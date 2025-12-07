#!/usr/bin/env python3
"""
Скрипт для добавления задачи, которая точно вернет результаты.
Использует широкие фильтры для гарантированного результата.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, SearchFilters
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔍 Создаем задачу с широкими фильтрами для гарантированного результата...")
    
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
    
    # Создаем фильтры с очень широкими ограничениями
    # Используем популярный предмет с очень высокой максимальной ценой
    filters = SearchFilters(
        item_name="AK-47 | Redline (Field-Tested)",
        max_price=500.0,  # Очень высокая цена, чтобы найти много предметов
        appid=730,
        currency=1
    )
    
    try:
        task = await monitoring_service.add_monitoring_task(
            name="✅ Проверка уведомлений (широкие фильтры)",
            item_name="AK-47 | Redline (Field-Tested)",
            filters=filters,
            check_interval=30  # Проверка каждые 30 секунд для быстрого результата
        )
        
        logger.info(f"✅ Задача создана успешно!")
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Макс. цена: ${filters.max_price}")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        logger.info(f"   Активна: {task.is_active}")
        logger.info(f"")
        logger.info(f"📋 Задача будет проверяться каждые {task.check_interval} секунд")
        logger.info(f"📊 Используйте команду /tasks в Telegram боте для просмотра задач")
        logger.info(f"🔔 Уведомления будут отправляться в Telegram при нахождении предметов")
        
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

