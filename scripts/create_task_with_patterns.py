#!/usr/bin/env python3
"""
Скрипт для создания задачи с указанными паттернами
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
from core import SearchFilters, PatternList, StickersFilter
from sqlalchemy import text, select
from core import MonitoringTask, FoundItem


async def main():
    """Создает задачу с указанными паттернами."""
    item_name = "MP9 | Starlight Protector (Field-Tested)"
    patterns = [14, 18, 461, 513, 173]
    max_price = 100.0
    
    logger.info(f"📝 Создаем задачу для '{item_name}' с паттернами {patterns} и max_price=${max_price}...")
    
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
        # Удаляем старую задачу, если она существует
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.item_name == item_name)
        )
        tasks = result.scalars().all()
        if tasks:
            for task in tasks:
                logger.info(f"🗑️  Удаляем задачу {task.id}...")
                await monitoring_service.delete_monitoring_task(task.id)
                logger.info(f"✅ Задача {task.id} удалена")
        
        # Удаляем все найденные предметы для этого item_name
        logger.info(f"🗑️  Удаляем все найденные предметы для '{item_name}'...")
        delete_result = await session.execute(
            text("DELETE FROM found_items WHERE item_name = :item_name"),
            {"item_name": item_name}
        )
        deleted_count = delete_result.rowcount
        logger.info(f"✅ Удалено {deleted_count} найденных предметов")
        
        await session.commit()
        
        # Создаем новую задачу
        filters = SearchFilters(
            item_name=item_name,
            appid=730,
            currency=1,
            max_price=max_price,
            pattern_list=PatternList(
                patterns=patterns,
                item_type="skin"
            ),
            stickers_filter=StickersFilter(
                min_stickers_price=0.0,
                max_overpay_coefficient=None
            )
        )
        
        new_task = await monitoring_service.add_monitoring_task(
            name=item_name,
            item_name=item_name,
            filters=filters,
            check_interval=60  # 1 минута для быстрого теста
        )
        
        if new_task:
            logger.info(f"✅ Новая задача создана: ID={new_task.id}, Название: {new_task.name}")
            logger.info(f"   📋 Параметры: appid=730, currency=1, check_interval=60с")
            logger.info(f"   🔍 Фильтры: max_price=${max_price}, pattern={patterns}")
            
            # Сбрасываем next_check для немедленного запуска
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

