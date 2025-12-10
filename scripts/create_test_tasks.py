#!/usr/bin/env python3
"""
Скрипт для создания нескольких тестовых задач для проверки устойчивости системы
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
from core import MonitoringTask, SearchFilters
from datetime import datetime


async def create_task(item_name: str, patterns: list, max_price: float, check_interval: int = 60):
    """Создает одну задачу."""
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
        # Проверяем, существует ли уже задача
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.item_name == item_name)
        )
        existing_task = result.scalar_one_or_none()
        
        if existing_task:
            logger.info(f"ℹ️ Задача для '{item_name}' уже существует (ID={existing_task.id}), пропускаем")
            return existing_task.id
        
        # Создаем фильтры
        from core import PatternList, StickersFilter
        filters = SearchFilters(
            appid=730,
            currency=1,
            item_name=item_name,
            max_price=max_price,
            pattern_list=PatternList(
                patterns=patterns,
                item_type="skin"
            ),
            stickers_filter=StickersFilter(
                stickers=[],
                min_stickers_price=0.0
            ),
            auto_update_base_price=False
        )
        
        # Создаем задачу
        new_task = await monitoring_service.add_monitoring_task(
            name=item_name,
            item_name=item_name,
            filters=filters,
            check_interval=check_interval
        )
        
        if new_task:
            logger.info(f"✅ Задача создана: ID={new_task.id}, Название: {new_task.name}")
            return new_task.id
        else:
            logger.error(f"❌ Не удалось создать задачу для '{item_name}'")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка при создании задачи для '{item_name}': {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return None
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


async def main():
    """Создает несколько тестовых задач."""
    logger.info("🚀 Создание тестовых задач для проверки устойчивости системы...")
    
    # Список задач для создания
    tasks_to_create = [
        {
            "item_name": "AK-47 | Redline (Field-Tested)",
            "patterns": [661, 321, 179, 555],
            "max_price": 50.0,
            "check_interval": 120
        },
        {
            "item_name": "AWP | Asiimov (Field-Tested)",
            "patterns": [103, 104, 105],
            "max_price": 80.0,
            "check_interval": 120
        },
        {
            "item_name": "M4A4 | Howl (Field-Tested)",
            "patterns": [12, 13, 14],
            "max_price": 150.0,
            "check_interval": 180
        },
        {
            "item_name": "Glock-18 | Fade (Factory New)",
            "patterns": [1, 2, 3],
            "max_price": 200.0,
            "check_interval": 180
        },
    ]
    
    created_tasks = []
    for task_data in tasks_to_create:
        task_id = await create_task(
            item_name=task_data["item_name"],
            patterns=task_data["patterns"],
            max_price=task_data["max_price"],
            check_interval=task_data["check_interval"]
        )
        if task_id:
            created_tasks.append(task_id)
        await asyncio.sleep(1)  # Небольшая задержка между созданием задач
    
    logger.info(f"✅ Создано задач: {len(created_tasks)}")
    logger.info(f"   ID задач: {created_tasks}")


if __name__ == "__main__":
    asyncio.run(main())
