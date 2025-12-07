#!/usr/bin/env python3
"""
Детальная проверка ВСЕХ лотов на странице для поиска предметов с наклейками > $200.
Показывает каждый лот с его наклейками и ценами.
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
from collections import defaultdict

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def check_all_lots_manually():
    """Проверяет каждый лот на странице вручную."""
    
    hash_name = "AK-47 | Redline (Minimal Wear)"
    appid = 730
    
    logger.info(f"🔍 ДЕТАЛЬНАЯ ПРОВЕРКА ВСЕХ ЛОТОВ: {hash_name}")
    logger.info(f"📄 Страница: https://steamcommunity.com/market/listings/{appid}/{hash_name.replace(' ', '%20')}")
    
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
        
        all_lots = []
        items_over_200 = []
        
        # Парсим все страницы
        total_pages = 5
        for page in range(total_pages):
            start = page * 20
            logger.info(f"\n{'='*80}")
            logger.info(f"📄 СТРАНИЦА {page + 1}/{total_pages} (start={start})")
            logger.info(f"{'='*80}")
            
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
                
                # Создаем мапу listing_id -> price
                listing_prices = {}
                for listing in page_listings:
                    listing_id = listing.get('listing_id')
                    price = listing.get('price', 0.0)
                    if listing_id:
                        listing_prices[str(listing_id)] = price
                
                lot_number = 0
                for contextid, items in app_assets.items():
                    for itemid, item in items.items():
                        lot_number += 1
                        
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
                        
                        # Если не нашли через listinginfo, пробуем через HTML
                        if not listing_price and listing_id:
                            listing_price = listing_prices.get(str(listing_id))
                        
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
                        
                        # Получаем цены для наклеек
                        total_stickers_price = 0.0
                        if stickers_found:
                            unique_stickers = list(dict.fromkeys(stickers_found))
                            prices = await StickerPricesAPI.get_stickers_prices_batch(
                                unique_stickers,
                                appid=appid,
                                currency=1,
                                proxy=proxy_url,
                                delay=0.1,
                                redis_service=redis_service,
                                proxy_manager=proxy_manager
                            )
                            
                            # Вычисляем общую цену с гибким сопоставлением
                            for sticker_name in stickers_found:
                                # Точное совпадение
                                if sticker_name in prices and prices[sticker_name] is not None:
                                    total_stickers_price += prices[sticker_name]
                                else:
                                    # Гибкое сопоставление
                                    valid_prices = {k: v for k, v in prices.items() if v is not None}
                                    if valid_prices:
                                        match_result = find_best_match(sticker_name, valid_prices, min_similarity=0.5)
                                        if match_result:
                                            matched_name, similarity = match_result
                                            total_stickers_price += valid_prices[matched_name]
                        
                        lot_info = {
                            'lot_number': lot_number + (page * 20),
                            'listing_id': listing_id,
                            'itemid': itemid,
                            'price': listing_price,
                            'stickers': stickers_found,
                            'total_stickers_price': total_stickers_price
                        }
                        all_lots.append(lot_info)
                        
                        # Логируем каждый лот
                        if stickers_found:
                            price_str = f"${listing_price:.2f}" if listing_price else "N/A"
                            logger.info(f"📦 Лот #{lot_info['lot_number']}: listing_id={listing_id}, price={price_str}")
                            logger.info(f"   Наклеек: {len(stickers_found)}, общая цена: ${total_stickers_price:.2f}")
                            if total_stickers_price >= 200.0:
                                logger.info(f"   🎯 ПРОХОДИТ ФИЛЬТР! (${total_stickers_price:.2f} >= $200.00)")
                                items_over_200.append(lot_info)
                            else:
                                logger.info(f"   ❌ Не проходит (${total_stickers_price:.2f} < $200.00)")
                        else:
                            logger.debug(f"📦 Лот #{lot_info['lot_number']}: listing_id={listing_id}, наклеек нет")
            
            await asyncio.sleep(0.5)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(f"{'='*80}")
        logger.info(f"   Всего лотов проверено: {len(all_lots)}")
        logger.info(f"   Лотов с наклейками: {len([l for l in all_lots if l['stickers']])}")
        logger.info(f"   🎯 Лотов с наклейками > $200: {len(items_over_200)}")
        logger.info(f"{'='*80}\n")
        
        if items_over_200:
            logger.info(f"🎯 НАЙДЕННЫЕ ПРЕДМЕТЫ С НАКЛЕЙКАМИ > $200:")
            logger.info(f"{'='*80}\n")
            for idx, item in enumerate(items_over_200, 1):
                logger.info(f"Предмет #{idx}:")
                logger.info(f"   Лот #: {item['lot_number']}")
                logger.info(f"   listing_id: {item['listing_id']}")
                logger.info(f"   itemid: {item['itemid']}")
                logger.info(f"   цена предмета: ${item['price']:.2f}" if item['price'] else "   цена предмета: N/A")
                logger.info(f"   наклейки: {item['stickers']}")
                logger.info(f"   общая цена наклеек: ${item['total_stickers_price']:.2f}")
                logger.info("")
        else:
            logger.warning(f"⚠️ НЕ НАЙДЕНО предметов с наклейками > $200!")
        
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
    asyncio.run(check_all_lots_manually())

