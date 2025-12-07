#!/usr/bin/env python3
"""
Тест парсинга Desert Eagle | Heat Treated для проверки:
1. Правильного получения вариантов предмета
2. Парсинга float и pattern с первых страниц
3. Пагинации по страницам
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from services.monitoring_service import MonitoringService
from core.models import SearchFilters, FloatRange, PatternList
from loguru import logger

async def create_test_task():
    """Создает тестовую задачу для Desert Eagle | Heat Treated"""
    
    logger.info("🧪 Создаем тестовую задачу для проверки парсинга Desert Eagle")
    
    db_manager = DatabaseManager()
    
    async with await db_manager.get_session() as session:
        monitoring_service = MonitoringService(db_session=session)
        
        # Фильтры для поиска предмета на первых страницах
        filters = SearchFilters(
            appid=730,
            currency=1,
            item_name="Desert Eagle | Heat Treated",
            max_price=5.0,  # Ограничиваем цену чтобы найти на первых страницах
            float_range=FloatRange(min=0.1, max=0.9),  # Широкий диапазон float
            # Не указываем конкретный pattern, чтобы найти любой на первых страницах
        )
        
        # Создаем задачу
        task = await monitoring_service.add_monitoring_task(
            item_name="Desert Eagle | Heat Treated - ТЕСТ ПАРСИНГА",
            filters=filters,
            check_interval=30  # Проверяем каждые 30 секунд
        )
        
        logger.info(f"✅ Создана тестовая задача #{task.id}")
        logger.info(f"📋 Название: {task.name}")
        logger.info(f"💰 Макс. цена: ${filters.max_price}")
        logger.info(f"🔢 Float: {filters.float_range.min} - {filters.float_range.max}")
        logger.info(f"⏰ Интервал: {task.check_interval} сек")
        
        print(f"\n🎯 ТЕСТОВАЯ ЗАДАЧА СОЗДАНА:")
        print(f"   ID: {task.id}")
        print(f"   Название: {task.name}")
        print(f"   Предмет: {filters.item_name}")
        print(f"   Макс. цена: ${filters.max_price}")
        print(f"   Float: {filters.float_range.min} - {filters.float_range.max}")
        print(f"   Интервал: {task.check_interval} сек")
        print(f"\n📊 Ожидаем в логах:")
        print(f"   - Поиск вариантов предмета через новый API")
        print(f"   - Парсинг страниц: 1 из X, 2 из X, и т.д.")
        print(f"   - Извлечение float и pattern из asset_properties")
        print(f"   - Найденные предметы с данными")

if __name__ == "__main__":
    asyncio.run(create_test_task())
