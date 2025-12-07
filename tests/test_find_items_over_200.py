#!/usr/bin/env python3
"""
Тестовый скрипт для поиска всех предметов с наклейками > $200 на странице.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.steam_parser import SteamMarketParser
from parsers.sticker_prices import StickerPricesAPI
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.config import Config
from core.database import DatabaseManager
from core.utils.sticker_name_matcher import find_best_match
from loguru import logger
from bs4 import BeautifulSoup

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def find_items_over_200():
    """Ищет все предметы с наклейками > $200."""
    
    hash_name = "AK-47 | Redline (Minimal Wear)"
    appid = 730
    
    logger.info(f"🔍 Ищем предметы с наклейками > $200: {hash_name}")
    
    # Инициализируем компоненты
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    
    proxy_obj = await proxy_manager.get_next_proxy(force_refresh=False)
    proxy_url = proxy_obj.url if proxy_obj else None
    
    try:
        parser = SteamMarketParser(proxy=proxy_url, timeout=30, redis_service=redis_service, proxy_manager=proxy_manager)
        await parser._ensure_client()
        
        items_over_200 = []
        
        # Парсим первые 5 страниц
        for page in range(5):
            start = page * 20
            logger.info(f"📄 Страница {page + 1} (start={start})...")
            
            render_data = await parser._fetch_render_api(appid, hash_name, start=start, count=20)
            if not render_data:
                break
            
            if 'assets' in render_data and '730' in render_data['assets']:
                app_assets = render_data['assets']['730']
                listinginfo = render_data.get('listinginfo', {})
                results_html = render_data.get('results_html', '')
                
                # Парсим HTML для получения цен лотов
                from parsers.item_page_parser import ItemPageParser
                parser_obj = ItemPageParser(results_html)
                page_listings = parser_obj.get_all_listings()
                
                for contextid, items in app_assets.items():
                    for itemid, item in items.items():
                        # Ищем listing_id и цену
                        listing_id = None
                        listing_price = None
                        for lid, listing_data in listinginfo.items():
                            if 'asset' in listing_data:
                                asset_info = listing_data['asset']
                                if str(asset_info.get('id')) == str(itemid):
                                    listing_id = lid
                                    if 'sell_price' in listing_data:
                                        listing_price = listing_data['sell_price'] / 100.0
                                    break
                        
                        # Парсим наклейки
                        stickers_found = []
                        if 'descriptions' in item:
                            for desc in item['descriptions']:
                                if desc.get('name') == 'sticker_info':
                                    sticker_html = desc.get('value', '')
                                    if sticker_html:
                                        sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                        images = sticker_soup.find_all('img')
                                        
                                        for idx, img in enumerate(images):
                                            if idx >= 5:
                                                break
                                            title = img.get('title', '')
                                            if title and 'Sticker:' in title:
                                                sticker_name = title.replace('Sticker: ', '').strip()
                                                if sticker_name and len(sticker_name) > 3:
                                                    stickers_found.append(sticker_name)
                        
                        if stickers_found:
                            # Получаем цены для наклеек
                            unique_stickers = list(dict.fromkeys(stickers_found))
                            prices = await StickerPricesAPI.get_stickers_prices_batch(
                                unique_stickers,
                                appid=appid,
                                currency=1,
                                proxy=proxy_url,
                                delay=0.2,
                                redis_service=redis_service,
                                proxy_manager=proxy_manager
                            )
                            
                            # Вычисляем общую цену с гибким сопоставлением
                            total_price = 0.0
                            for sticker_name in stickers_found:
                                # Точное совпадение
                                if sticker_name in prices and prices[sticker_name] is not None:
                                    total_price += prices[sticker_name]
                                else:
                                    # Гибкое сопоставление
                                    valid_prices = {k: v for k, v in prices.items() if v is not None}
                                    if valid_prices:
                                        match_result = find_best_match(sticker_name, valid_prices, min_similarity=0.5)
                                        if match_result:
                                            matched_name, similarity = match_result
                                            total_price += valid_prices[matched_name]
                            
                            if total_price >= 200.0:
                                items_over_200.append({
                                    'listing_id': listing_id,
                                    'price': listing_price,
                                    'stickers': stickers_found,
                                    'total_stickers_price': total_price
                                })
                                logger.info(f"🎯 НАЙДЕН ПРЕДМЕТ С НАКЛЕЙКАМИ > $200!")
                                logger.info(f"   listing_id: {listing_id}")
                                logger.info(f"   цена предмета: ${listing_price:.2f}" if listing_price else "   цена предмета: N/A")
                                logger.info(f"   наклейки: {stickers_found}")
                                logger.info(f"   общая цена наклеек: ${total_price:.2f}")
            
            await asyncio.sleep(0.5)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 ИТОГО: Найдено предметов с наклейками > $200: {len(items_over_200)}")
        logger.info(f"{'='*80}\n")
        
        for idx, item in enumerate(items_over_200, 1):
            logger.info(f"Предмет #{idx}:")
            logger.info(f"   listing_id: {item['listing_id']}")
            logger.info(f"   цена: ${item['price']:.2f}" if item['price'] else "   цена: N/A")
            logger.info(f"   наклейки: {item['stickers']}")
            logger.info(f"   общая цена наклеек: ${item['total_stickers_price']:.2f}")
            logger.info("")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await parser.close() if 'parser' in locals() else None
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(find_items_over_200())

