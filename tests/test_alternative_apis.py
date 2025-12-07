"""
Тестирование альтернативных API для получения float и pattern (paintSeed) из inspect ссылок.
"""
import asyncio
import httpx
from urllib.parse import quote, unquote
import json
import re
import pytest

pytest_plugins = ('pytest_asyncio',)


async def test_csgofloat_api(inspect_link: str = None):
    """Тестирует CSGOFloat API."""
    if inspect_link is None:
        inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M720139732925859819A47696126279D16747423212568741781"
    print("\n" + "="*70)
    print("🔹 Тестирую CSGOFloat API")
    print("="*70)
    
    # Парсим inspect ссылку
    pattern = r'csgo_econ_action_preview.*?M(\d+)A(\d+)D(\d+)'
    match = re.search(pattern, inspect_link)
    
    if not match:
        print("❌ Не удалось распарсить inspect ссылку")
        return None
    
    listing_id, asset_id, d_param = match.groups()
    print(f"   Listing ID: {listing_id}")
    print(f"   Asset ID: {asset_id}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    endpoints = [
        {
            "name": "CSGOFloat - Listing",
            "url": f"https://csgofloat.com/api/v1/listings/{listing_id}",
            "method": "GET"
        },
        {
            "name": "CSGOFloat - Item",
            "url": f"https://csgofloat.com/api/v1/item/{asset_id}",
            "method": "GET"
        },
        {
            "name": "CSGOFloat - Inspect (encoded)",
            "url": f"https://csgofloat.com/api/v1/inspect?inspect={quote(inspect_link.replace('steam://', ''))}",
            "method": "GET"
        },
    ]
    
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        for endpoint in endpoints:
            try:
                print(f"\n   Тестирую: {endpoint['name']}")
                print(f"   URL: {endpoint['url']}")
                
                response = await client.get(endpoint['url'])
                print(f"   Статус: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"   ✅ УСПЕХ!")
                    
                    # Ищем float и pattern
                    float_val = None
                    pattern_val = None
                    
                    # Разные форматы ответа
                    if 'iteminfo' in data:
                        iteminfo = data['iteminfo']
                        float_val = iteminfo.get('floatvalue') or iteminfo.get('float')
                        pattern_val = iteminfo.get('paintseed') or iteminfo.get('paintSeed') or iteminfo.get('pattern')
                    elif 'item' in data:
                        item = data['item']
                        float_val = item.get('floatvalue') or item.get('float')
                        pattern_val = item.get('paintseed') or item.get('paintSeed') or item.get('pattern')
                    elif isinstance(data, dict):
                        float_val = data.get('floatvalue') or data.get('float') or data.get('floatValue')
                        pattern_val = data.get('paintseed') or data.get('paintSeed') or data.get('pattern')
                    
                    if float_val or pattern_val:
                        print(f"   🎯 Float: {float_val}")
                        print(f"   🎯 Pattern: {pattern_val}")
                        return {
                            'float_value': float(float_val) if float_val else None,
                            'pattern': int(pattern_val) if pattern_val else None,
                            'source': 'csgofloat_api',
                            'endpoint': endpoint['name']
                        }
                    else:
                        print(f"   ⚠️  Данные найдены, но float/pattern не обнаружены")
                        print(f"   Структура: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                else:
                    print(f"   ❌ Ошибка: {response.status_code}")
                    if response.status_code != 404:
                        print(f"   Ответ: {response.text[:200]}")
            except Exception as e:
                print(f"   ❌ Исключение: {type(e).__name__}: {e}")
    
    return None


async def test_csfloat_api(inspect_link: str = None):
    """Тестирует CSFloat API."""
    if inspect_link is None:
        inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M720139732925859819A47696126279D16747423212568741781"
    print("\n" + "="*70)
    print("🔹 Тестирую CSFloat API")
    print("="*70)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    endpoints = [
        {
            "name": "CSFloat - Inspect",
            "url": f"https://csfloat.com/api/v1/get_single_item_info?inspect_link={quote(inspect_link)}",
            "method": "GET"
        },
    ]
    
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        for endpoint in endpoints:
            try:
                print(f"\n   Тестирую: {endpoint['name']}")
                print(f"   URL: {endpoint['url']}")
                
                response = await client.get(endpoint['url'])
                print(f"   Статус: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"   ✅ УСПЕХ!")
                    
                    # Ищем float и pattern
                    float_val = None
                    pattern_val = None
                    
                    if isinstance(data, dict):
                        float_val = data.get('floatvalue') or data.get('float') or data.get('floatValue')
                        pattern_val = data.get('paintseed') or data.get('paintSeed') or data.get('pattern') or data.get('paint_seed')
                    
                    if float_val or pattern_val:
                        print(f"   🎯 Float: {float_val}")
                        print(f"   🎯 Pattern: {pattern_val}")
                        return {
                            'float_value': float(float_val) if float_val else None,
                            'pattern': int(pattern_val) if pattern_val else None,
                            'source': 'csfloat_api',
                            'endpoint': endpoint['name']
                        }
                    else:
                        print(f"   ⚠️  Данные найдены, но float/pattern не обнаружены")
                        print(f"   Структура: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                else:
                    print(f"   ❌ Ошибка: {response.status_code}")
                    print(f"   Ответ: {response.text[:200]}")
            except Exception as e:
                print(f"   ❌ Исключение: {type(e).__name__}: {e}")
    
    return None


async def test_steam_inventory_helper_api(inspect_link: str = None):
    """Тестирует Steam Inventory Helper API (если доступен)."""
    print("\n" + "="*70)
    print("🔹 Тестирую Steam Inventory Helper API")
    print("="*70)
    
    # SIH обычно использует свой API, но он может быть недоступен публично
    print("   ⚠️  Steam Inventory Helper API обычно недоступен публично")
    return None


async def main():
    """Главная функция."""
    print("="*70)
    print("🧪 ТЕСТИРОВАНИЕ АЛЬТЕРНАТИВНЫХ API ДЛЯ ПОЛУЧЕНИЯ FLOAT И PATTERN")
    print("="*70)
    
    # Тестовая inspect ссылка
    inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M719013833069528178A47488648268D12604456091454546265"
    
    print(f"\n📋 Тестовая inspect ссылка:")
    print(f"   {inspect_link}")
    
    results = []
    
    # Тестируем CSGOFloat API
    result = await test_csgofloat_api(inspect_link)
    if result:
        results.append(result)
    
    # Тестируем CSFloat API
    result = await test_csfloat_api(inspect_link)
    if result:
        results.append(result)
    
    # Тестируем Steam Inventory Helper API
    result = await test_steam_inventory_helper_api(inspect_link)
    if result:
        results.append(result)
    
    # Итоги
    print("\n" + "="*70)
    print("📊 ИТОГИ")
    print("="*70)
    
    if results:
        print(f"\n✅ Найдено рабочих API: {len(results)}")
        for r in results:
            print(f"\n   📌 {r['source']} ({r['endpoint']})")
            print(f"      Float: {r['float_value']}")
            print(f"      Pattern: {r['pattern']}")
    else:
        print("\n❌ Рабочих API не найдено")
        print("\n💡 Возможные причины:")
        print("   1. API требуют авторизацию или API ключ")
        print("   2. API имеют ограничения по частоте запросов")
        print("   3. API недоступны публично")
        print("   4. Нужно использовать другой формат запросов")


if __name__ == "__main__":
    asyncio.run(main())

