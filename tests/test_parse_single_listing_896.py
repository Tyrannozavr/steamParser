"""
Тестовый скрипт для проверки парсинга одного лота с паттерном 896.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import Config, SearchFilters, DatabaseManager
from core.steam_parser import SteamMarketParser
from services.redis_service import RedisService
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_parse_single_listing():
    """Тестирует парсинг одного лота с паттерном 896."""
    logger.info("🧪 Начинаем тест парсинга одного лота с паттерном 896")
    
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
    
    # Инициализируем Redis (если нужно)
    redis_service = None
    try:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        logger.info("✅ Redis подключен")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}")
    
    # Создаем парсер
    parser = SteamMarketParser(
        proxy=None,
        timeout=30,
        redis_service=redis_service,
        proxy_manager=None
    )
    
    await parser._ensure_client()
    
    # Парсим все лоты для этого предмета
    logger.info("🔍 Начинаем парсинг всех лотов...")
    target_patterns = set(filters.pattern_list.patterns)
    logger.info(f"🎯 Ищем паттерны: {target_patterns}")
    
    try:
        all_parsed_listings = await parser._parse_all_listings(
            appid=filters.appid,
            hash_name=filters.item_name,
            filters=filters,
            target_patterns=target_patterns,
            task_logger=None
        )
        
        logger.info(f"📊 Получено {len(all_parsed_listings)} лотов из _parse_all_listings")
        
        # Ищем лоты с паттерном 896
        patterns_896 = [ld for ld in all_parsed_listings if ld.pattern == 896]
        logger.info(f"🎯 Найдено {len(patterns_896)} лотов с паттерном 896")
        
        if patterns_896:
            for ld in patterns_896:
                logger.info(f"   - listing_id={ld.listing_id}, pattern={ld.pattern}, price=${ld.item_price:.2f}")
                
                # Проверяем фильтры для этого лота
                item = {"name": filters.item_name}
                from core.steam_filter_methods import SteamFilterMethods
                test_filter = SteamFilterMethods()
                matches = await test_filter._matches_filters(item, filters, ld)
                
                logger.info(f"   ✅ Проверка фильтров: matches={matches}")
                if matches:
                    logger.info(f"   🎉 ЛОТ С ПАТТЕРНОМ 896 ПРОШЕЛ ФИЛЬТРЫ!")
                else:
                    logger.error(f"   ❌ ЛОТ С ПАТТЕРНОМ 896 НЕ ПРОШЕЛ ФИЛЬТРЫ!")
        else:
            logger.error("❌ Лоты с паттерном 896 не найдены в результатах парсинга")
            
            # Показываем все найденные паттерны
            patterns_found = [ld.pattern for ld in all_parsed_listings if ld.pattern is not None]
            logger.info(f"   Найденные паттерны (первые 30): {patterns_found[:30]}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при парсинге: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        if redis_service:
            await redis_service.disconnect()


if __name__ == "__main__":
    asyncio.run(test_parse_single_listing())

