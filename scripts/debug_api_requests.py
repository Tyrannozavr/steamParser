"""
Скрипт для отладки API запросов на странице Steam Market.
Помогает найти, откуда расширение Chrome получает float и pattern.
"""
import asyncio
import httpx
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse, parse_qs, unquote


class APIDebugger:
    """Отладчик для поиска API запросов."""

    def __init__(self, proxy=None):
        self.proxy = proxy
        self.client = None
        self.found_apis = []

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            proxy=self.proxy,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def fetch_page(self, url: str) -> str:
        """Загружает страницу."""
        print(f"\n🔍 Загружаю страницу: {url}")
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text

    def extract_js_objects(self, html: str) -> list:
        """Извлекает JavaScript объекты из HTML."""
        objects = []
        
        # Ищем g_rgListingInfo, g_rgItemInfo и другие объекты
        patterns = [
            r'g_rgListingInfo\s*=\s*(\{.*?\});',
            r'g_rgItemInfo\s*=\s*(\{.*?\});',
            r'g_rgAssets\s*=\s*(\{.*?\});',
            r'var\s+rgListingInfo\s*=\s*(\{.*?\});',
            r'var\s+rgItemInfo\s*=\s*(\{.*?\});',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    obj_str = match.group(1)
                    # Пытаемся распарсить как JSON
                    obj = json.loads(obj_str)
                    objects.append(obj)
                except:
                    pass
        
        return objects

    def extract_api_urls(self, html: str) -> list:
        """Извлекает возможные API URL из HTML и JavaScript."""
        urls = set()
        
        # Ищем все URL в JavaScript
        url_patterns = [
            r'["\'](https?://[^"\']+api[^"\']+)["\']',
            r'["\'](https?://[^"\']+float[^"\']+)["\']',
            r'["\'](https?://[^"\']+pattern[^"\']+)["\']',
            r'["\'](https?://[^"\']+inspect[^"\']+)["\']',
            r'["\'](https?://[^"\']+cs2float[^"\']+)["\']',
            r'["\'](https?://[^"\']+csgofloat[^"\']+)["\']',
            r'["\'](https?://[^"\']+cs\.money[^"\']+)["\']',
            r'["\'](https?://[^"\']+buff[^"\']+)["\']',
        ]
        
        for pattern in url_patterns:
            matches = re.finditer(pattern, html, re.IGNORECASE)
            for match in matches:
                url = match.group(1)
                if 'api' in url.lower() or 'float' in url.lower() or 'pattern' in url.lower():
                    urls.add(url)
        
        return list(urls)

    def extract_inspect_links(self, html: str) -> list:
        """Извлекает inspect ссылки."""
        links = []
        
        # Ищем steam:// ссылки
        pattern = r'steam://rungame/[^\s"\'<>]+'
        matches = re.finditer(pattern, html)
        for match in matches:
            links.append(match.group(0))
        
        # Ищем в href
        soup = BeautifulSoup(html, 'lxml')
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if 'steam://' in href or 'inspect' in href.lower():
                links.append(href)
        
        return list(set(links))

    def extract_listing_ids(self, html: str) -> list:
        """Извлекает listing ID из страницы."""
        ids = []
        
        # Ищем в JavaScript объектах
        pattern = r'listingid["\']?\s*:\s*["\']?(\d+)'
        matches = re.finditer(pattern, html, re.IGNORECASE)
        for match in matches:
            ids.append(match.group(1))
        
        # Ищем в URL параметрах
        pattern = r'[?&]listingid=(\d+)'
        matches = re.finditer(pattern, html, re.IGNORECASE)
        for match in matches:
            ids.append(match.group(1))
        
        return list(set(ids))

    def extract_asset_ids(self, html: str) -> list:
        """Извлекает asset ID из страницы."""
        ids = []
        
        patterns = [
            r'assetid["\']?\s*:\s*["\']?(\d+)',
            r'asset["\']?\s*:\s*["\']?(\d+)',
            r'[?&]assetid=(\d+)',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, html, re.IGNORECASE)
            for match in matches:
                ids.append(match.group(1))
        
        return list(set(ids))

    async def test_api_endpoints(self, inspect_link: str, listing_id: str = None, asset_id: str = None):
        """Тестирует различные API endpoints."""
        print("\n🧪 Тестирую API endpoints...")
        
        # Извлекаем параметры из inspect ссылки
        inspect_params = {}
        if 'A' in inspect_link:
            parts = inspect_link.split('A')
            if len(parts) > 1:
                asset_part = parts[1].split('D')[0] if 'D' in parts[1] else parts[1]
                inspect_params['asset_id'] = asset_part
        
        # Список возможных API для проверки
        apis_to_test = []
        
        # CS2FloatChecker API
        if asset_id:
            apis_to_test.append({
                'name': 'CS2FloatChecker - float-rarity',
                'url': f'https://api.cs2floatchecker.com/api/float-rarity/7/{asset_id}/0.1',
                'method': 'GET'
            })
        
        # CSGOFloat API
        if inspect_link:
            encoded_inspect = httpx.URL(inspect_link).raw_path.decode()
            apis_to_test.append({
                'name': 'CSGOFloat - inspect',
                'url': f'https://csgofloat.com/api/v1/listings?inspect_link={encoded_inspect}',
                'method': 'GET'
            })
        
        # CS.Money API
        if listing_id:
            apis_to_test.append({
                'name': 'CS.Money - listing',
                'url': f'https://cs.money/api/v1/steam/listing/{listing_id}',
                'method': 'GET'
            })
        
        # Проверяем каждый API
        for api in apis_to_test:
            try:
                print(f"\n  🔹 Проверяю: {api['name']}")
                print(f"     URL: {api['url']}")
                
                response = await self.client.get(api['url'])
                if response.status_code == 200:
                    data = response.json()
                    print(f"     ✅ Успешно! Статус: {response.status_code}")
                    print(f"     📦 Ответ: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}...")
                    
                    # Проверяем наличие float и pattern
                    if 'float' in str(data).lower() or 'floatValue' in str(data):
                        print(f"     🎯 НАЙДЕН FLOAT!")
                    if 'pattern' in str(data).lower() or 'paintseed' in str(data).lower() or 'paintSeed' in str(data):
                        print(f"     🎯 НАЙДЕН PATTERN!")
                    
                    self.found_apis.append({
                        'name': api['name'],
                        'url': api['url'],
                        'data': data
                    })
                else:
                    print(f"     ❌ Ошибка: {response.status_code}")
            except Exception as e:
                print(f"     ⚠️  Исключение: {e}")

    async def analyze_page(self, url: str):
        """Анализирует страницу и ищет источники данных."""
        print("=" * 70)
        print("🔍 ОТЛАДКА API ЗАПРОСОВ STEAM MARKET")
        print("=" * 70)
        
        # Загружаем страницу
        html = await self.fetch_page(url)
        
        print(f"\n📄 Размер HTML: {len(html)} байт")
        
        # Извлекаем inspect ссылки
        print("\n🔗 Ищу inspect ссылки...")
        inspect_links = self.extract_inspect_links(html)
        print(f"   Найдено inspect ссылок: {len(inspect_links)}")
        if inspect_links:
            print(f"   Первая ссылка: {inspect_links[0][:100]}...")
        
        # Извлекаем listing ID
        print("\n🆔 Ищу listing ID...")
        listing_ids = self.extract_listing_ids(html)
        print(f"   Найдено listing ID: {len(listing_ids)}")
        if listing_ids:
            print(f"   Listing IDs: {listing_ids[:5]}")
        
        # Извлекаем asset ID
        print("\n🆔 Ищу asset ID...")
        asset_ids = self.extract_asset_ids(html)
        print(f"   Найдено asset ID: {len(asset_ids)}")
        if asset_ids:
            print(f"   Asset IDs: {asset_ids[:5]}")
        
        # Извлекаем JavaScript объекты
        print("\n📦 Ищу JavaScript объекты...")
        js_objects = self.extract_js_objects(html)
        print(f"   Найдено объектов: {len(js_objects)}")
        if js_objects:
            print(f"   Ключи первого объекта: {list(js_objects[0].keys())[:10]}")
        
        # Извлекаем API URL
        print("\n🌐 Ищу API URL в коде...")
        api_urls = self.extract_api_urls(html)
        print(f"   Найдено возможных API URL: {len(api_urls)}")
        if api_urls:
            for url in api_urls[:10]:
                print(f"   - {url}")
        
        # Тестируем API endpoints
        if inspect_links:
            listing_id = listing_ids[0] if listing_ids else None
            asset_id = asset_ids[0] if asset_ids else None
            await self.test_api_endpoints(inspect_links[0], listing_id, asset_id)
        
        # Итоги
        print("\n" + "=" * 70)
        print("📊 ИТОГИ")
        print("=" * 70)
        print(f"✅ Найдено рабочих API: {len(self.found_apis)}")
        for api in self.found_apis:
            print(f"\n   📌 {api['name']}")
            print(f"      URL: {api['url']}")


async def main():
    """Главная функция."""
    url = "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Nightwish%20%28Field-Tested%29"
    
    async with APIDebugger() as debugger:
        await debugger.analyze_page(url)


if __name__ == "__main__":
    asyncio.run(main())

