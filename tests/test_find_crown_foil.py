#!/usr/bin/env python3
"""
Тестовый скрипт для поиска лота с Crown (Foil) и проверки его обработки.
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
from loguru import logger
import json

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def find_crown_foil_lot():
    """Ищет лот с Crown (Foil) и проверяет его обработку."""
    
    hash_name = "AK-47 | Redline (Minimal Wear)"
    appid = 730
    
    logger.info(f"🔍 Ищем лот с Crown (Foil) для: {hash_name}")
    
    # Инициализируем компоненты
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    
    # Получаем прокси
    proxy_obj = await proxy_manager.get_next_proxy(force_refresh=False)
    proxy_url = proxy_obj.url if proxy_obj else None
    
    try:
        # Создаем парсер
        parser = SteamMarketParser(proxy=proxy_url, timeout=30, redis_service=redis_service, proxy_manager=proxy_manager)
        await parser._ensure_client()
        
        # Получаем все страницы и ищем Crown (Foil)
        total_count = 0
        crown_foil_lots = []
        
        for page in range(5):  # Проверяем первые 5 страниц
            start = page * 20
            logger.info(f"📄 Страница {page + 1} (start={start})...")
            
            render_data = await parser._fetch_render_api(appid, hash_name, start=start, count=20)
            if not render_data:
                break
            
            if page == 0:
                total_count = render_data.get('total_count', 0)
                logger.info(f"📊 Всего лотов: {total_count}")
            
            if 'assets' in render_data and '730' in render_data['assets']:
                app_assets = render_data['assets']['730']
                listinginfo = render_data.get('listinginfo', {})
                
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
                                        from bs4 import BeautifulSoup
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
                                        
                                        # Проверяем, есть ли Crown (Foil)
                                        if any('Crown (Foil)' in s for s in stickers_found):
                                            crown_foil_lots.append({
                                                'listing_id': listing_id,
                                                'price': listing_price,
                                                'stickers': stickers_found,
                                                'itemid': itemid
                                            })
                                            logger.info(f"🎯 НАЙДЕН ЛОТ С CROWN (FOIL)!")
                                            logger.info(f"   listing_id: {listing_id}")
                                            logger.info(f"   price: ${listing_price:.2f}" if listing_price else "   price: N/A")
                                            logger.info(f"   наклейки: {stickers_found}")
            
            await asyncio.sleep(0.5)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 Найдено лотов с Crown (Foil): {len(crown_foil_lots)}")
        logger.info(f"{'='*80}\n")
        
        # Детально проверяем каждый найденный лот
        for idx, lot in enumerate(crown_foil_lots, 1):
            logger.info(f"🔍 ЛОТ #{idx} С CROWN (FOIL):")
            logger.info(f"   listing_id: {lot['listing_id']}")
            logger.info(f"   price: ${lot['price']:.2f}" if lot['price'] else "   price: N/A")
            logger.info(f"   наклейки: {lot['stickers']}")
            
            # Получаем цены для наклеек
            unique_stickers = list(dict.fromkeys(lot['stickers']))  # Убираем дубликаты
            logger.info(f"   💰 Получаем цены для {len(unique_stickers)} уникальных наклеек...")
            
            prices = await StickerPricesAPI.get_stickers_prices_batch(
                unique_stickers,
                appid=appid,
                currency=1,
                proxy=proxy_url,
                delay=0.3,
                redis_service=redis_service,
                proxy_manager=proxy_manager
            )
            
            total_price = 0.0
            logger.info(f"   📊 Результаты получения цен:")
            for sticker_name in lot['stickers']:
                price = prices.get(sticker_name)
                if price is not None and price > 0:
                    total_price += price
                    logger.info(f"      ✅ {sticker_name}: ${price:.2f}")
                else:
                    logger.warning(f"      ❌ {sticker_name}: цена не получена (price={price})")
            
            logger.info(f"   💵 Общая цена наклеек: ${total_price:.2f}")
            logger.info(f"   🔍 Фильтр: min_stickers_price = $200.00")
            
            if total_price >= 200.0:
                logger.info(f"   ✅✅✅ ПРОХОДИТ ФИЛЬТР! (${total_price:.2f} >= $200.00)")
            else:
                logger.warning(f"   ❌ НЕ ПРОХОДИТ фильтр (${total_price:.2f} < $200.00)")
            
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
    asyncio.run(find_crown_foil_lot())

