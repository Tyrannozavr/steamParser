#!/usr/bin/env python3
"""
Тестовый скрипт для получения цен наклеек со страницы Steam Market.
Парсит все наклейки с страницы и получает их цены через API.
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
from collections import defaultdict

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_sticker_prices():
    """Тестирует получение цен наклеек со страницы Steam Market."""
    
    hash_name = "AK-47 | Redline (Minimal Wear)"
    appid = 730
    
    logger.info(f"🔍 Тестируем получение цен наклеек для: {hash_name}")
    logger.info(f"📄 Страница: https://steamcommunity.com/market/listings/{appid}/{hash_name.replace(' ', '%20')}")
    
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
    
    logger.info(f"🌐 Используем прокси: {'ID=' + str(proxy_obj.id) if proxy_obj else 'нет'}")
    
    try:
        # Создаем парсер
        parser = SteamMarketParser(proxy=proxy_url, timeout=30, redis_service=redis_service, proxy_manager=proxy_manager)
        await parser._ensure_client()
        
        # Получаем первую страницу через render API
        logger.info(f"📥 Получаем данные через render API...")
        render_data = await parser._fetch_render_api(appid, hash_name, start=0, count=100)
        
        if not render_data:
            logger.error("❌ Не удалось получить данные через render API")
            return
        
        total_count = render_data.get('total_count', 0)
        logger.info(f"📊 Всего лотов на рынке: {total_count}")
        
        # Парсим наклейки из всех лотов
        all_stickers = {}  # {название_наклейки: {count: количество, prices: [список цен], listings: [список listing_id]}}
        
        # Обрабатываем первую страницу
        if 'assets' in render_data and '730' in render_data['assets']:
            app_assets = render_data['assets']['730']
            listinginfo = render_data.get('listinginfo', {})
            
            for contextid, items in app_assets.items():
                for itemid, item in items.items():
                    # Ищем listing_id для этого asset
                    listing_id = None
                    for lid, listing_data in listinginfo.items():
                        if 'asset' in listing_data:
                            asset_info = listing_data['asset']
                            if str(asset_info.get('id')) == str(itemid):
                                listing_id = lid
                                break
                    
                    # Парсим наклейки из descriptions
                    if 'descriptions' in item:
                        for desc in item['descriptions']:
                            if desc.get('name') == 'sticker_info':
                                sticker_html = desc.get('value', '')
                                if sticker_html:
                                    from bs4 import BeautifulSoup
                                    from core import StickerInfo
                                    sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                    images = sticker_soup.find_all('img')
                                    
                                    for idx, img in enumerate(images):
                                        if idx >= 5:
                                            break
                                        title = img.get('title', '')
                                        if title and 'Sticker:' in title:
                                            sticker_name = title.replace('Sticker: ', '').strip()
                                            if sticker_name and len(sticker_name) > 3:
                                                if sticker_name not in all_stickers:
                                                    all_stickers[sticker_name] = {
                                                        'count': 0,
                                                        'listings': [],
                                                        'prices': []
                                                    }
                                                all_stickers[sticker_name]['count'] += 1
                                                if listing_id:
                                                    all_stickers[sticker_name]['listings'].append(listing_id)
        
        # Получаем еще страницы, если нужно (максимум 5 страниц для теста)
        max_pages = min(5, (total_count + 19) // 20)
        logger.info(f"📄 Парсим {max_pages} страниц...")
        
        for page in range(1, max_pages):
            start = page * 20
            logger.info(f"📄 Страница {page + 1}/{max_pages} (start={start})...")
            
            render_data = await parser._fetch_render_api(appid, hash_name, start=start, count=20)
            if not render_data or 'assets' not in render_data:
                break
            
            if '730' in render_data['assets']:
                app_assets = render_data['assets']['730']
                listinginfo = render_data.get('listinginfo', {})
                
                for contextid, items in app_assets.items():
                    for itemid, item in items.items():
                        listing_id = None
                        for lid, listing_data in listinginfo.items():
                            if 'asset' in listing_data:
                                asset_info = listing_data['asset']
                                if str(asset_info.get('id')) == str(itemid):
                                    listing_id = lid
                                    break
                        
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
                                                    if sticker_name not in all_stickers:
                                                        all_stickers[sticker_name] = {
                                                            'count': 0,
                                                            'listings': [],
                                                            'prices': []
                                                        }
                                                    all_stickers[sticker_name]['count'] += 1
                                                    if listing_id:
                                                        all_stickers[sticker_name]['listings'].append(listing_id)
            
            await asyncio.sleep(0.5)  # Задержка между страницами
        
        logger.info(f"\n📊 Найдено уникальных наклеек: {len(all_stickers)}")
        logger.info(f"📋 Общее количество наклеек на всех предметах: {sum(s['count'] for s in all_stickers.values())}")
        
        # Получаем цены для всех наклеек
        logger.info(f"\n💰 Получаем цены для всех наклеек через API...")
        sticker_names = list(all_stickers.keys())
        
        prices = await StickerPricesAPI.get_stickers_prices_batch(
            sticker_names,
            appid=appid,
            currency=1,
            proxy=proxy_url,
            delay=0.5,
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        
        # Выводим результаты
        logger.info(f"\n{'='*80}")
        logger.info(f"📋 РЕЗУЛЬТАТЫ: Цены наклеек со страницы")
        logger.info(f"{'='*80}\n")
        
        # Сортируем по цене (от большей к меньшей)
        sorted_stickers = sorted(
            all_stickers.items(),
            key=lambda x: prices.get(x[0], 0) or 0,
            reverse=True
        )
        
        total_price_all = 0.0
        found_prices = 0
        no_prices = 0
        
        for sticker_name, data in sorted_stickers:
            price = prices.get(sticker_name)
            count = data['count']
            
            if price is not None and price > 0:
                total_price_all += price * count
                found_prices += 1
                logger.info(f"✅ {sticker_name}")
                logger.info(f"   💰 Цена: ${price:.2f}")
                logger.info(f"   📊 Встречается: {count} раз(а)")
                logger.info(f"   💵 Общая стоимость всех экземпляров: ${price * count:.2f}")
            else:
                no_prices += 1
                logger.warning(f"❌ {sticker_name}")
                logger.warning(f"   ⚠️ Цена не получена")
                logger.warning(f"   📊 Встречается: {count} раз(а)")
                logger.warning(f"   📋 Listing IDs: {data['listings'][:5]}{'...' if len(data['listings']) > 5 else ''}")
            
            logger.info("")
        
        logger.info(f"{'='*80}")
        logger.info(f"📊 СТАТИСТИКА:")
        logger.info(f"   ✅ Найдено цен: {found_prices} из {len(all_stickers)}")
        logger.info(f"   ❌ Не найдено цен: {no_prices} из {len(all_stickers)}")
        logger.info(f"   💰 Общая стоимость всех наклеек: ${total_price_all:.2f}")
        logger.info(f"{'='*80}")
        
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
    asyncio.run(test_sticker_prices())

