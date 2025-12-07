"""Точечный тест парсинга наклеек для одного лота."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import Config, DatabaseManager
from core.steam_parser import SteamMarketParser
from core import SearchFilters, PatternList
from services.proxy_manager import ProxyManager
from services.redis_service import RedisService
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

async def test_sticker_parsing():
    """Тестирует парсинг наклеек для одного конкретного лота."""
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    
    parser = SteamMarketParser(
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    try:
        # Тестируем конкретный предмет с паттерном 419
        item_name = "StatTrak™ AK-47 | Redline (Well-Worn)"
        hash_name = "StatTrak™ AK-47 | Redline (Well-Worn)"
        appid = 730
        
        logger.info(f"🔍 ТОЧЕЧНЫЙ ТЕСТ: Парсим один лот для '{item_name}'")
        logger.info(f"   Цель: проверить, что наклейки парсятся из assets")
        
        # Создаем фильтры
        filters = SearchFilters(
            appid=appid,
            currency=1,
            item_name=item_name,
            pattern_list=PatternList(patterns=[419], item_type="skin")
        )
        
        # Парсим ВСЕ лоты на странице через _parse_all_listings
        logger.info(f"📡 Запрашиваем данные через API /render/...")
        parsed_listings = await parser._parse_all_listings(
            appid=appid,
            hash_name=hash_name,
            filters=filters,
            target_patterns={419}
        )
        
        logger.info(f"📊 Получено лотов: {len(parsed_listings)}")
        
        # Ищем лот с паттерном 419
        lot_419 = None
        for listing in parsed_listings:
            if listing.pattern == 419:
                lot_419 = listing
                break
        
        if not lot_419:
            logger.error("❌ Лот с паттерном 419 не найден!")
            return
        
        logger.info(f"✅ Найден лот с паттерном 419:")
        logger.info(f"   Цена: ${lot_419.item_price:.2f}")
        logger.info(f"   Float: {lot_419.float_value}")
        logger.info(f"   Listing ID: {lot_419.listing_id}")
        logger.info(f"   Наклеек: {len(lot_419.stickers) if lot_419.stickers else 0}")
        
        if lot_419.stickers and len(lot_419.stickers) > 0:
            logger.info(f"✅ НАКЛЕЙКИ НАЙДЕНЫ: {len(lot_419.stickers)} штук")
            for i, sticker in enumerate(lot_419.stickers):
                sticker_name = sticker.name if hasattr(sticker, 'name') else str(sticker)
                sticker_wear = sticker.wear if hasattr(sticker, 'wear') else None
                sticker_price = sticker.price if hasattr(sticker, 'price') else None
                price_str = f"${sticker_price:.2f}" if sticker_price else "$0.00"
                logger.info(f"   [{i+1}] {sticker_name} (wear: {sticker_wear}, price: {price_str})")
            logger.info(f"   Общая цена наклеек: ${lot_419.total_stickers_price:.2f}")
        else:
            logger.error("❌ НАКЛЕЙКИ НЕ НАЙДЕНЫ!")
            logger.error(f"   lot_419.stickers = {lot_419.stickers}")
            logger.error(f"   type = {type(lot_419.stickers)}")
        
        # Теперь проверяем, что наклейки передаются после прохождения фильтров
        logger.info(f"\n🔍 Проверяем передачу наклеек после прохождения фильтров...")
        from core.steam_filter_methods import SteamFilterMethods
        matches = await parser._matches_filters(
            item={"name": item_name},
            filters=filters,
            parsed_data=lot_419
        )
        
        if matches:
            logger.info(f"✅ Лот прошел фильтры")
            logger.info(f"🔍 ПРОВЕРКА НАКЛЕЕК: lot_419.stickers={lot_419.stickers}, len={len(lot_419.stickers) if lot_419.stickers else 0}")
            
            if lot_419.stickers and len(lot_419.stickers) > 0:
                logger.info(f"✅ НАЙДЕНЫ НАКЛЕЙКИ В listing_data: {len(lot_419.stickers)} штук")
                
                # Проверяем, есть ли цены
                has_prices = any(s.price and s.price > 0 for s in lot_419.stickers if hasattr(s, 'price'))
                logger.info(f"   Есть цены: {has_prices}")
                
                if not has_prices:
                    logger.info(f"🏷️ Запрашиваем цены на наклейки...")
                    from parsers.sticker_prices import StickerPricesAPI
                    sticker_names = [s.wear or s.name for s in lot_419.stickers if s.wear or s.name]
                    if sticker_names:
                        prices = await StickerPricesAPI.get_stickers_prices_batch(
                            sticker_names, 
                            proxy=parser.proxy, 
                            delay=0.3, 
                            redis_service=redis_service, 
                            proxy_manager=proxy_manager
                        )
                        # Обновляем цены
                        for sticker in lot_419.stickers:
                            sticker_name = sticker.wear or sticker.name
                            if sticker_name and sticker_name in prices and prices[sticker_name] is not None:
                                sticker.price = prices[sticker_name]
                        lot_419.total_stickers_price = sum(s.price for s in lot_419.stickers if hasattr(s, 'price') and s.price)
                        logger.info(f"🏷️ Обновлены цены для {len([s for s in lot_419.stickers if hasattr(s, 'price') and s.price])} наклеек, общая цена: ${lot_419.total_stickers_price:.2f}")
            else:
                logger.error("❌ НАКЛЕЙКИ НЕ ПЕРЕДАНЫ В listing_data!")
        else:
            logger.error("❌ Лот не прошел фильтры!")
        
    finally:
        await parser.close()
        await redis_service.disconnect()
        await session.close()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_sticker_parsing())

