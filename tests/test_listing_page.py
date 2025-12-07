#!/usr/bin/env python3
"""
Тестовый скрипт для проверки парсинга конкретного лота.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from parsers.item_page_parser import ItemPageParser
from core.steam_parser import SteamMarketParser
from core.config import Config
from services.redis_service import RedisService
from loguru import logger

async def test_listing_page():
    """Тестируем парсинг страницы с конкретным listing_id."""
    
    # Настройка логирования
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    # Инициализация сервисов
    # RedisService создается из REDIS_URL
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(Config.REDIS_URL)
    
    # Создаем парсер (без proxy_manager для упрощения)
    parser = SteamMarketParser(
        redis_service=redis_service
    )
    
    # Параметры для теста
    appid = 730
    hash_name = "AK-47 | Redline (Battle-Scarred)"
    target_listing_id = "733651971153157038"
    
    logger.info(f"🔍 Тестируем парсинг страницы для: {hash_name}")
    logger.info(f"🎯 Ищем listing_id: {target_listing_id}")
    
    # Парсим все страницы пагинации
    logger.info("📄 Парсим все страницы пагинации...")
    
    # Получаем первую страницу
    html = await parser._fetch_item_page(appid, hash_name, page=1)
    if not html:
        logger.error("❌ Не удалось загрузить первую страницу")
        return
    
    page_parser = ItemPageParser(html)
    all_listings = page_parser.get_all_listings()
    logger.info(f"📋 Страница 1: Найдено {len(all_listings)} лотов")
    
    # Проверяем, есть ли наш listing_id на первой странице
    found_on_page = None
    for listing in all_listings:
        if listing.get('listing_id') == target_listing_id:
            found_on_page = 1
            logger.info(f"✅ Найден на странице 1!")
            logger.info(f"   Цена: ${listing.get('price', 'N/A'):.2f}")
            logger.info(f"   Inspect ссылка: {listing.get('inspect_link', 'N/A')}")
            logger.info(f"   Listing ID: {listing.get('listing_id', 'N/A')}")
            break
    
    # Если не нашли на первой странице, проверяем вторую
    if not found_on_page:
        logger.info("📄 Проверяем страницу 2...")
        await asyncio.sleep(1)
        html_page2 = await parser._fetch_item_page(appid, hash_name, page=2)
        if html_page2:
            page_parser2 = ItemPageParser(html_page2)
            all_listings_page2 = page_parser2.get_all_listings()
            logger.info(f"📋 Страница 2: Найдено {len(all_listings_page2)} лотов")
            
            for listing in all_listings_page2:
                if listing.get('listing_id') == target_listing_id:
                    found_on_page = 2
                    logger.info(f"✅ Найден на странице 2!")
                    logger.info(f"   Цена: ${listing.get('price', 'N/A'):.2f}")
                    logger.info(f"   Inspect ссылка: {listing.get('inspect_link', 'N/A')}")
                    logger.info(f"   Listing ID: {listing.get('listing_id', 'N/A')}")
                    break
    
    # Если не нашли, проверяем все страницы
    if not found_on_page:
        logger.info("📄 Проверяем все страницы...")
        total_count = page_parser.get_total_listings_count()
        logger.info(f"📊 Всего лотов: {total_count}")
        
        listings_per_page = 10
        if total_count:
            total_pages = (total_count + listings_per_page - 1) // listings_per_page
            logger.info(f"📊 Всего страниц: {total_pages}")
            max_pages = min(total_pages + 1, 20)
        else:
            # Если total_count неизвестен, проверяем до тех пор, пока не получим меньше 10 лотов
            logger.info("📊 Количество страниц неизвестно, проверяем до тех пор, пока не получим меньше 10 лотов")
            max_pages = 20
        
        # Проверяем больше страниц, так как лот с ценой $38.92 может быть дальше
        for page in range(2, max_pages):
            await asyncio.sleep(1)
            html_page = await parser._fetch_item_page(appid, hash_name, page=page)
            if html_page:
                page_parser_page = ItemPageParser(html_page)
                page_listings = page_parser_page.get_all_listings()
                logger.info(f"📋 Страница {page}: Найдено {len(page_listings)} лотов")
                
                # Если получили меньше 10 лотов и total_count неизвестен - это последняя страница
                if not total_count and len(page_listings) < 10:
                    logger.info(f"📋 Страница {page}: Получено меньше 10 лотов, это последняя страница")
                
                for listing in page_listings:
                    if listing.get('listing_id') == target_listing_id:
                        found_on_page = page
                        logger.info(f"✅ Найден на странице {page}!")
                        logger.info(f"   Цена: ${listing.get('price', 'N/A'):.2f}")
                        logger.info(f"   Inspect ссылка: {listing.get('inspect_link', 'N/A')}")
                        logger.info(f"   Listing ID: {listing.get('listing_id', 'N/A')}")
                        break
                
                if found_on_page:
                    break
                
                # Если получили меньше 10 лотов и total_count неизвестен - прекращаем проверку
                if not total_count and len(page_listings) < 10:
                    break
    
    if not found_on_page:
        logger.error(f"❌ Listing ID {target_listing_id} не найден на проверенных страницах")
        logger.info("🔍 Проверяем HTML второй страницы на наличие этого listing_id...")
        
        # Загружаем вторую страницу и проверяем HTML
        html_page2 = await parser._fetch_item_page(appid, hash_name, page=2)
        if html_page2:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_page2, 'html.parser')
            
            # Проверяем, есть ли listing_id в HTML как строка
            if target_listing_id in html_page2:
                logger.info(f"✅ Listing ID {target_listing_id} найден в HTML страницы 2 как строка!")
            else:
                logger.warning(f"⚠️ Listing ID {target_listing_id} не найден в HTML страницы 2 как строка")
            
            # Ищем элемент с этим listing_id в атрибуте id
            listing_row = soup.find('div', id=f'listing_{target_listing_id}')
            if listing_row:
                logger.info(f"✅ Найден элемент div#listing_{target_listing_id}")
                
                # Проверяем, есть ли цена
                price_elem = listing_row.select_one('.market_listing_price_with_fee')
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    logger.info(f"   Цена найдена: {price_text}")
                else:
                    logger.warning("   ⚠️ Цена не найдена в элементе")
                    # Пробуем другие селекторы
                    price_elems = listing_row.select('.market_listing_price, .normal_price')
                    for price_elem in price_elems:
                        price_text = price_elem.get_text(strip=True)
                        logger.info(f"   Цена (fallback): {price_text}")
                
                # Проверяем, есть ли inspect ссылка
                inspect_elem = listing_row.find('a', href=lambda x: x and 'csgo_econ_action_preview' in x)
                if inspect_elem:
                    inspect_link = inspect_elem.get('href')
                    logger.info(f"   Inspect ссылка найдена: {inspect_link}")
                else:
                    logger.warning("   ⚠️ Inspect ссылка не найдена в элементе")
                    # Пробуем найти в JavaScript
                    scripts = listing_row.find_all('script')
                    for script in scripts:
                        if script.string and 'csgo_econ_action_preview' in script.string:
                            logger.info(f"   Inspect ссылка найдена в script: {script.string[:200]}...")
            else:
                logger.warning(f"❌ Элемент div#listing_{target_listing_id} не найден в HTML")
                
                # Пробуем найти по классу
                listing_row = soup.find('div', class_=lambda x: x and f'listing_{target_listing_id}' in x)
                if listing_row:
                    logger.info(f"✅ Найден элемент с классом listing_{target_listing_id}")
                else:
                    logger.warning(f"❌ Элемент с классом listing_{target_listing_id} не найден")
                    
                    # Пробуем найти все элементы с listing_id в атрибутах
                    all_listing_rows = soup.find_all('div', class_='market_listing_row')
                    logger.info(f"🔍 Найдено {len(all_listing_rows)} элементов market_listing_row на странице 2")
                    for idx, row in enumerate(all_listing_rows[:5], 1):  # Проверяем первые 5
                        row_id = row.get('id', '')
                        row_classes = row.get('class', [])
                        logger.info(f"   Лот [{idx}]: id={row_id}, classes={row_classes}")
                        
                        # Проверяем цену
                        price_elem = row.select_one('.market_listing_price_with_fee')
                        if price_elem:
                            price_text = price_elem.get_text(strip=True)
                            logger.info(f"      Цена: {price_text}")
                        
                        # Проверяем inspect ссылку
                        inspect_elem = row.find('a', href=lambda x: x and 'csgo_econ_action_preview' in x)
                        if inspect_elem:
                            inspect_link = inspect_elem.get('href')
                            logger.info(f"      Inspect: {inspect_link[:100]}...")
                        else:
                            logger.warning(f"      Inspect ссылка не найдена")

if __name__ == "__main__":
    asyncio.run(test_listing_page())

