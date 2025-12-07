#!/usr/bin/env python3
"""
Скрипт для удаления задачи мониторинга.
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


async def main():
    """Удаляет задачу мониторинга."""
    if len(sys.argv) < 2:
        logger.error("❌ Использование: python3 scripts/delete_task.py <task_id>")
        return
    
    task_id = int(sys.argv[1])
    logger.info(f"🗑️  Удаление задачи {task_id}...")
    
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
        success = await monitoring_service.delete_monitoring_task(task_id)
        if success:
            logger.info(f"✅ Задача {task_id} успешно удалена")
        else:
            logger.error(f"❌ Задача {task_id} не найдена")
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении задачи: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

