#!/usr/bin/env python3
"""
Скрипт для обновления задачи 29 с новыми параметрами
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.database import DatabaseManager
from services.redis_service import RedisService
from services.proxy_manager_factory import ProxyManagerFactory
from services.monitoring_service import MonitoringService
from core.config import Config
from sqlalchemy import select
from core import MonitoringTask, SearchFilters, PatternList, StickersFilter


async def main():
    """Обновляет задачу 29 с новыми параметрами."""
    task_id = 29
    new_patterns = [14, 18, 461, 513, 173, 867, 456, 359, 232]
    new_max_price = 120.0
    
    logger.info(f"📝 Обновляем задачу {task_id} с паттернами {new_patterns} и max_price=${new_max_price}...")
    
    # Инициализация БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    # Инициализация Redis
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        logger.info("✅ Redis подключен")
    
    # Инициализация ProxyManager через фабрику
    proxy_manager = await ProxyManagerFactory.get_instance(
        db_session=session,
        redis_service=redis_service,
        default_delay=0.2,
        site="steam"
    )
    
    # Инициализация MonitoringService
    monitoring_service = MonitoringService(
        db_session=session,
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    try:
        # Находим задачу
        task = await session.get(MonitoringTask, task_id)
        if not task:
            logger.error(f"❌ Задача {task_id} не найдена")
            return
        
        logger.info(f"📋 Текущая задача: {task.name}")
        logger.info(f"   Текущие паттерны: {task.filters_json.get('pattern_list', {}).get('patterns', [])}")
        logger.info(f"   Текущий max_price: {task.filters_json.get('max_price', 0)}")
        
        # Обновляем фильтры
        from core import SearchFilters, PatternList, StickersFilter
        
        filters = SearchFilters(
            item_name=task.item_name,
            appid=task.filters_json.get('appid', 730),
            currency=task.filters_json.get('currency', 1),
            max_price=new_max_price,
            pattern_list=PatternList(
                patterns=new_patterns,
                item_type=task.filters_json.get('pattern_list', {}).get('item_type', 'skin')
            ),
            stickers_filter=StickersFilter(
                min_stickers_price=task.filters_json.get('stickers_filter', {}).get('min_stickers_price', 0.0),
                max_overpay_coefficient=task.filters_json.get('stickers_filter', {}).get('max_overpay_coefficient')
            )
        )
        
        # Обновляем задачу
        await monitoring_service.update_monitoring_task(
            task_id=task_id,
            filters=filters
        )
        
        await session.commit()
        logger.info(f"✅ Задача {task_id} обновлена")
        logger.info(f"   Новые паттерны: {new_patterns}")
        logger.info(f"   Новый max_price: ${new_max_price}")
        
        # Сбрасываем next_check для немедленного запуска
        task.next_check = datetime.now()
        await session.commit()
        logger.info(f"   ⏰ next_check установлен на текущее время для немедленного запуска")
        
        # Публикуем задачу в Redis очередь для немедленного выполнения
        if redis_service and redis_service.is_connected():
            try:
                queue_key = "parsing_tasks"
                task_message = {
                    "task_id": task_id,
                    "action": "parse"
                }
                await redis_service.push_to_queue(queue_key, task_message)
                logger.info(f"   📤 Задача добавлена в Redis очередь для немедленного выполнения")
            except Exception as e:
                logger.warning(f"   ⚠️ Не удалось добавить задачу в очередь: {e}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

