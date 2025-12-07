"""
Прямой тест API /render/ для проверки ответа Steam.
"""
import asyncio
import httpx
import json
from urllib.parse import quote

async def test_render_api(hash_name: str, appid: int = 730):
    """Тестирует прямой запрос к /render/ API."""
    print("=" * 80)
    print(f"🧪 Тест прямого запроса к /render/ API")
    print(f"   Предмет: {hash_name}")
    print(f"   AppID: {appid}")
    print("=" * 80)
    
    # Формируем URL
    base_url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
    params = {
        "query": "",
        "start": 0,
        "count": 10,
        "country": "BY",
        "language": "english",
        "currency": 1
    }
    url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
    
    print(f"\n📡 URL запроса:")
    print(f"   {url}")
    
    # Делаем запрос
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"\n⏳ Отправка запроса...")
            response = await client.get(url)
            print(f"✅ Получен ответ: status_code={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                print(f"\n📊 Структура ответа:")
                print(f"   Ключи: {list(data.keys())}")
                
                print(f"\n📋 Детали ответа:")
                for key, value in data.items():
                    if key == 'results_html':
                        html_len = len(str(value)) if value else 0
                        print(f"   {key}: [HTML, длина: {html_len} символов]")
                    elif key == 'assets':
                        assets_count = len(value) if isinstance(value, dict) else 0
                        print(f"   {key}: [Dict, количество элементов: {assets_count}]")
                    elif isinstance(value, (dict, list)):
                        print(f"   {key}: {type(value).__name__} (длина: {len(value)})")
                    else:
                        print(f"   {key}: {value}")
                
                # Проверяем total_count
                total_count = data.get('total_count', None)
                success = data.get('success', False)
                results = data.get('results', [])
                results_html = data.get('results_html', '')
                results_html_len = len(results_html.strip()) if results_html else 0
                
                print(f"\n🔍 Анализ:")
                print(f"   success: {success}")
                print(f"   total_count: {total_count} (тип: {type(total_count).__name__})")
                print(f"   results: {len(results)} элементов")
                print(f"   results_html: {results_html_len} символов")
                
                if total_count is None:
                    print(f"\n❌ ПРОБЛЕМА: total_count отсутствует в ответе!")
                elif total_count == 0:
                    print(f"\n⚠️  total_count = 0")
                    if results_html_len > 100:
                        print(f"   Но results_html_len = {results_html_len} - возможно, лоты есть в HTML")
                else:
                    print(f"\n✅ total_count = {total_count} - лоты найдены!")
                
                # Сохраняем полный ответ в файл (без results_html для читаемости)
                data_for_save = {k: v for k, v in data.items() if k != 'results_html'}
                with open(f'test_render_response_{hash_name.replace(" ", "_").replace("|", "")}.json', 'w', encoding='utf-8') as f:
                    json.dump(data_for_save, f, indent=2, ensure_ascii=False)
                print(f"\n💾 Ответ сохранен в test_render_response_*.json (без results_html)")
                
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

async def test_all_variants():
    """Тестирует все варианты AK-47 | Redline."""
    variants = [
        "AK-47 | Redline (Field-Tested)",
        "AK-47 | Redline (Minimal Wear)",
        "AK-47 | Redline (Well-Worn)",
        "AK-47 | Redline (Battle-Scarred)",
        "StatTrak™ AK-47 | Redline (Field-Tested)",
        "StatTrak™ AK-47 | Redline (Minimal Wear)",
        "StatTrak™ AK-47 | Redline (Well-Worn)",
        "StatTrak™ AK-47 | Redline (Battle-Scarred)",
    ]
    
    print("\n" + "=" * 80)
    print("🧪 Тестирование всех вариантов AK-47 | Redline")
    print("=" * 80)
    
    results = {}
    for variant in variants:
        print(f"\n{'='*80}")
        data = await test_render_api(variant)
        results[variant] = data
        await asyncio.sleep(2)  # Задержка между запросами
    
    print("\n" + "=" * 80)
    print("📊 ИТОГИ:")
    print("=" * 80)
    
    valid_count = 0
    for variant, data in results.items():
        if data:
            total_count = data.get('total_count', 0)
            if total_count and total_count > 0:
                print(f"✅ {variant}: {total_count} лотов")
                valid_count += 1
            else:
                print(f"❌ {variant}: total_count={total_count}")
        else:
            print(f"❌ {variant}: нет данных")
    
    print(f"\n✅ Валидных вариантов: {valid_count}/{len(variants)}")

if __name__ == "__main__":
    # Сначала тестируем один вариант
    print("Тест одного варианта:")
    asyncio.run(test_render_api("AK-47 | Redline (Field-Tested)"))
    
    # Потом все варианты
    print("\n\nТест всех вариантов:")
    asyncio.run(test_all_variants())
