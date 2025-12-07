"""
Тестовый скрипт для проверки максимального значения count в render endpoint для листингов.
"""
import asyncio
import httpx
from urllib.parse import quote

HASH_NAME = "AK-47 | Slate (Field-Tested)"
APPID = 730
BASE_RENDER_URL = "https://steamcommunity.com/market/listings/{appid}/{hash_name}/render/"

async def test_count_value(client: httpx.AsyncClient, count: int) -> dict:
    """Тестирует запрос с указанным значением count."""
    encoded_name = quote(HASH_NAME, safe="")
    url = BASE_RENDER_URL.format(appid=APPID, hash_name=encoded_name)
    
    params = {
        "query": "",
        "start": 0,
        "count": count,
        "currency": 1,
        "language": "english",
        "country": "US"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://steamcommunity.com/market/listings/{APPID}/{encoded_name}",
        "Origin": "https://steamcommunity.com",
    }
    
    try:
        response = await client.get(url, params=params, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        
        total_count = data.get("total_count", 0)
        results_count = len(data.get("results", []))
        listinginfo_count = len(data.get("listinginfo", {}))
        
        return {
            "success": data.get("success", False),
            "total_count": total_count,
            "results_count": results_count,
            "listinginfo_count": listinginfo_count,
            "requested_count": count,
            "status_code": response.status_code
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "requested_count": count
        }


async def main():
    """Тестирует разные значения count."""
    print(f"🔍 Тестирование максимального значения count для: {HASH_NAME}\n")
    print("=" * 80)
    
    test_counts = [10, 50, 100, 200, 500]
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for count in test_counts:
            print(f"\n📊 Тестируем count={count}:")
            await asyncio.sleep(2.0)  # Задержка между запросами
            
            result = await test_count_value(client, count)
            
            if result.get("success"):
                print(f"   ✅ Успешно")
                print(f"   📈 total_count: {result.get('total_count')}")
                print(f"   📦 results: {result.get('results_count')} элементов")
                print(f"   📋 listinginfo: {result.get('listinginfo_count')} листингов")
                print(f"   🎯 Запрошено: {result.get('requested_count')}, получено: {result.get('results_count')}")
                
                if result.get('results_count') == count:
                    print(f"   ✅ Получено ровно столько, сколько запрошено!")
                elif result.get('results_count') < count:
                    print(f"   ⚠️ Получено меньше, чем запрошено (возможно, лимит)")
            else:
                print(f"   ❌ Ошибка: {result.get('error', 'Unknown')}")
    
    print("\n" + "=" * 80)
    print("📝 Выводы:")
    print("   - Проверьте, какое максимальное значение count поддерживается")
    print("   - Если count=100 работает, это значительно ускорит парсинг")


if __name__ == "__main__":
    asyncio.run(main())




