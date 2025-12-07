"""
Тест /render/ API с count=20 и проверка HTML страницы.
"""
import asyncio
import httpx
import json
from urllib.parse import quote
import re
from bs4 import BeautifulSoup

async def test_render_count_20(hash_name: str, appid: int = 730):
    """Тестирует /render/ API с count=20."""
    print("=" * 80)
    print(f"🧪 Тест /render/ API с count=20")
    print(f"   Предмет: {hash_name}")
    print("=" * 80)
    
    # Формируем URL с count=20
    base_url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
    params = {
        "query": "",
        "start": 0,
        "count": 20,  # ВАЖНО: count=20
        "country": "BY",
        "language": "english",
        "currency": 1
    }
    url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
    
    print(f"\n📡 URL запроса:")
    print(f"   {url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n⏳ Отправка запроса...")
            response = await client.get(url)
            print(f"✅ Получен ответ: status_code={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                success = data.get('success', False)
                total_count = data.get('total_count', None)
                results = data.get('results', [])
                results_html = data.get('results_html', '')
                results_html_len = len(results_html.strip()) if results_html else 0
                
                print(f"\n📊 Результаты:")
                print(f"   success: {success}")
                print(f"   total_count: {total_count}")
                print(f"   results: {len(results)} элементов")
                print(f"   results_html: {results_html_len} символов")
                
                # Сохраняем HTML для анализа
                if results_html:
                    with open(f'test_render_count20_{hash_name.replace(" ", "_").replace("|", "").replace("™", "")}.html', 'w', encoding='utf-8') as f:
                        f.write(results_html)
                    print(f"   💾 HTML сохранен в файл")
                
                return data
            else:
                print(f"\n❌ Ошибка: status_code={response.status_code}")
                return None
                
        except Exception as e:
            print(f"\n❌ Исключение: {e}")
            return None

async def test_steam_market_page(hash_name: str, appid: int = 730):
    """Тестирует прямую HTML страницу Steam Market."""
    print("\n" + "=" * 80)
    print(f"🧪 Тест прямой HTML страницы Steam Market")
    print(f"   Предмет: {hash_name}")
    print("=" * 80)
    
    # URL прямой страницы
    url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}"
    
    print(f"\n📡 URL запроса:")
    print(f"   {url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n⏳ Отправка запроса...")
            response = await client.get(url)
            print(f"✅ Получен ответ: status_code={response.status_code}")
            
            if response.status_code == 200:
                html = response.text
                
                # Сохраняем HTML
                filename = f'test_market_page_{hash_name.replace(" ", "_").replace("|", "").replace("™", "")}.html'
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"   💾 HTML сохранен в {filename}")
                
                # Парсим HTML
                soup = BeautifulSoup(html, 'html.parser')
                
                # Ищем количество лотов
                # Обычно это в элементе типа "Showing 1-10 of 123 listings"
                listing_count_elements = soup.find_all(string=re.compile(r'(\d+)\s+listings?', re.IGNORECASE))
                print(f"\n📊 Найдено элементов с 'listings': {len(listing_count_elements)}")
                for elem in listing_count_elements[:5]:
                    print(f"   - {elem.strip()}")
                
                # Ищем элементы с лотами
                # Обычно это market_listing_row_link
                listing_rows = soup.find_all('a', class_='market_listing_row_link')
                print(f"\n📊 Найдено market_listing_row_link: {len(listing_rows)}")
                
                # Ищем данные в JavaScript
                # Обычно данные в window.market_sellorder_data или подобном
                script_tags = soup.find_all('script')
                print(f"\n📊 Найдено script тегов: {len(script_tags)}")
                
                for script in script_tags:
                    if script.string:
                        # Ищем упоминания total_count, listing_count и т.д.
                        if 'total_count' in script.string or 'listing_count' in script.string:
                            # Извлекаем релевантные строки
                            lines = script.string.split('\n')
                            for i, line in enumerate(lines):
                                if 'total_count' in line or 'listing_count' in line:
                                    print(f"   Строка {i}: {line.strip()[:200]}")
                
                # Ищем данные в data-атрибутах
                data_elements = soup.find_all(attrs={'data-listingid': True})
                print(f"\n📊 Найдено элементов с data-listingid: {len(data_elements)}")
                
                return html
            else:
                print(f"\n❌ Ошибка: status_code={response.status_code}")
                return None
                
        except Exception as e:
            print(f"\n❌ Исключение: {e}")
            import traceback
            traceback.print_exc()
            return None

async def test_different_counts(hash_name: str, appid: int = 730):
    """Тестирует разные значения count."""
    print("\n" + "=" * 80)
    print(f"🧪 Тест разных значений count")
    print(f"   Предмет: {hash_name}")
    print("=" * 80)
    
    counts = [10, 20, 50, 100]
    
    for count in counts:
        print(f"\n{'='*80}")
        print(f"📊 Тест с count={count}")
        
        base_url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
        params = {
            "query": "",
            "start": 0,
            "count": count,
            "country": "BY",
            "language": "english",
            "currency": 1
        }
        url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    total_count = data.get('total_count', None)
                    results = data.get('results', [])
                    results_html = data.get('results_html', '')
                    results_html_len = len(results_html.strip()) if results_html else 0
                    
                    print(f"   ✅ status_code=200")
                    print(f"   total_count: {total_count}")
                    print(f"   results: {len(results)}")
                    print(f"   results_html_len: {results_html_len}")
                elif response.status_code == 429:
                    print(f"   ❌ status_code=429 (Too Many Requests)")
                else:
                    print(f"   ❌ status_code={response.status_code}")
                
                await asyncio.sleep(2)  # Задержка между запросами
                
            except Exception as e:
                print(f"   ❌ Исключение: {e}")

if __name__ == "__main__":
    hash_name = "AK-47 | Redline (Field-Tested)"
    
    # Тест с count=20
    print("1. Тест с count=20:")
    asyncio.run(test_render_count_20(hash_name))
    
    # Тест прямой страницы
    print("\n2. Тест прямой HTML страницы:")
    asyncio.run(test_steam_market_page(hash_name))
    
    # Тест разных count
    print("\n3. Тест разных значений count:")
    asyncio.run(test_different_counts(hash_name))

