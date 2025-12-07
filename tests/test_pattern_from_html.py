#!/usr/bin/env python3
"""
Тестовый скрипт для проверки извлечения паттерна напрямую из HTML страницы Steam Market.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from core.steam_parser import SteamMarketParser
from parsers.pattern_parser import PatternParser
from core.config import Config
from services.redis_service import RedisService
from bs4 import BeautifulSoup
from loguru import logger

async def test_pattern_from_html():
    """Тестируем извлечение паттерна напрямую из HTML страницы Steam Market."""
    
    # Настройка логирования
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    # Инициализация сервисов
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(Config.REDIS_URL)
    
    # Создаем парсер
    parser = SteamMarketParser(redis_service=redis_service)
    
    # URL для теста
    url = "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Battle-Scarred)"
    appid = 730
    hash_name = "AK-47 | Redline (Battle-Scarred)"
    
    logger.info(f"🔍 Тестируем извлечение паттерна из HTML страницы")
    logger.info(f"📄 URL: {url}")
    
    async with parser:
        # Загружаем страницу
        logger.info("📡 Загружаем страницу...")
        html = await parser._fetch_item_page(appid, hash_name, page=1)
        
        if not html:
            logger.error("❌ Не удалось загрузить страницу")
            return
        
        logger.info(f"✅ Страница загружена ({len(html)} символов)")
        
        # Парсим HTML
        soup = BeautifulSoup(html, 'html.parser')
        
        # Проверяем, есть ли паттерн в HTML
        logger.info("\n" + "="*60)
        logger.info("🔍 Проверяем наличие паттерна в HTML...")
        logger.info("="*60)
        
        # 1. Проверяем через PatternParser
        logger.info("\n1️⃣ Используем PatternParser.parse()...")
        pattern = PatternParser.parse(html, soup)
        if pattern is not None:
            logger.info(f"   ✅ Паттерн найден через PatternParser: {pattern}")
        else:
            logger.warning("   ❌ Паттерн не найден через PatternParser")
        
        # 2. Проверяем в JavaScript коде напрямую
        logger.info("\n2️⃣ Проверяем JavaScript код...")
        scripts = soup.find_all('script')
        logger.info(f"   Найдено {len(scripts)} script тегов")
        
        pattern_found_in_js = False
        for idx, script in enumerate(scripts, 1):
            if script.string:
                script_text = script.string
                
                # Ищем различные варианты паттерна
                patterns_to_check = [
                    (r'["\']paintseed["\']\s*:\s*([0-9]+)', 'paintseed'),
                    (r'["\']pattern["\']\s*:\s*([0-9]+)', 'pattern'),
                    (r'["\']patternindex["\']\s*:\s*([0-9]+)', 'patternindex'),
                    (r'g_rgListingInfo\s*=\s*(\{.*?\});', 'g_rgListingInfo'),
                    (r'g_rgItemInfo\s*=\s*(\{.*?\});', 'g_rgItemInfo'),
                    (r'Pattern:\s*#?([0-9]+)', 'Pattern text'),
                ]
                
                for pattern_regex, pattern_name in patterns_to_check:
                    import re
                    match = re.search(pattern_regex, script_text, re.IGNORECASE | re.DOTALL)
                    if match:
                        logger.info(f"   ✅ Script [{idx}]: Найден {pattern_name}: {match.group(1)}")
                        pattern_found_in_js = True
                        # Показываем контекст
                        start = max(0, match.start() - 100)
                        end = min(len(script_text), match.end() + 100)
                        context = script_text[start:end].replace('\n', ' ').replace('\r', ' ')
                        logger.debug(f"      Контекст: ...{context}...")
        
        if not pattern_found_in_js:
            logger.warning("   ❌ Паттерн не найден в JavaScript коде")
        
        # 3. Проверяем data-атрибуты
        logger.info("\n3️⃣ Проверяем data-атрибуты элементов...")
        data_attrs = ['data-pattern', 'data-paintseed', 'data-pattern-index']
        pattern_found_in_attrs = False
        for attr_name in data_attrs:
            elements = soup.find_all(attrs={attr_name: True})
            if elements:
                logger.info(f"   ✅ Найдено {len(elements)} элементов с атрибутом {attr_name}")
                for elem in elements[:3]:  # Показываем первые 3
                    attr_value = elem.get(attr_name)
                    logger.info(f"      {attr_name}={attr_value}")
                    pattern_found_in_attrs = True
            else:
                logger.debug(f"   ❌ Элементы с атрибутом {attr_name} не найдены")
        
        if not pattern_found_in_attrs:
            logger.warning("   ❌ Паттерн не найден в data-атрибутах")
        
        # 4. Проверяем элементы расширения браузера
        logger.info("\n4️⃣ Проверяем элементы расширения браузера...")
        cs2_pattern = soup.find('div', class_='cs2-pattern-copyable')
        if cs2_pattern:
            text = cs2_pattern.get_text()
            logger.info(f"   ✅ Найден элемент cs2-pattern-copyable: {text}")
        else:
            logger.debug("   ❌ Элемент cs2-pattern-copyable не найден")
        
        # 5. Проверяем текст страницы
        logger.info("\n5️⃣ Проверяем текст страницы на наличие 'Pattern'...")
        page_text = soup.get_text()
        pattern_matches = []
        import re
        for match in re.finditer(r'Pattern[:\s]*#?([0-9]+)', page_text, re.IGNORECASE):
            pattern_matches.append(match.group(1))
        
        if pattern_matches:
            logger.info(f"   ✅ Найдено {len(pattern_matches)} упоминаний паттерна в тексте: {pattern_matches[:5]}")
        else:
            logger.debug("   ❌ Упоминания паттерна в тексте не найдены")
        
        # 6. Проверяем g_rgAssets и другие структуры данных
        logger.info("\n6️⃣ Проверяем g_rgAssets и другие структуры данных...")
        for script in scripts:
            if script.string:
                # Проверяем g_rgAssets
                if 'g_rgAssets' in script.string:
                    logger.info("   ✅ Найден g_rgAssets")
                    try:
                        import json
                        match = re.search(r'var g_rgAssets\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                        if match:
                            assets_data = json.loads(match.group(1))
                            logger.info(f"   📦 g_rgAssets распарсен, проверяем на наличие паттерна...")
                            pattern_in_assets = PatternParser._find_pattern_in_dict(assets_data)
                            if pattern_in_assets:
                                logger.info(f"      ✅ Паттерн найден в g_rgAssets: {pattern_in_assets}")
                            else:
                                logger.debug("      ❌ Паттерн не найден в g_rgAssets")
                    except Exception as e:
                        logger.debug(f"      ⚠️ Ошибка при парсинге g_rgAssets: {e}")
                
                # Проверяем g_rgListingInfo на наличие паттерна в asset данных
                if 'g_rgListingInfo' in script.string:
                    logger.info("   ✅ Найден g_rgListingInfo, проверяем asset данные...")
                    try:
                        import json
                        match = re.search(r'var g_rgListingInfo\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                        if match:
                            listing_info = json.loads(match.group(1))
                            logger.info(f"   📦 g_rgListingInfo распарсен, проверяем {len(listing_info)} лотов...")
                            patterns_found = []
                            for listing_id, listing_data in list(listing_info.items())[:5]:
                                if isinstance(listing_data, dict) and 'asset' in listing_data:
                                    asset = listing_data['asset']
                                    pattern_in_asset = PatternParser._find_pattern_in_dict(asset)
                                    if pattern_in_asset:
                                        patterns_found.append((listing_id, pattern_in_asset))
                                        logger.info(f"      ✅ Лот {listing_id}: паттерн {pattern_in_asset}")
                            if not patterns_found:
                                logger.debug("      ❌ Паттерн не найден в asset данных g_rgListingInfo")
                    except Exception as e:
                        logger.debug(f"      ⚠️ Ошибка при парсинге g_rgListingInfo: {e}")
        
        # 7. Проверяем listing rows на наличие паттерна
        logger.info("\n7️⃣ Проверяем listing rows на наличие паттерна...")
        listing_rows = soup.find_all('div', class_='market_listing_row')
        logger.info(f"   Найдено {len(listing_rows)} listing rows")
        
        for idx, row in enumerate(listing_rows[:5], 1):  # Проверяем первые 5
            row_id = row.get('id', '')
            logger.info(f"\n   Лот [{idx}]: id={row_id}")
            
            # Проверяем data-атрибуты
            for attr in data_attrs:
                attr_value = row.get(attr)
                if attr_value:
                    logger.info(f"      ✅ {attr}={attr_value}")
            
            # Проверяем JavaScript в row
            scripts_in_row = row.find_all('script')
            for script in scripts_in_row:
                if script.string:
                    for pattern_regex, pattern_name in patterns_to_check[:3]:
                        match = re.search(pattern_regex, script.string, re.IGNORECASE)
                        if match:
                            logger.info(f"      ✅ В script найден {pattern_name}: {match.group(1)}")
        
        # Итоговый вывод
        logger.info("\n" + "="*60)
        logger.info("📊 ИТОГОВЫЙ РЕЗУЛЬТАТ:")
        logger.info("="*60)
        if pattern is not None:
            logger.info(f"✅ Паттерн успешно извлечен из HTML: {pattern}")
            logger.info("✅ Извлечение паттерна из HTML РЕАЛИЗОВАНО")
        else:
            logger.warning("❌ Паттерн не удалось извлечь из HTML")
            logger.warning("⚠️ Требуется использование дополнительных API запросов")

if __name__ == "__main__":
    asyncio.run(test_pattern_from_html())

