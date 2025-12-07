#!/usr/bin/env python3
"""
Скрипт для добавления тестовой задачи мониторинга с широкими фильтрами.
Эта задача должна гарантированно найти хотя бы один предмет.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, SearchFilters
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔍 Создаем тестовую задачу с широкими фильтрами...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    # Инициализируем ProxyManager
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    
    # Инициализируем MonitoringService
    monitoring_service = MonitoringService(
        session,
        proxy_manager,
        notification_callback=None,
        redis_service=redis_service
    )
    
    # Создаем фильтры с минимальными ограничениями
    # Используем популярный предмет с широким диапазоном цен
    filters = SearchFilters(
        item_name="AK-47 | Redline",
        max_price=200.0,  # Достаточно высокая цена, чтобы найти много предметов
        appid=730,
        currency=1
    )
    
    try:
        task = await monitoring_service.add_monitoring_task(
            name="🧪 Тестовая задача (гарантированный результат)",
            item_name="AK-47 | Redline",
            filters=filters,
            check_interval=60  # Проверка каждую минуту
        )
        
        logger.info(f"✅ Задача создана успешно!")
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Макс. цена: ${filters.max_price}")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        logger.info(f"   Активна: {task.is_active}")
        logger.info(f"")
        logger.info(f"📋 Используйте команду /tasks в Telegram боте для просмотра задач")
        logger.info(f"📊 Используйте команду /status для просмотра статистики")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании задачи: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

