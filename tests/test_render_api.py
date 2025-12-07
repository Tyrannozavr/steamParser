"""
Тестовый скрипт для проверки API /render/ напрямую.
"""
import asyncio
import httpx
import json
import re
from urllib.parse import quote
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(lambda msg: print(msg, end=''), format="{time:HH:mm:ss} | {level} | {message}", level="DEBUG")


async def test_render_api(hash_name: str, appid: int = 730):
    """Тестирует API /render/ для конкретного hash_name."""
    print("=" * 80)
    print(f"🧪 Тест API /render/ для '{hash_name}'")
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
    
    # Делаем запрос с повторными попытками
    async with httpx.AsyncClient(timeout=30.0) as client:
        max_retries = 5
        response = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = (attempt + 1) * 5
                    print(f"\n⏳ Попытка {attempt + 1}/{max_retries}, ждем {delay} сек...")
                    await asyncio.sleep(delay)
                
                print(f"\n⏳ Отправка запроса (попытка {attempt + 1}/{max_retries})...")
                response = await client.get(url)
                print(f"📥 Статус ответа: {response.status_code}")
                
                if response.status_code == 429:
                    print(f"⚠️ Получен 429, ждем перед следующей попыткой...")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        print(f"❌ Все попытки исчерпаны, получили 429")
                        return None
                
                if response.status_code == 200:
                    break
                else:
                    print(f"⚠️ Неожиданный статус {response.status_code}, пробуем еще раз...")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return None
                        
            except Exception as e:
                print(f"❌ Ошибка на попытке {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return None
        
        if not response or response.status_code != 200:
            print(f"❌ Не удалось получить успешный ответ")
            return None
        
        # Парсим ответ
        try:
            data = response.json()
            
            print(f"\n📊 Структура ответа:")
            print(f"   Ключи: {list(data.keys())}")
            
            # Проверяем основные поля
            success = data.get('success', False)
            total_count = data.get('total_count', None)
            results = data.get('results', [])
            results_html = data.get('results_html', '')
            assets = data.get('assets', {})
            
            print(f"\n📋 Основные поля:")
            print(f"   success: {success}")
            print(f"   total_count: {total_count} (тип: {type(total_count)})")
            print(f"   results: {len(results)} элементов")
            print(f"   results_html: длина {len(results_html)} символов")
            print(f"   assets: {len(assets)} элементов")
            
            # Выводим полный ответ (без results_html, т.к. он очень большой)
            data_for_print = {k: v for k, v in data.items() if k != 'results_html'}
            print(f"\n📄 Полный ответ (без results_html):")
            print(json.dumps(data_for_print, indent=2, ensure_ascii=False))
            
            # Проверяем results_html
            if results_html:
                print(f"\n📄 Первые 500 символов results_html:")
                print(results_html[:500])
                
                # Ищем упоминания количества лотов в HTML
                count_patterns = [
                    (r'(\d+)\s+listings?', 'listings'),
                    (r'showing\s+(\d+)', 'showing'),
                    (r'total[:\s]+(\d+)', 'total'),
                    (r'(\d+)\s+items?', 'items'),
                ]
                print(f"\n🔍 Поиск количества лотов в HTML:")
                for pattern, name in count_patterns:
                    matches = re.findall(pattern, results_html, re.IGNORECASE)
                    if matches:
                        print(f"   Найдено '{name}': {matches}")
            
            # Проверяем assets
            if assets:
                print(f"\n📦 Assets (первые 3):")
                for i, (key, value) in enumerate(list(assets.items())[:3]):
                    print(f"   {key}: {type(value)}")
                    if isinstance(value, dict):
                        print(f"      Ключи: {list(value.keys())[:5]}")
            
            # Итоговый вывод
            print(f"\n" + "=" * 80)
            if success and total_count is not None:
                if total_count > 0:
                    print(f"✅ УСПЕХ: Предмет валиден, {total_count} лотов")
                else:
                    print(f"⚠️ ВНИМАНИЕ: success=True, но total_count=0")
                    if len(results_html) > 500:
                        print(f"   Но results_html длиной {len(results_html)} - возможно, лоты есть")
            elif success and total_count is None:
                print(f"⚠️ ВНИМАНИЕ: success=True, но total_count отсутствует в ответе")
                if len(results_html) > 500:
                    print(f"   Но results_html длиной {len(results_html)} - возможно, лоты есть")
            else:
                print(f"❌ ОШИБКА: success=False или total_count не найден")
            print("=" * 80)
            
            return data
            
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            print(f"   Первые 500 символов ответа:")
            print(response.text[:500])
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
    
    results = {}
    for variant in variants:
        print(f"\n\n{'='*80}")
        print(f"Тестируем: {variant}")
        print(f"{'='*80}\n")
        data = await test_render_api(variant)
        results[variant] = data
        await asyncio.sleep(2)  # Задержка между запросами
    
    print(f"\n\n{'='*80}")
    print("📊 ИТОГОВЫЕ РЕЗУЛЬТАТЫ")
    print(f"{'='*80}\n")
    
    valid_count = 0
    for variant, data in results.items():
        if data:
            success = data.get('success', False)
            total_count = data.get('total_count', 0)
            if success and total_count and total_count > 0:
                print(f"✅ {variant}: {total_count} лотов")
                valid_count += 1
            else:
                print(f"❌ {variant}: success={success}, total_count={total_count}")
        else:
            print(f"❌ {variant}: нет данных")
    
    print(f"\n📊 Итого: {valid_count}/{len(variants)} вариантов валидны")
    return results


if __name__ == "__main__":
    # Тестируем один вариант сначала
    print("🧪 Тест одного варианта:")
    result = asyncio.run(test_render_api("AK-47 | Redline (Field-Tested)"))
    
    if result and result.get('success') and result.get('total_count', 0) > 0:
        print("\n✅ Первый тест успешен, тестируем все варианты...")
        asyncio.run(test_all_variants())
    else:
        print("\n❌ Первый тест не прошел, проверьте логи выше")
