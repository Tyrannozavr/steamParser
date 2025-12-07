#!/usr/bin/env python3
"""
Скрипт для добавления задачи 126: AK-47 | Redline (Field-Tested)
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, SearchFilters, FloatRange, PatternList
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔍 Создаем задачу 126: AK-47 | Redline (Field-Tested)...")
    
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
    
    # Создаем фильтры для задачи 126
    filters = SearchFilters(
        item_name="AK-47 | Redline (Field-Tested)",
        appid=730,
        currency=1,
        max_price=50.0,  # Макс. цена: $50.00
        float_range=FloatRange(min=0.350000, max=0.360000),  # Float: 0.350000 - 0.360000
        pattern_list=PatternList(patterns=[522], item_type="skin")  # Паттерн: 522 (skin)
    )
    
    try:
        task = await monitoring_service.add_monitoring_task(
            name="AK-47 | Redline (Field-Tested) - Паттерн 522",
            item_name="AK-47 | Redline (Field-Tested)",
            filters=filters,
            check_interval=60  # Проверка каждую минуту
        )
        
        logger.info(f"✅ Задача 126 создана успешно!")
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Макс. цена: ${filters.max_price:.2f}")
        logger.info(f"   Float: {filters.float_range.min:.6f} - {filters.float_range.max:.6f}")
        logger.info(f"   Паттерны: {filters.pattern_list.patterns} ({filters.pattern_list.item_type})")
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

