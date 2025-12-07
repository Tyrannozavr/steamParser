"""
Тестовый скрипт для проверки фильтрации паттерна 896.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import Config, SearchFilters
from core.steam_filter_methods import SteamFilterMethods
from core.models import ParsedItemData
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


class TestFilter(SteamFilterMethods):
    """Тестовый класс для проверки фильтров."""
    pass


async def test_pattern_896_filter():
    """Тестирует фильтрацию паттерна 896."""
    logger.info("🧪 Начинаем тест фильтрации паттерна 896")
    
    # Создаем фильтры как в задаче #85
    filters = SearchFilters(
        appid=730,
        currency=1,
        item_name="StatTrak™ AK-47 | Redline (Field-Tested)",
        max_price=200.0,
        pattern_list={
            "patterns": [63, 575, 896],
            "item_type": "skin"
        },
        auto_update_base_price=False
    )
    
    logger.info(f"📋 Фильтры: pattern_list={filters.pattern_list}")
    logger.info(f"   patterns={filters.pattern_list.patterns} (типы: {[type(p).__name__ for p in filters.pattern_list.patterns]})")
    
    # Создаем тестовый ParsedItemData с паттерном 896
    parsed_data = ParsedItemData(
        float_value=0.357310503721237183,
        pattern=896,  # Паттерн 896
        stickers=[],
        total_stickers_price=0.0,
        item_name="StatTrak™ AK-47 | Redline (Field-Tested)",
        item_price=101.11,
        inspect_links=[],
        item_type="skin",
        is_stattrak=True,
        listing_id="747163221828673397"
    )
    
    logger.info(f"📦 Тестовые данные: pattern={parsed_data.pattern} (тип: {type(parsed_data.pattern).__name__})")
    
    # Создаем тестовый item
    item = {
        "name": "StatTrak™ AK-47 | Redline (Field-Tested)",
        "listingid": "747163221828673397"
    }
    
    # Создаем тестовый фильтр
    test_filter = TestFilter()
    
    # Проверяем фильтры
    logger.info("🔍 Проверяем фильтры...")
    matches = await test_filter._matches_filters(item, filters, parsed_data)
    
    logger.info(f"✅ Результат проверки фильтров: matches={matches}")
    
    if matches:
        logger.info("🎉 ПАТТЕРН 896 ПРОШЕЛ ФИЛЬТРЫ!")
    else:
        logger.error("❌ ПАТТЕРН 896 НЕ ПРОШЕЛ ФИЛЬТРЫ!")
        
        # Проверяем вручную
        logger.info("🔍 Проверяем вручную:")
        logger.info(f"   pattern={parsed_data.pattern} (тип: {type(parsed_data.pattern).__name__})")
        logger.info(f"   patterns={filters.pattern_list.patterns} (типы: {[type(p).__name__ for p in filters.pattern_list.patterns]})")
        logger.info(f"   pattern in patterns: {parsed_data.pattern in filters.pattern_list.patterns}")
        logger.info(f"   pattern == 896: {parsed_data.pattern == 896}")
        logger.info(f"   str(pattern) == '896': {str(parsed_data.pattern) == '896'}")
        
        # Проверяем каждый паттерн отдельно
        for p in filters.pattern_list.patterns:
            logger.info(f"   Сравнение: {parsed_data.pattern} == {p} (тип: {type(p).__name__}): {parsed_data.pattern == p}")
            logger.info(f"   Сравнение: {parsed_data.pattern} == {p} (int): {int(parsed_data.pattern) == int(p)}")
            logger.info(f"   Сравнение: str({parsed_data.pattern}) == str({p}): {str(parsed_data.pattern) == str(p)}")


if __name__ == "__main__":
    asyncio.run(test_pattern_896_filter())

