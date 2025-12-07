"""
Тест /render/ API с прокси из базы данных.
"""
import asyncio
import httpx
import json
from urllib.parse import quote
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import DatabaseManager, Config
from services.proxy_manager import ProxyManager

async def test_render_with_proxy(hash_name: str, appid: int = 730):
    """Тестирует /render/ API с прокси."""
    print("=" * 80)
    print(f"🧪 Тест /render/ API с прокси")
    print(f"   Предмет: {hash_name}")
    print("=" * 80)
    
    # Инициализация БД и ProxyManager
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    proxy_manager = ProxyManager(db_session)
    proxy = await proxy_manager.get_next_proxy(force_refresh=False)
    
    if not proxy:
        print("❌ Нет доступных прокси в базе данных")
        await db_manager.close()
        return None
    
    print(f"✅ Используем прокси ID={proxy.id}: {proxy.url[:50]}...")
    
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
    
    # Делаем запрос через прокси
    proxy_dict = {"http://": proxy.url, "https://": proxy.url}
    
    async with httpx.AsyncClient(proxies=proxy_dict, timeout=30.0) as client:
        try:
            print(f"\n⏳ Отправка запроса через прокси...")
            response = await client.get(url)
            print(f"✅ Получен ответ: status_code={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                print(f"\n📊 Структура ответа:")
                print(f"   Ключи: {list(data.keys())}")
                
                success = data.get('success', False)
                total_count = data.get('total_count', None)
                results = data.get('results', [])
                results_html = data.get('results_html', '')
                results_html_len = len(results_html.strip()) if results_html else 0
                
                print(f"\n📋 Детали ответа:")
                print(f"   success: {success}")
                print(f"   total_count: {total_count} (тип: {type(total_count).__name__})")
                print(f"   results: {len(results)} элементов")
                print(f"   results_html: {results_html_len} символов")
                
                # Сохраняем ответ (без results_html)
                data_for_save = {k: v for k, v in data.items() if k != 'results_html'}
                filename = f'test_render_with_proxy_{hash_name.replace(" ", "_").replace("|", "").replace("™", "")}.json'
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(data_for_save, f, indent=2, ensure_ascii=False)
                print(f"\n💾 Ответ сохранен в {filename} (без results_html)")
                
                if total_count and total_count > 0:
                    print(f"\n✅ УСПЕХ: total_count = {total_count} - лоты найдены!")
                elif results_html_len > 500:
                    print(f"\n⚠️  total_count отсутствует или = 0, но results_html_len = {results_html_len}")
                    print(f"   Возможно, лоты есть в HTML, но total_count не установлен")
                else:
                    print(f"\n❌ total_count = {total_count}, results_html_len = {results_html_len}")
                    print(f"   Лоты не найдены")
                
                await db_manager.close()
                return data
            elif response.status_code == 429:
                print(f"\n❌ 429 Too Many Requests - прокси заблокирован")
                await proxy_manager.mark_proxy_used(proxy, success=False, error="429 Too Many Requests", is_429_error=True)
                await db_manager.close()
                return None
            else:
                print(f"\n❌ Ошибка: status_code={response.status_code}")
                print(f"   Текст ответа: {response.text[:500]}")
                await db_manager.close()
                return None
                
        except Exception as e:
            print(f"\n❌ Исключение: {e}")
            import traceback
            traceback.print_exc()
            await db_manager.close()
            return None

async def test_all_variants_with_proxy():
    """Тестирует все варианты с прокси."""
    variants = [
        "AK-47 | Redline (Field-Tested)",
        "AK-47 | Redline (Minimal Wear)",
    ]
    
    print("\n" + "=" * 80)
    print("🧪 Тестирование вариантов с прокси")
    print("=" * 80)
    
    results = {}
    for variant in variants:
        print(f"\n{'='*80}")
        data = await test_render_with_proxy(variant)
        results[variant] = data
        await asyncio.sleep(3)  # Задержка между запросами
    
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
                results_html_len = len(data.get('results_html', '').strip())
                print(f"⚠️  {variant}: total_count={total_count}, results_html_len={results_html_len}")
        else:
            print(f"❌ {variant}: нет данных")
    
    print(f"\n✅ Валидных вариантов: {valid_count}/{len(variants)}")

if __name__ == "__main__":
    # Тестируем один вариант
    asyncio.run(test_render_with_proxy("AK-47 | Redline (Field-Tested)"))

