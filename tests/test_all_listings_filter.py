#!/usr/bin/env python3
"""
Проверяет все лоты на странице Steam Market через render API и применяет фильтр по наклейкам.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.utils.sticker_parser import StickerParser, StickerPriceResolver
from parsers.sticker_prices import StickerPricesAPI
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.config import Config
from core.database import DatabaseManager
from loguru import logger
import httpx
from bs4 import BeautifulSoup
import re
from urllib.parse import quote

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

MIN_STICKERS_PRICE = 200.0  # Фильтр: минимум $200


async def fetch_listings_page(appid: int, hash_name: str, start: int, count: int, proxy: str = None):
    """Получает страницу лотов через render API."""
    url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
    params = {
        'query': '',
        'start': start,
        'count': count,
        'country': 'BY',
        'language': 'english',
        'currency': 1
    }
    
    async with httpx.AsyncClient(proxy=proxy, timeout=30) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def extract_listings_from_render_data(data: dict):
    """Извлекает информацию о лотах из render API ответа."""
    listings = []
    
    if not data.get('success'):
        return listings
    
    listinginfo = data.get('listinginfo', {})
    assets_data = data.get('assets', {})
    
    # listinginfo может быть словарем или списком
    if isinstance(listinginfo, list):
        listinginfo = {item.get('listingid', ''): item for item in listinginfo if isinstance(item, dict)}
    
    # assets может быть словарем с ключом '730' или списком
    assets = {}
    if isinstance(assets_data, dict):
        assets = assets_data.get('730', {})
    elif isinstance(assets_data, list):
        # Если это список, преобразуем в словарь
        for asset_item in assets_data:
            if isinstance(asset_item, dict) and '730' in asset_item:
                assets.update(asset_item['730'])
    
    # Парсим HTML для получения цен
    results_html = data.get('results_html', '')
    soup = BeautifulSoup(results_html, 'html.parser')
    
    # Создаем словарь цен по listing_id
    price_map = {}
    for row in soup.find_all('div', class_='market_listing_row'):
        listing_id = row.get('id', '').replace('listing_', '')
        if listing_id:
            price_elem = row.find('span', class_='market_listing_price_without_fee')
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                if match:
                    try:
                        price_map[listing_id] = float(match.group())
                    except ValueError:
                        pass
    
    # Парсим HTML для получения наклеек
    for row in soup.find_all('div', class_='market_listing_row'):
        listing_id = row.get('id', '').replace('listing_', '')
        if not listing_id or listing_id not in listinginfo:
            continue
        
        listing_data = listinginfo[listing_id]
        
        # Извлекаем наклейки из HTML
        sticker_div = row.find('div', id='sticker_info') or row.find('div', class_='sticker_info')
        stickers = []
        if sticker_div:
            sticker_html = str(sticker_div)
            stickers = StickerParser.parse_stickers_from_html(sticker_html)
        
        # Если наклейки не найдены в HTML, пробуем из assets
        if not stickers:
            asset_id = listing_data.get('asset', {}).get('id', '')
            contextid = listing_data.get('asset', {}).get('contextid', '2')
            
            # Ищем в assets по contextid и asset_id
            if contextid in assets:
                context_assets = assets[contextid]
                if asset_id and str(asset_id) in context_assets:
                    asset_data = context_assets[str(asset_id)]
                    if asset_data and 'descriptions' in asset_data:
                        for desc in asset_data['descriptions']:
                            if desc.get('name') == 'sticker_info':
                                sticker_html = desc.get('value', '')
                                if sticker_html:
                                    stickers = StickerParser.parse_stickers_from_html(sticker_html)
                                    break
        
        # Получаем цену
        price = price_map.get(listing_id)
        
        listings.append({
            'listing_id': listing_id,
            'price': price,
            'stickers': stickers
        })
    
    return listings


async def check_all_listings():
    """Проверяет все лоты на странице."""
    appid = 730
    hash_name = "AK-47 | Redline (Minimal Wear)"
    
    logger.info("="*80)
    logger.info("🔍 ПРОВЕРКА ВСЕХ ЛОТОВ НА СТРАНИЦЕ")
    logger.info("="*80)
    logger.info(f"   Предмет: {hash_name}")
    logger.info(f"   Фильтр: min_stickers_price = ${MIN_STICKERS_PRICE:.2f}")
    logger.info("")
    
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
        # Получаем первую страницу для определения total_count
        logger.info("📥 Загружаем первую страницу...")
        first_page = await fetch_listings_page(appid, hash_name, start=0, count=10, proxy=proxy_url)
        
        total_count = first_page.get('total_count', 0)
        logger.info(f"   Всего лотов: {total_count}")
        logger.info("")
        
        # Создаем resolver для цен
        resolver = StickerPriceResolver(
            sticker_prices_api=StickerPricesAPI,
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        
        all_results = []
        count_per_page = 10
        pages_to_fetch = (total_count + count_per_page - 1) // count_per_page
        
        # Обрабатываем все страницы
        for page in range(pages_to_fetch):
            start = page * count_per_page
            logger.info(f"📄 Страница {page + 1}/{pages_to_fetch} (start={start})...")
            
            if page == 0:
                # Используем данные первой страницы
                data = first_page
            else:
                data = await fetch_listings_page(appid, hash_name, start=start, count=count_per_page, proxy=proxy_url)
                await asyncio.sleep(0.3)  # Задержка между страницами
            
            listings = extract_listings_from_render_data(data)
            logger.info(f"   Найдено лотов на странице: {len(listings)}")
            
            # Обрабатываем каждый лот
            for listing in listings:
                listing_id = listing['listing_id']
                item_price = listing['price']
                stickers = listing['stickers']
                
                logger.info(f"   📦 Лот ID: {listing_id}")
                logger.info(f"      Цена предмета: ${item_price:.2f}" if item_price else "      Цена предмета: N/A")
                
                if not stickers:
                    logger.info(f"      Наклеек: нет")
                    all_results.append({
                        'listing_id': listing_id,
                        'item_price': item_price,
                        'stickers_count': 0,
                        'total_stickers_price': 0.0,
                        'passes_filter': False,
                        'reason': 'Нет наклеек'
                    })
                    logger.info(f"      ❌ НЕ ПРОХОДИТ (нет наклеек)")
                    continue
                
                logger.info(f"      Наклеек: {len(stickers)}")
                for sticker in stickers:
                    logger.info(f"         - {sticker.name}")
                
                # Получаем цены наклеек
                sticker_names = [s.name for s in stickers]
                prices = await resolver.get_stickers_prices(
                    sticker_names,
                    appid=730,
                    currency=1,
                    proxy=proxy_url,
                    delay=0.1,
                    use_fuzzy_matching=True
                )
                
                # Вычисляем общую цену
                total_stickers_price = 0.0
                sticker_details = []
                for sticker in stickers:
                    price = prices.get(sticker.name)
                    if price is not None:
                        total_stickers_price += price
                        sticker_details.append(f"{sticker.name}: ${price:.2f}")
                    else:
                        sticker_details.append(f"{sticker.name}: цена не найдена")
                
                passes_filter = total_stickers_price >= MIN_STICKERS_PRICE
                
                logger.info(f"      Общая цена наклеек: ${total_stickers_price:.2f}")
                for detail in sticker_details:
                    logger.info(f"         {detail}")
                
                if passes_filter:
                    logger.info(f"      ✅ ПРОХОДИТ ФИЛЬТР (${total_stickers_price:.2f} >= ${MIN_STICKERS_PRICE:.2f})")
                else:
                    logger.info(f"      ❌ НЕ ПРОХОДИТ (${total_stickers_price:.2f} < ${MIN_STICKERS_PRICE:.2f})")
                
                all_results.append({
                    'listing_id': listing_id,
                    'item_price': item_price,
                    'stickers_count': len(stickers),
                    'total_stickers_price': total_stickers_price,
                    'passes_filter': passes_filter,
                    'sticker_details': sticker_details
                })
                
                await asyncio.sleep(0.1)  # Небольшая задержка между лотами
            
            logger.info("")
        
        # Выводим итоговый список
        logger.info("="*80)
        logger.info("📊 ИТОГОВЫЙ СПИСОК")
        logger.info("="*80)
        
        passed_count = sum(1 for r in all_results if r['passes_filter'])
        logger.info(f"Всего лотов: {len(all_results)}")
        logger.info(f"Прошли фильтр: {passed_count}")
        logger.info(f"Не прошли фильтр: {len(all_results) - passed_count}")
        logger.info("")
        
        logger.info("✅ ЛОТЫ, КОТОРЫЕ ПРОШЛИ ФИЛЬТР:")
        logger.info("-" * 80)
        for result in all_results:
            if result['passes_filter']:
                logger.info(f"  ✅ Лот ID: {result['listing_id']}")
                logger.info(f"     Цена предмета: ${result['item_price']:.2f}" if result['item_price'] else "     Цена предмета: N/A")
                logger.info(f"     Наклеек: {result['stickers_count']}")
                logger.info(f"     Общая цена наклеек: ${result['total_stickers_price']:.2f}")
                for detail in result.get('sticker_details', []):
                    logger.info(f"        {detail}")
                logger.info("")
        
        logger.info("❌ ЛОТЫ, КОТОРЫЕ НЕ ПРОШЛИ ФИЛЬТР:")
        logger.info("-" * 80)
        for result in all_results:
            if not result['passes_filter']:
                reason = result.get('reason', f"${result['total_stickers_price']:.2f} < ${MIN_STICKERS_PRICE:.2f}")
                logger.info(f"  ❌ Лот ID: {result['listing_id']} - {reason}")
                if result['stickers_count'] > 0:
                    logger.info(f"     Наклеек: {result['stickers_count']}, общая цена: ${result['total_stickers_price']:.2f}")
        
        logger.info("="*80)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(check_all_listings())
