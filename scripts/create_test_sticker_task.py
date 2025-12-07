#!/usr/bin/env python3
"""
Скрипт для создания тестовой задачи с фильтром по наклейкам.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, SearchFilters, StickersFilter
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from core.config import Config
from loguru import logger


async def main():
    """Основная функция."""
    logger.info("🔍 Создаю тестовую задачу для проверки фильтра по наклейкам...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        
        # Инициализируем сервисы
        redis_service = None
        if Config.REDIS_ENABLED:
            redis_service = RedisService(Config.REDIS_URL)
            try:
                await redis_service.connect()
            except Exception as e:
                logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}")
        
        proxy_manager = ProxyManager(session, redis_service=redis_service)
        monitoring_service = MonitoringService(session, proxy_manager)
        
        # Создаем фильтры для тестовой задачи
        # Ищем AK-47 | Nightwish (Well-Worn) с наклейками
        filters = SearchFilters(item_name="AK-47 | Nightwish (Well-Worn)")
        
        # Устанавливаем максимальную цену (например, $100)
        filters.max_price = 100.0
        
        # Фильтр по наклейкам: формула S = D + (P * x)
        # Максимальный коэффициент переплаты: 0.1 (10%)
        # Минимальная цена наклеек: $5.0
        filters.stickers_filter = StickersFilter(
            max_overpay_coefficient=0.1,  # 10% переплата
            min_stickers_price=5.0  # Минимум $5 наклеек
        )
        
        # Создаем задачу
        task = await monitoring_service.add_monitoring_task(
            name="Тест фильтра наклеек - AK-47 Nightwish",
            item_name="AK-47 | Nightwish (Well-Worn)",
            filters=filters,
            check_interval=60  # Проверка каждую минуту
        )
        
        logger.info(f"✅ Задача создана!")
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Макс. цена: ${filters.max_price}")
        logger.info(f"   Макс. переплата за наклейки: {filters.stickers_filter.max_overpay_coefficient * 100}%")
        logger.info(f"   Мин. цена наклеек: ${filters.stickers_filter.min_stickers_price}")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        
        # Активируем задачу
        await monitoring_service.update_monitoring_task(task.id, is_active=True)
        logger.info(f"✅ Задача активирована!")
        
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

