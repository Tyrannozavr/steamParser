#!/usr/bin/env python3
"""
Тестовый скрипт для проверки получения цен для ВСЕХ наклеек с конкретной страницы Steam Market.
Проверяет, что гибкое сопоставление работает для всех наклеек.
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
from core.utils.sticker_name_matcher import find_best_match, normalize_sticker_name
from loguru import logger
from collections import defaultdict

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_all_stickers_from_page():
    """Тестирует получение цен для всех наклеек с конкретной страницы."""
    
    hash_name = "AK-47 | Redline (Minimal Wear)"
    appid = 730
    
    logger.info(f"🔍 Тестируем получение цен для ВСЕХ наклеек: {hash_name}")
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
        
        # Собираем все наклейки со всех страниц
        all_stickers = defaultdict(int)  # {название: количество}
        total_lots = 0
        lots_with_stickers = 0
        
        # Парсим первые 5 страниц (100 лотов)
        for page in range(5):
            start = page * 20
            logger.info(f"📄 Страница {page + 1} (start={start})...")
            
            render_data = await parser._fetch_render_api(appid, hash_name, start=start, count=20)
            if not render_data:
                break
            
            if 'assets' in render_data and '730' in render_data['assets']:
                app_assets = render_data['assets']['730']
                
                for contextid, items in app_assets.items():
                    for itemid, item in items.items():
                        total_lots += 1
                        
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
                                                    all_stickers[sticker_name] += 1
                        
                        if stickers_found:
                            lots_with_stickers += 1
            
            await asyncio.sleep(0.5)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 СТАТИСТИКА:")
        logger.info(f"   Всего лотов проверено: {total_lots}")
        logger.info(f"   Лотов с наклейками: {lots_with_stickers}")
        logger.info(f"   Уникальных наклеек найдено: {len(all_stickers)}")
        logger.info(f"   Всего наклеек (с дубликатами): {sum(all_stickers.values())}")
        logger.info(f"{'='*80}\n")
        
        # Получаем цены для всех уникальных наклеек
        unique_stickers = list(all_stickers.keys())
        logger.info(f"💰 Запрашиваем цены для {len(unique_stickers)} уникальных наклеек...")
        
        prices = await StickerPricesAPI.get_stickers_prices_batch(
            unique_stickers,
            appid=appid,
            currency=1,
            proxy=proxy_url,
            delay=0.3,
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 РЕЗУЛЬТАТЫ ПОЛУЧЕНИЯ ЦЕН:")
        logger.info(f"{'='*80}\n")
        
        # Анализируем результаты
        found_prices = {}
        not_found_stickers = []
        matched_with_fuzzy = []
        
        for sticker_name in unique_stickers:
            # Проверяем точное совпадение
            if sticker_name in prices and prices[sticker_name] is not None:
                found_prices[sticker_name] = prices[sticker_name]
                logger.info(f"✅ {sticker_name}: ${prices[sticker_name]:.2f} (точное совпадение)")
            else:
                # Пробуем гибкое сопоставление
                valid_prices = {k: v for k, v in prices.items() if v is not None}
                if valid_prices:
                    match_result = find_best_match(sticker_name, valid_prices, min_similarity=0.5)
                    if match_result:
                        matched_name, similarity = match_result
                        matched_price = valid_prices[matched_name]
                        found_prices[sticker_name] = matched_price
                        matched_with_fuzzy.append((sticker_name, matched_name, similarity, matched_price))
                        similarity_pct = int(similarity * 100)
                        logger.info(f"✅ {sticker_name}: ${matched_price:.2f} (гибкое совпадение {similarity_pct}% -> '{matched_name}')")
                    else:
                        not_found_stickers.append(sticker_name)
                        logger.warning(f"❌ {sticker_name}: цена не найдена")
                else:
                    not_found_stickers.append(sticker_name)
                    logger.warning(f"❌ {sticker_name}: цена не найдена (нет доступных цен в API)")
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 ИТОГОВАЯ СТАТИСТИКА:")
        logger.info(f"{'='*80}")
        logger.info(f"   ✅ Найдено цен (точное совпадение): {len([s for s in unique_stickers if s in prices and prices[s] is not None])}")
        logger.info(f"   ✅ Найдено цен (гибкое сопоставление): {len(matched_with_fuzzy)}")
        logger.info(f"   ❌ Не найдено цен: {len(not_found_stickers)}")
        logger.info(f"   📊 Общий процент успеха: {len(found_prices) * 100 / len(unique_stickers):.1f}%")
        
        if matched_with_fuzzy:
            logger.info(f"\n   🔍 Примеры гибкого сопоставления:")
            for original, matched, similarity, price in matched_with_fuzzy[:5]:
                similarity_pct = int(similarity * 100)
                logger.info(f"      '{original}' -> '{matched}' ({similarity_pct}%, ${price:.2f})")
        
        if not_found_stickers:
            logger.warning(f"\n   ⚠️ Наклейки без цен ({len(not_found_stickers)}):")
            for sticker in not_found_stickers[:10]:
                logger.warning(f"      - {sticker}")
            if len(not_found_stickers) > 10:
                logger.warning(f"      ... и еще {len(not_found_stickers) - 10}")
        
        logger.info(f"{'='*80}\n")
        
        # Проверяем, что все наклейки получили цены
        if len(found_prices) == len(unique_stickers):
            logger.info(f"🎉 УСПЕХ! Все {len(unique_stickers)} наклеек получили цены!")
        else:
            logger.warning(f"⚠️ Проблема: {len(not_found_stickers)} наклеек не получили цены из {len(unique_stickers)} всего")
        
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
    asyncio.run(test_all_stickers_from_page())

