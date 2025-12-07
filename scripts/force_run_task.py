#!/usr/bin/env python3
"""
Скрипт для принудительного запуска задачи
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
from core import MonitoringTask


async def main():
    """Принудительно запускает задачу."""
    if len(sys.argv) < 2:
        logger.error("❌ Использование: python3 scripts/force_run_task.py <task_id>")
        return
    
    task_id = int(sys.argv[1])
    logger.info(f"🚀 Принудительный запуск задачи {task_id}...")
    
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
        # Получаем задачу из БД
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            logger.error(f"❌ Задача {task_id} не найдена")
            return
        
        logger.info(f"📋 Задача найдена: {task.name} (ID={task.id})")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Активна: {task.is_active}")
        
        # Принудительно добавляем задачу в очередь Redis
        logger.info(f"📤 Добавляем задачу {task_id} в очередь Redis для немедленной обработки...")
        
        # Используем RedisService для публикации задачи в очередь
        if redis_service and redis_service.is_connected():
            from core import SearchFilters
            import json
            
            # Получаем фильтры из задачи
            filters_dict = json.loads(task.filters_json) if isinstance(task.filters_json, str) else task.filters_json
            filters = SearchFilters(**filters_dict)
            
            # Формируем данные задачи для очереди
            task_data = {
                'type': 'parsing_task',
                'task_id': task.id,
                'filters_json': filters_dict,
                'item_name': task.item_name,
                'appid': task.appid,
                'currency': task.currency or 1
            }
            
            # Публикуем в очередь (без префикса stream:, он добавляется автоматически)
            await redis_service.push_to_queue('parsing_tasks', task_data)
            
            logger.info(f"✅ Задача {task_id} добавлена в очередь Redis")
            logger.info(f"   Воркер парсинга обработает задачу в ближайшее время")
        else:
            logger.error(f"❌ Redis не подключен, невозможно добавить задачу в очередь")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

