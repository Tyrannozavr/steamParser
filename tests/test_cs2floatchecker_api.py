"""
Тестирование API cs2floatchecker.com для получения float и pattern.
Проверяем различные endpoints и форматы запросов.
"""
import asyncio
import httpx
from urllib.parse import quote, unquote
import json
import pytest

pytest_plugins = ('pytest_asyncio',)


async def test_cs2floatchecker_apis():
    """Тестирует различные endpoints API cs2floatchecker.com."""
    
    # Тестовые данные
    inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M720139732925859819A47696126279D16747423212568741781"
    listing_id = "720139732925859819"
    asset_id = "47696126279"
    
    # Извлекаем параметры из inspect ссылки
    # Формат: M{listingid}A{assetid}D{param}
    parts = inspect_link.split('M')
    if len(parts) > 1:
        rest = parts[1].split('A')
        if len(rest) > 1:
            listing_id = rest[0]
            asset_rest = rest[1].split('D')
            asset_id = asset_rest[0]
    
    print("=" * 70)
    print("🧪 ТЕСТИРОВАНИЕ API CS2FLOATCHECKER.COM")
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
        # 1. Float-rarity (известный рабочий)
        {
            "name": "Float-rarity (известный)",
            "url": f"https://api.cs2floatchecker.com/api/float-rarity/7/{asset_id}/0.1",
            "method": "GET"
        },
        # 2. Inspect через listing ID
        {
            "name": "Inspect через listing ID",
            "url": f"https://api.cs2floatchecker.com/api/inspect/{listing_id}",
            "method": "GET"
        },
        # 3. Inspect через asset ID
        {
            "name": "Inspect через asset ID",
            "url": f"https://api.cs2floatchecker.com/api/inspect/asset/{asset_id}",
            "method": "GET"
        },
        # 4. Item через listing ID
        {
            "name": "Item через listing ID",
            "url": f"https://api.cs2floatchecker.com/api/item/{listing_id}",
            "method": "GET"
        },
        # 5. Listing через listing ID
        {
            "name": "Listing через listing ID",
            "url": f"https://api.cs2floatchecker.com/api/listing/{listing_id}",
            "method": "GET"
        },
        # 6. Inspect через POST с телом
        {
            "name": "Inspect POST с inspect link",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"inspect": inspect_link}
        },
        # 7. Inspect через POST с listing ID
        {
            "name": "Inspect POST с listing ID",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"listing_id": listing_id}
        },
        # 8. Inspect через POST с asset ID
        {
            "name": "Inspect POST с asset ID",
            "url": "https://api.cs2floatchecker.com/api/inspect",
            "method": "POST",
            "json": {"asset_id": asset_id, "appid": 730}
        },
        # 9. Float и pattern отдельно
        {
            "name": "Float через asset ID",
            "url": f"https://api.cs2floatchecker.com/api/float/{asset_id}",
            "method": "GET"
        },
        # 10. Pattern через asset ID
        {
            "name": "Pattern через asset ID",
            "url": f"https://api.cs2floatchecker.com/api/pattern/{asset_id}",
            "method": "GET"
        },
        # 11. Paintseed через asset ID
        {
            "name": "Paintseed через asset ID",
            "url": f"https://api.cs2floatchecker.com/api/paintseed/{asset_id}",
            "method": "GET"
        },
        # 12. Полная информация через asset ID
        {
            "name": "Полная информация через asset ID",
            "url": f"https://api.cs2floatchecker.com/api/item-info/{asset_id}",
            "method": "GET"
        },
        # 13. Через Steam Market URL
        {
            "name": "Через Steam Market URL",
            "url": "https://api.cs2floatchecker.com/api/market-item",
            "method": "POST",
            "json": {"url": "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Nightwish%20%28Field-Tested%29"}
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
                        print(f"   📦 Ответ (первые 500 символов):")
                        print(f"   {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                        
                        # Проверяем наличие float и pattern
                        data_str = json.dumps(data, ensure_ascii=False).lower()
                        has_float = 'float' in data_str or 'floatvalue' in data_str
                        has_pattern = 'pattern' in data_str or 'paintseed' in data_str
                        
                        if has_float:
                            print(f"   🎯 НАЙДЕН FLOAT!")
                        if has_pattern:
                            print(f"   🎯 НАЙДЕН PATTERN!")
                        
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
    else:
        print("\n❌ Рабочих endpoints не найдено")
        print("\n💡 Возможные причины:")
        print("   1. API требует специальные заголовки или авторизацию")
        print("   2. API использует другой формат запросов")
        print("   3. API доступен только для расширения Chrome")
        print("   4. Нужно использовать другой endpoint или формат данных")


if __name__ == "__main__":
    asyncio.run(test_cs2floatchecker_apis())

