"""
Тестовый скрипт для проверки запросов к Steam Market API.
Имитирует запрос с реального устройства с улучшенными заголовками.

Поддерживает:
- httpx (стандартный)
- curl_cffi (более реалистичная имитация браузера, если установлен)

Установка curl_cffi:
    pip install curl_cffi
"""
import asyncio
import json
import httpx
from datetime import datetime
from typing import Optional, Dict, Any
import random

# Пробуем импортировать curl_cffi для более реалистичной имитации
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    print("💡 curl_cffi не установлен. Для более реалистичной имитации установите: pip install curl_cffi")

# Реалистичные User-Agent для разных устройств
REALISTIC_USER_AGENTS = [
    # Chrome на Windows 11 (самый популярный)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Chrome на macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Firefox на Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Edge на Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    # Safari на macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
]

# Реалистичные заголовки для Chrome
def get_realistic_chrome_headers() -> Dict[str, str]:
    """Генерирует реалистичные заголовки как у Chrome браузера."""
    user_agent = random.choice(REALISTIC_USER_AGENTS)
    
    # Определяем платформу из User-Agent
    if "Windows" in user_agent:
        accept_language = "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        sec_ch_ua = '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'
        sec_ch_ua_platform = '"Windows"'
    elif "Macintosh" in user_agent:
        accept_language = "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        sec_ch_ua = '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'
        sec_ch_ua_platform = '"macOS"'
    else:
        accept_language = "en-US,en;q=0.9,ru;q=0.8"
        sec_ch_ua = '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'
        sec_ch_ua_platform = '"Linux"'
    
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://steamcommunity.com",
        "Referer": "https://steamcommunity.com/market/search?appid=730",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-CH-UA": sec_ch_ua,
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": sec_ch_ua_platform,
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
    }


