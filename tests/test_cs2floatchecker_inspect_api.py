"""
Тестирование различных endpoints API cs2floatchecker.com для парсинга inspect ссылок.
Проверяем все возможные варианты получения float и paintSeed.
"""
import asyncio
import httpx
from urllib.parse import quote, unquote
import json


async def test_inspect_endpoints():
    """Тестирует различные endpoints для парсинга inspect ссылок."""
    
    # Тестовая inspect ссылка
    inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M719013833069528178A47488648268D12604456091454546265"
    
    # Параметры из inspect ссылки
    listing_id = "719013833069528178"
    asset_id = "47488648268"
    
    print("=" * 70)
    print("🧪 ТЕСТИРОВАНИЕ API CS2FLOATCHECKER.COM ДЛЯ INSPECT ССЫЛОК")
    print("=" * 70)
    print(f"\n📋 Тестовые данные:")
    print(f"   Inspect link: {inspect_link[:80]}...")
    print(f"   Listing ID: {listing_id}")
    print(f"   Asset ID: {asset_id}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://steamcommunity.com/"
    }
    
    # Список возможных endpoints для проверки
    endpoints_to_test = [
        # 1. GET с inspect в query параметре
        {
            "name": "GET /api/inspect?inspect=...",
            "url": f"https://api.cs2floatchecker.com/api/inspect?inspect={quote(inspect_link)}",
            "method": "GET"
        },
        # 2. POST с inspect в body
        {
            "name": "POST /api/inspect",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"inspect": inspect_link}
        },
        # 3. POST с inspectLink
        {
            "name": "POST /api/inspect (inspectLink)",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"inspectLink": inspect_link}
        },
        # 4. POST с listing ID
        {
            "name": "POST /api/inspect (listingId)",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"listingId": listing_id}
        },
        # 5. GET через listing ID
        {
            "name": "GET /api/inspect/{listingId}",
            "url": f"https://api.cs2floatchecker.com/api/inspect/{listing_id}",
            "method": "GET"
        },
        # 6. GET через asset ID
        {
            "name": "GET /api/inspect/asset/{assetId}",
            "url": f"https://api.cs2floatchecker.com/api/inspect/asset/{asset_id}",
            "method": "GET"
        },
        # 7. POST с asset ID
        {
            "name": "POST /api/inspect (assetId)",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"assetId": asset_id, "appid": 730}
        },
        # 8. Parse-inspect endpoint
        {
            "name": "GET /api/parse-inspect",
            "url": f"https://api.cs2floatchecker.com/api/parse-inspect?inspect={quote(inspect_link)}",
            "method": "GET"
        },
        # 9. Item-info endpoint
        {
            "name": "GET /api/item-info",
            "url": f"https://api.cs2floatchecker.com/api/item-info?inspect={quote(inspect_link)}",
            "method": "GET"
        },
        # 10. Item endpoint
        {
            "name": "GET /api/item",
            "url": f"https://api.cs2floatchecker.com/api/item?inspect={quote(inspect_link)}",
            "method": "GET"
        },
        # 11. Получить данные через listing ID
        {
            "name": "GET /api/listing/{listingId}",
            "url": f"https://api.cs2floatchecker.com/api/listing/{listing_id}",
            "method": "GET"
        },
        # 12. Получить данные через asset ID
        {
            "name": "GET /api/asset/{assetId}",
            "url": f"https://api.cs2floatchecker.com/api/asset/{asset_id}",
            "method": "GET"
        },
    ]
    
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        working_endpoints = []
        
        for endpoint in endpoints_to_test:
            print(f"\n{'='*70}")
            print(f"🔹 Тестирую: {endpoint['name']}")
            print(f"   URL: {endpoint['url']}")
            print(f"   Method: {endpoint['method']}")
            
            try:
                if endpoint['method'] == 'GET':
                    response = await client.get(endpoint['url'])
                else:
                    json_data = endpoint.get('json', {})
                    response = await client.post(endpoint['url'], json=json_data)
                
                print(f"   Статус: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"   ✅ УСПЕХ!")
                        print(f"   📦 Ответ (первые 800 символов):")
                        print(f"   {json.dumps(data, indent=2, ensure_ascii=False)[:800]}")
                        
                        # Проверяем наличие float и pattern
                        data_str = json.dumps(data, ensure_ascii=False).lower()
                        has_float = 'float' in data_str or 'floatvalue' in data_str
                        has_pattern = 'paintseed' in data_str or 'pattern' in data_str
                        
                        if has_float:
                            print(f"   🎯 НАЙДЕН FLOAT!")
                        if has_pattern:
                            print(f"   🎯 НАЙДЕН PATTERN (PAINTSEED)!")
                        
                        working_endpoints.append({
                            'name': endpoint['name'],
                            'url': endpoint['url'],
                            'method': endpoint['method'],
                            'data': data,
                            'has_float': has_float,
                            'has_pattern': has_pattern
                        })
                    except Exception as e:
                        print(f"   ⚠️  Не JSON: {response.text[:200]}")
                elif response.status_code == 404:
                    print(f"   ❌ Endpoint не найден")
                elif response.status_code == 400:
                    print(f"   ⚠️  Bad Request - возможно неправильный формат")
                    try:
                        error_data = response.json()
                        print(f"   Ошибка: {json.dumps(error_data, indent=2, ensure_ascii=False)[:300]}")
                    except:
                        print(f"   Текст ошибки: {response.text[:200]}")
                else:
                    print(f"   ❌ Ошибка: {response.status_code}")
                    print(f"   Ответ: {response.text[:200]}")
                    
            except Exception as e:
                print(f"   ❌ Исключение: {type(e).__name__}: {e}")
    
    # Итоги
    print("\n" + "=" * 70)
    print("📊 ИТОГИ")
    print("=" * 70)
    print(f"✅ Найдено рабочих endpoints: {len(working_endpoints)}")
    
    if working_endpoints:
        print("\n🎯 Рабочие endpoints:")
        for ep in working_endpoints:
            print(f"\n   📌 {ep['name']}")
            print(f"      URL: {ep['url']}")
            print(f"      Method: {ep['method']}")
            print(f"      Float: {'✅' if ep['has_float'] else '❌'}")
            print(f"      Pattern: {'✅' if ep['has_pattern'] else '❌'}")
            
            # Показываем структуру данных
            if ep['has_pattern']:
                print(f"      📦 Структура данных с pattern:")
                print(f"      {json.dumps(ep['data'], indent=6, ensure_ascii=False)[:500]}")
    else:
        print("\n❌ Рабочих endpoints не найдено")
        print("\n💡 Возможные причины:")
        print("   1. API требует специальные заголовки или авторизацию")
        print("   2. API использует другой формат запросов")
        print("   3. API доступен только для расширения Chrome")
        print("   4. Нужно использовать другой endpoint или формат данных")


if __name__ == "__main__":
    asyncio.run(test_inspect_endpoints())

