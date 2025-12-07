#!/usr/bin/env python3
"""
Тестовый скрипт для проверки извлечения названий наклеек из конкретного предмета.
Проверяет, как парсятся наклейки из render API и как получаются их цены.
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


async def test_sticker_extraction():
    """Тестирует извлечение наклеек из конкретного предмета."""
    
    hash_name = "AK-47 | Redline (Minimal Wear)"
    appid = 730
    
    logger.info(f"🔍 Тестируем извлечение наклеек для: {hash_name}")
    
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
        
        # Получаем первую страницу
        logger.info(f"📥 Получаем данные через render API...")
        render_data = await parser._fetch_render_api(appid, hash_name, start=0, count=20)
        
        if not render_data:
            logger.error("❌ Не удалось получить данные")
            return
        
        logger.info(f"📊 Всего лотов: {render_data.get('total_count', 0)}")
        
        # Парсим наклейки из каждого лота
        if 'assets' in render_data and '730' in render_data['assets']:
            app_assets = render_data['assets']['730']
            listinginfo = render_data.get('listinginfo', {})
            
            logger.info(f"\n{'='*80}")
            logger.info(f"📋 ДЕТАЛЬНЫЙ АНАЛИЗ НАКЛЕЕК ИЗ ЛОТОВ:")
            logger.info(f"{'='*80}\n")
            
            lot_number = 0
            for contextid, items in app_assets.items():
                for itemid, item in items.items():
                    # Ищем listing_id
                    listing_id = None
                    listing_price = None
                    for lid, listing_data in listinginfo.items():
                        if 'asset' in listing_data:
                            asset_info = listing_data['asset']
                            if str(asset_info.get('id')) == str(itemid):
                                listing_id = lid
                                # Получаем цену лота
                                if 'sell_price' in listing_data:
                                    listing_price = listing_data['sell_price'] / 100.0
                                break
                    
                    lot_number += 1
                    price_str = f"${listing_price:.2f}" if listing_price else "N/A"
                    logger.info(f"📦 ЛОТ #{lot_number} (listing_id={listing_id}, price={price_str})")
                    
                    # Парсим наклейки
                    stickers_found = []
                    if 'descriptions' in item:
                        for desc in item['descriptions']:
                            if desc.get('name') == 'sticker_info':
                                sticker_html = desc.get('value', '')
                                if sticker_html:
                                    from bs4 import BeautifulSoup
                                    from core import StickerInfo
                                    sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                    images = sticker_soup.find_all('img')
                                    
                                    logger.info(f"   🖼️ Найдено {len(images)} изображений наклеек")
                                    
                                    for idx, img in enumerate(images):
                                        if idx >= 5:
                                            break
                                        title = img.get('title', '')
                                        logger.info(f"      Изображение {idx}: title='{title}'")
                                        
                                        if title and 'Sticker:' in title:
                                            sticker_name = title.replace('Sticker: ', '').strip()
                                            if sticker_name and len(sticker_name) > 3:
                                                stickers_found.append(sticker_name)
                                                logger.info(f"      ✅ Найдена наклейка: '{sticker_name}' (позиция {idx})")
                                            else:
                                                logger.warning(f"      ⚠️ Название наклейки слишком короткое: '{sticker_name}'")
                                        else:
                                            logger.warning(f"      ⚠️ Нет 'Sticker:' в title: '{title}'")
                    
                    if stickers_found:
                        logger.info(f"   📋 Всего наклеек найдено: {len(stickers_found)}")
                        logger.info(f"   📝 Названия: {stickers_found}")
                        
                        # Получаем цены для этих наклеек
                        logger.info(f"   💰 Получаем цены для наклеек...")
                        prices = await StickerPricesAPI.get_stickers_prices_batch(
                            stickers_found,
                            appid=appid,
                            currency=1,
                            proxy=proxy_url,
                            delay=0.3,
                            redis_service=redis_service,
                            proxy_manager=proxy_manager
                        )
                        
                        total_price = 0.0
                        logger.info(f"   📊 Результаты получения цен:")
                        for sticker_name in stickers_found:
                            price = prices.get(sticker_name)
                            if price is not None and price > 0:
                                total_price += price
                                logger.info(f"      ✅ {sticker_name}: ${price:.2f}")
                            else:
                                logger.warning(f"      ❌ {sticker_name}: цена не получена (price={price})")
                        
                        logger.info(f"   💵 Общая цена наклеек: ${total_price:.2f}")
                        logger.info(f"   🔍 Фильтр: min_stickers_price = $200.00")
                        if total_price >= 200.0:
                            logger.info(f"   ✅ ПРОХОДИТ фильтр (${total_price:.2f} >= $200.00)")
                        else:
                            logger.info(f"   ❌ НЕ ПРОХОДИТ фильтр (${total_price:.2f} < $200.00)")
                    else:
                        logger.warning(f"   ⚠️ Наклейки не найдены в этом лоте")
                    
                    logger.info("")
                    
                    # Ограничиваем количество лотов для теста
                    if lot_number >= 10:
                        logger.info(f"   ... (показываем только первые 10 лотов)")
                        break
        
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
    asyncio.run(test_sticker_extraction())