async def test_steam_request_curl_cffi(
    item_name: str = "AK-47 | Redline",
    proxy: Optional[str] = None,
):
    """
    Тестирует запрос с использованием curl_cffi (более реалистичная имитация браузера).
    
    Args:
        item_name: Название предмета для поиска
        proxy: Прокси в формате "http://user:pass@host:port" или None
    """
    if not CURL_CFFI_AVAILABLE:
        print("❌ curl_cffi не установлен")
        return None
    
    print("=" * 80)
    print(f"🧪 Тест запроса с curl_cffi (реалистичная имитация браузера)")
    print("=" * 80)
    print(f"📦 Предмет: {item_name}")
    print(f"🌐 Прокси: {proxy if proxy else 'Нет (прямое подключение)'}")
    print()
    
    params = {
        "query": item_name,
        "start": 0,
        "count": 10,
        "search_descriptions": 0,
        "sort_column": "price",
        "sort_dir": "asc",
        "appid": 730,
        "currency": 1,
        "norender": 1,
        "language": "russian"
    }
    
    url = "https://steamcommunity.com/market/search/render/"
    
    # curl_cffi автоматически использует реалистичные заголовки
    # Можно указать конкретный браузер для имитации
    browsers = ["chrome131", "chrome130", "edge131", "safari17"]
    browser = random.choice(browsers)
    
    print(f"🌐 Имитация браузера: {browser}")
    print()
    
    try:
        proxies = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}
            print(f"🔗 Используем прокси: {proxy[:50]}...")
        else:
            print("🔗 Прямое подключение (без прокси)")
        
        print()
        print(f"📡 Отправка запроса к: {url}")
        print(f"📋 Параметры: {json.dumps(params, ensure_ascii=False, indent=2)}")
        print()
        
        start_time = datetime.now()
        response = curl_requests.get(
            url,
            params=params,
            proxies=proxies,
            impersonate=browser,  # Имитация конкретного браузера
            timeout=30
        )
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"📥 Получен ответ за {elapsed:.2f} сек")
        print(f"   Status Code: {response.status_code}")
        print()
        
        if response.status_code == 429:
            print("❌ ОШИБКА 429: Too Many Requests")
            return None
        
        if response.status_code != 200:
            print(f"❌ ОШИБКА: Status Code {response.status_code}")
            return None
        
        data = response.json()
        print("✅ Успешный ответ!")
        print()
        print("📊 Данные ответа:")
        print(f"   success: {data.get('success')}")
        print(f"   total_count: {data.get('total_count', 0)}")
        print(f"   results: {len(data.get('results', []))} предметов")
        
        return data
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_steam_request(
    item_name: str = "AK-47 | Redline",
    proxy: Optional[str] = None,
    use_realistic_headers: bool = True
):
    """
    Тестирует запрос к Steam Market API.
    
    Args:
        item_name: Название предмета для поиска
        proxy: Прокси в формате "http://user:pass@host:port" или None
        use_realistic_headers: Использовать реалистичные заголовки
    """
    print("=" * 80)
    print(f"🧪 Тест запроса к Steam Market API")
    print("=" * 80)
    print(f"📦 Предмет: {item_name}")
    print(f"🌐 Прокси: {proxy if proxy else 'Нет (прямое подключение)'}")
    print(f"📋 Заголовки: {'Реалистичные' if use_realistic_headers else 'Стандартные'}")
    print()
    
    # Параметры запроса
    params = {
        "query": item_name,
        "start": 0,
        "count": 10,
        "search_descriptions": 0,
        "sort_column": "price",
        "sort_dir": "asc",
        "appid": 730,
        "currency": 1,
        "norender": 1,
        "language": "russian"
    }
    
    url = "https://steamcommunity.com/market/search/render/"
    
    # Заголовки
    if use_realistic_headers:
        headers = get_realistic_chrome_headers()
    else:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://steamcommunity.com/market/",
        }
    
    print("📤 Заголовки запроса:")
    for key, value in headers.items():
        print(f"   {key}: {value[:80] if len(str(value)) > 80 else value}")
    print()
    
    # Создаем клиент
    client_kwargs = {
        "timeout": 30.0,
        "headers": headers,
        "follow_redirects": True,
    }
    
    if proxy:
        client_kwargs["proxy"] = proxy
        print(f"🔗 Используем прокси: {proxy[:50]}...")
    else:
        print("🔗 Прямое подключение (без прокси)")
    
    print()
    
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            print(f"📡 Отправка запроса к: {url}")
            print(f"📋 Параметры: {json.dumps(params, ensure_ascii=False, indent=2)}")
            print()
            
            start_time = datetime.now()
            response = await client.get(url, params=params)
            elapsed = (datetime.now() - start_time).total_seconds()
            
            print(f"📥 Получен ответ за {elapsed:.2f} сек")
            print(f"   Status Code: {response.status_code}")
            print(f"   Headers ответа:")
            for key, value in response.headers.items():
                if key.lower() in ['content-type', 'content-length', 'date', 'server', 'x-steam-error']:
                    print(f"      {key}: {value}")
            print()
            
            if response.status_code == 429:
                print("❌ ОШИБКА 429: Too Many Requests")
                print("   Steam заблокировал запрос")
                if "Retry-After" in response.headers:
                    print(f"   Retry-After: {response.headers['Retry-After']} сек")
                print()
                print("💡 Рекомендации:")
                print("   1. Используйте прокси")
                print("   2. Увеличьте задержку между запросами")
                print("   3. Попробуйте другой User-Agent")
                return None
            
            if response.status_code != 200:
                print(f"❌ ОШИБКА: Status Code {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return None
            
            # Парсим JSON
            try:
                data = response.json()
                print("✅ Успешный ответ!")
                print()
                print("📊 Данные ответа:")
                print(f"   success: {data.get('success')}")
                print(f"   total_count: {data.get('total_count', 0)}")
                print(f"   results: {len(data.get('results', []))} предметов")
                print()
                
                if data.get('results'):
                    print("📦 Первые предметы:")
                    for idx, item in enumerate(data.get('results', [])[:3], 1):
                        name = item.get('asset_description', {}).get('market_hash_name', 'Unknown')
                        price = item.get('sell_price_text', 'N/A')
                        print(f"   {idx}. {name} - {price}")
                
                return data
                
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка парсинга JSON: {e}")
                print(f"   Response text: {response.text[:500]}")
                return None
                
    except httpx.ProxyError as e:
        print(f"❌ Ошибка прокси: {e}")
        return None
    except httpx.TimeoutException:
        print(f"❌ Таймаут запроса (>30 сек)")
        return None
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_multiple_approaches(item_name: str = "AK-47 | Redline", proxy: Optional[str] = None):
    """Тестирует несколько подходов к запросу."""
    print("\n" + "=" * 80)
    print("🧪 ТЕСТИРОВАНИЕ РАЗНЫХ ПОДХОДОВ")
    print("=" * 80 + "\n")
    
    # Тест 1: Реалистичные заголовки
    print("📋 Тест 1: Реалистичные заголовки Chrome")
    print("-" * 80)
    result1 = await test_steam_request(item_name, proxy, use_realistic_headers=True)
    await asyncio.sleep(2)
    
    # Тест 2: Стандартные заголовки
    print("\n📋 Тест 2: Стандартные заголовки")
    print("-" * 80)
    result2 = await test_steam_request(item_name, proxy, use_realistic_headers=False)
    await asyncio.sleep(2)
    
    # Тест 3: Другой User-Agent
    print("\n📋 Тест 3: Firefox User-Agent")
    print("-" * 80)
    # Можно добавить еще тесты
    
    print("\n" + "=" * 80)
    print("📊 ИТОГИ ТЕСТИРОВАНИЯ")
    print("=" * 80)
    print(f"Тест 1 (Реалистичные заголовки): {'✅ Успех' if result1 else '❌ Ошибка'}")
    print(f"Тест 2 (Стандартные заголовки): {'✅ Успех' if result2 else '❌ Ошибка'}")


async def main():
    """Главная функция."""
    import sys
    
    # Прокси из аргументов или используем один из ваших
    proxy = None
    if len(sys.argv) > 1:
        proxy = sys.argv[1]
    else:
        # Используем один из ваших прокси для теста
        proxy = "http://7cVXb8:m3jJpg7o30@185.181.244.74:5500"
        print("💡 Используется прокси по умолчанию")
        print("   Для использования другого прокси: python test_steam_request.py 'http://user:pass@host:port'")
        print()
    
    item_name = "AK-47 | Redline"
    
    # Тест 1: httpx с реалистичными заголовками
    print("\n" + "=" * 80)
    print("ТЕСТ 1: httpx с реалистичными заголовками")
    print("=" * 80)
    result1 = await test_steam_request(item_name, proxy, use_realistic_headers=True)
    await asyncio.sleep(2)
    
    # Тест 2: curl_cffi (если доступен)
    if CURL_CFFI_AVAILABLE:
        print("\n" + "=" * 80)
        print("ТЕСТ 2: curl_cffi (реалистичная имитация браузера)")
        print("=" * 80)
        result2 = await test_steam_request_curl_cffi(item_name, proxy)
        await asyncio.sleep(2)
    else:
        result2 = None
        print("\n💡 curl_cffi не установлен, пропускаем тест с curl_cffi")
    
    # Итоги
    print("\n" + "=" * 80)
    print("📊 ИТОГИ ТЕСТИРОВАНИЯ")
    print("=" * 80)
    print(f"httpx с реалистичными заголовками: {'✅ Успех' if result1 else '❌ Ошибка'}")
    if CURL_CFFI_AVAILABLE:
        print(f"curl_cffi (имитация браузера): {'✅ Успех' if result2 else '❌ Ошибка'}")


if __name__ == "__main__":
    asyncio.run(main())

