#!/usr/bin/env python3
"""
Скрипт для пересоздания задачи #24: MP9 | Starlight Protector (Field-Tested)
"""
import asyncio
import sys
from pathlib import Path

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
    """Пересоздает задачу #24 с теми же параметрами."""
    task_id = 24
    item_name = "MP9 | Starlight Protector (Field-Tested)"
    
    logger.info(f"🔍 Ищем задачу #{task_id} для '{item_name}'...")
    
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
        # Ищем задачу по ID
        task = await session.get(MonitoringTask, task_id)
        
        if task:
            logger.info(f"📋 Найдена задача #{task_id}:")
            logger.info(f"   - Название: {task.name}")
            logger.info(f"   - Предмет: {task.item_name}")
            logger.info(f"   - Активна: {task.is_active}")
            
            # Получаем фильтры из JSON
            filters_dict = task.get_filters_dict()
            logger.info(f"   - Фильтры: {filters_dict}")
            
            # Сохраняем параметры для пересоздания
            old_name = task.name
            old_item_name = task.item_name
            old_check_interval = task.check_interval
            old_appid = task.appid
            old_currency = task.currency
            old_filters_dict = filters_dict
            
            # Удаляем задачу
            logger.info(f"🗑️  Удаляем задачу #{task_id}...")
            success = await monitoring_service.delete_monitoring_task(task_id)
            if success:
                logger.info(f"✅ Задача #{task_id} успешно удалена")
            else:
                logger.error(f"❌ Не удалось удалить задачу #{task_id}")
                return
        else:
            logger.warning(f"⚠️  Задача #{task_id} не найдена, создаем новую с параметрами по умолчанию")
            old_name = f"{item_name}"
            old_item_name = item_name
            old_check_interval = 300
            old_appid = 730
            old_currency = 1
            old_filters_dict = {
                "item_name": item_name,
                "max_price": 100.0,
                "pattern_list": {
                    "patterns": [173, 864, 208, 567],
                    "item_type": "skin"
                },
                "stickers_filter": {
                    "min_stickers_price": 0.0,
                    "max_overpay_coefficient": None
                }
            }
        
        # Создаем SearchFilters из словаря
        from core import FloatRange
        filters = SearchFilters.model_validate(old_filters_dict)
        filters.item_name = old_item_name
        filters.appid = old_appid
        filters.currency = old_currency
        
        # Создаем новую задачу с теми же параметрами
        logger.info(f"📝 Создаем новую задачу для '{old_item_name}'...")
        logger.info(f"   📋 Параметры:")
        logger.info(f"      - Макс. цена: ${filters.max_price}")
        logger.info(f"      - Паттерны: {filters.pattern_list.patterns if filters.pattern_list else 'нет'}")
        logger.info(f"      - Интервал проверки: {old_check_interval}с")
        
        new_task = await monitoring_service.add_monitoring_task(
            name=old_name,
            item_name=old_item_name,
            filters=filters,
            check_interval=old_check_interval
        )
        
        if new_task:
            logger.info(f"✅ Новая задача создана: ID={new_task.id}, Название: {new_task.name}")
            logger.info(f"   📋 Параметры: appid={new_task.appid}, currency={new_task.currency}, check_interval={new_task.check_interval}с")
            logger.info(f"   🔍 Фильтры: max_price=${filters.max_price}, pattern={filters.pattern_list.patterns}")
            
            # Сбрасываем next_check для немедленного запуска
            from datetime import datetime
            new_task.next_check = datetime.now()
            await session.commit()
            logger.info(f"   ⏰ next_check установлен на текущее время для немедленного запуска")
            
            # Публикуем задачу в Redis очередь для немедленного выполнения
            if redis_service and redis_service.is_connected():
                try:
                    queue_key = "parsing_tasks"
                    task_message = {
                        "task_id": new_task.id,
                        "action": "parse"
                    }
                    await redis_service.push_to_queue(queue_key, task_message)
                    logger.info(f"   📤 Задача добавлена в Redis очередь для немедленного выполнения")
                except Exception as e:
                    logger.warning(f"   ⚠️ Не удалось добавить задачу в очередь: {e}")
        else:
            logger.error("❌ Не удалось создать новую задачу")
            
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

