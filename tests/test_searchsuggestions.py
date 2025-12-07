"""
Тест searchsuggestionsresults API для проверки listing_count.
"""
import asyncio
import httpx
import json

async def test_searchsuggestions(item_name: str):
    """Тестирует searchsuggestionsresults API."""
    print("=" * 80)
    print(f"🧪 Тест searchsuggestionsresults API")
    print(f"   Запрос: {item_name}")
    print("=" * 80)
    
    url = "https://steamcommunity.com/market/searchsuggestionsresults"
    params = {"q": item_name}
    
    print(f"\n📡 URL запроса:")
    print(f"   {url}?q={item_name}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n⏳ Отправка запроса...")
            response = await client.get(url, params=params)
            print(f"✅ Получен ответ: status_code={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                print(f"\n📊 Структура ответа:")
                print(f"   Ключи: {list(data.keys())}")
                
                results = data.get('results', [])
                print(f"\n📋 Найдено вариантов: {len(results)}")
                
                for i, result in enumerate(results, 1):
                    market_name = result.get('market_name', 'N/A')
                    market_hash_name = result.get('market_hash_name', 'N/A')
                    listing_count = result.get('listing_count', None)
                    min_price = result.get('min_price', 0) / 100 if result.get('min_price') else 0
                    
                    print(f"\n   {i}. {market_name}")
                    print(f"      market_hash_name: {market_hash_name}")
                    print(f"      listing_count: {listing_count} (тип: {type(listing_count).__name__})")
                    print(f"      min_price: ${min_price:.2f}")
                    
                    # Проверяем все ключи
                    print(f"      Все ключи: {list(result.keys())}")
                
                # Сохраняем ответ
                with open('test_searchsuggestions_response.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"\n💾 Ответ сохранен в test_searchsuggestions_response.json")
                
                return data
            else:
                print(f"\n❌ Ошибка: status_code={response.status_code}")
                print(f"   Текст ответа: {response.text[:500]}")
                return None
                
        except Exception as e:
            print(f"\n❌ Исключение: {e}")
            import traceback
            traceback.print_exc()
            return None

if __name__ == "__main__":
    asyncio.run(test_searchsuggestions("AK-47 | Redline"))

