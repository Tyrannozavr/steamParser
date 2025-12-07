"""
Скрипт для отладки парсера - сохраняет HTML страницы для анализа.
"""
import asyncio
from steam_parser import SteamMarketParser
from parsers import ItemPageParser


async def debug_parsing():
    """Сохраняет HTML страницу для анализа."""
    item_name = "AK-47 | Redline"
    
    async with SteamMarketParser() as parser:
        # Ищем предмет
        from models import SearchFilters
        filters = SearchFilters(item_name=item_name)
        result = await parser.search_items(filters, start=0, count=1)
        
        if not result['success'] or not result.get('items'):
            print("❌ Предметы не найдены")
            return
        
        first_item = result['items'][0]
        hash_name = first_item.get('asset_description', {}).get('market_hash_name')
        
        if not hash_name:
            print("❌ Не удалось получить hash_name")
            return
        
        print(f"📦 Загружаю страницу: {hash_name}")
        
        # Загружаем HTML
        html = await parser._fetch_item_page(730, hash_name)
        
        if html:
            # Сохраняем HTML для анализа
            with open('debug_page.html', 'w', encoding='utf-8') as f:
                f.write(html)
            print("✅ HTML сохранен в debug_page.html")
            
            # Парсим (без получения цен наклеек для быстрого дебага)
            parser_obj = ItemPageParser(html)
            parsed = await parser_obj.parse_all(fetch_sticker_prices=False)
            
            print(f"\n📊 Результаты парсинга:")
            print(f"  Float: {parsed.get('float_value')}")
            print(f"  Паттерн: {parsed.get('pattern')}")
            print(f"  Наклеек: {len(parsed.get('stickers', []))}")
            
            # Ищем упоминания float и pattern в HTML
            print(f"\n🔍 Поиск упоминаний в HTML:")
            float_matches = html.lower().count('wear') + html.lower().count('float')
            pattern_matches = html.lower().count('paintseed') + html.lower().count('pattern')
            print(f"  Упоминаний 'wear'/'float': {float_matches}")
            print(f"  Упоминаний 'paintseed'/'pattern': {pattern_matches}")
            
            # Ищем в JavaScript
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')
            scripts = soup.find_all('script')
            print(f"\n📜 Найдено <script> тегов: {len(scripts)}")
            
            for i, script in enumerate(scripts[:3], 1):  # Первые 3 скрипта
                if script.string:
                    text = script.string[:500]  # Первые 500 символов
                    if 'wear' in text.lower() or 'float' in text.lower():
                        print(f"\n  Скрипт {i} содержит 'wear'/'float':")
                        print(f"  {text[:200]}...")
                    if 'paintseed' in text.lower() or 'pattern' in text.lower():
                        print(f"\n  Скрипт {i} содержит 'paintseed'/'pattern':")
                        print(f"  {text[:200]}...")
        else:
            print("❌ Не удалось загрузить HTML")


if __name__ == "__main__":
    asyncio.run(debug_parsing())

