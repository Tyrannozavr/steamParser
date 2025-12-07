#!/usr/bin/env python3
"""
Создание тестовой задачи с фильтром по паттерну и наклейкам для проверки оптимизации.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from core.models import SearchFilters, PatternList, StickersFilter, StickerInfo
from services.monitoring_service import MonitoringService
from services.proxy_manager import ProxyManager
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

async def create_test_task():
    """Создает тестовую задачу с фильтром по паттерну и наклейкам."""
    
    logger.info("🧪 Создаем тестовую задачу с фильтром по паттерну и наклейкам")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        
        proxy_manager = ProxyManager(session, redis_service=redis_service)
        proxy_manager.start_background_proxy_check()
        
        monitoring_service = MonitoringService(
            db_session=session,
            proxy_manager=proxy_manager,
            redis_service=redis_service
        )
        
        # Фильтры: паттерн 419 и наклейки (любые, минимальная цена 1$)
        filters = SearchFilters(
            appid=730,
            currency=1,
            item_name="StatTrak™ AK-47 | Redline (Well-Worn)",
            pattern_list=PatternList(patterns=[419], item_type="skin"),
            stickers_filter=StickersFilter(
                total_stickers_price_min=1.0  # Минимальная цена наклеек 1$
            )
        )
        
        # Создаем задачу
        task = await monitoring_service.add_monitoring_task(
            name="ТЕСТ: Паттерн 419 + Наклейки",
            item_name=filters.item_name,
            filters=filters,
            check_interval=30
        )
        
        logger.info(f"✅ Создана тестовая задача #{task.id}")
        logger.info(f"📋 Название: {task.name}")
        logger.info(f"💰 Предмет: {task.item_name}")
        logger.info(f"🔢 Паттерн: {filters.pattern_list.patterns}")
        logger.info(f"🏷️ Наклейки: мин. цена ${filters.stickers_filter.total_stickers_price_min}")
        logger.info(f"⏰ Интервал: {task.check_interval} сек")
        
        print(f"\n🎯 ТЕСТОВАЯ ЗАДАЧА СОЗДАНА:")
        print(f"   ID: {task.id}")
        print(f"   Название: {task.name}")
        print(f"   Предмет: {filters.item_name}")
        print(f"   Паттерн: {filters.pattern_list.patterns}")
        print(f"   Наклейки: мин. цена ${filters.stickers_filter.total_stickers_price_min}")
        print(f"\n📊 Ожидаем в логах:")
        print(f"   - Предметы с паттерном != 419 должны быть пропущены БЕЗ дополнительных запросов")
        print(f"   - Для предметов с паттерном 419 должны запрашиваться цены наклеек")
        print(f"   - В уведомлении должна быть указана цена наклеек")
        
        await redis_service.disconnect()
        
    finally:
        await session.close()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(create_test_task())

