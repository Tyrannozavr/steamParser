#!/usr/bin/env python3
"""
Скрипт для тестирования различных методов защиты от 429 ошибок.
Пробует разные библиотеки и подходы для обхода блокировок Steam.
"""
import asyncio
import sys
import time
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from sqlalchemy import select
from core.config import Config
from loguru import logger
import httpx

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_method_1_httpx_basic(proxy_url: str):
    """Метод 1: Базовый httpx с простыми заголовками."""
    logger.info("=" * 70)
    logger.info("🧪 МЕТОД 1: httpx с базовыми заголовками")
    logger.info("=" * 70)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://steamcommunity.com/market/search?appid=730"
    }
    
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=10, headers=headers) as client:
            response = await client.get(
                "https://steamcommunity.com/market/search/render/",
                params={"query": "AK-47", "appid": 730, "start": 0, "count": 10}
            )
            logger.info(f"   Статус: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"   ✅ Успешно: success={data.get('success')}, total={data.get('total_count', 0)}")
                return True
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "не указан")
                logger.warning(f"   ❌ 429: Retry-After={retry_after}")
                return False
            else:
                logger.warning(f"   ❌ HTTP {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False


async def test_method_2_httpx_realistic(proxy_url: str):
    """Метод 2: httpx с реалистичными заголовками (как в текущем коде)."""
    logger.info("=" * 70)
    logger.info("🧪 МЕТОД 2: httpx с реалистичными заголовками (текущий подход)")
    logger.info("=" * 70)
    
    from core.steam_parser_constants import get_random_user_agent, get_browser_headers
    
    user_agent = get_random_user_agent()
    headers = get_browser_headers(user_agent)
    
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=10,
            headers=headers,
            follow_redirects=True,
            cookies={}
        ) as client:
            response = await client.get(
                "https://steamcommunity.com/market/search/render/",
                params={"query": "AK-47", "appid": 730, "start": 0, "count": 10}
            )
            logger.info(f"   Статус: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"   ✅ Успешно: success={data.get('success')}, total={data.get('total_count', 0)}")
                return True
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "не указан")
                logger.warning(f"   ❌ 429: Retry-After={retry_after}")
                return False
            else:
                logger.warning(f"   ❌ HTTP {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False


async def test_method_3_httpx_with_delay(proxy_url: str):
    """Метод 3: httpx с задержкой перед запросом."""
    logger.info("=" * 70)
    logger.info("🧪 МЕТОД 3: httpx с задержкой 5 сек перед запросом")
    logger.info("=" * 70)
    
    await asyncio.sleep(5)  # Задержка перед запросом
    
    from core.steam_parser_constants import get_random_user_agent, get_browser_headers
    
    user_agent = get_random_user_agent()
    headers = get_browser_headers(user_agent)
    
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=10,
            headers=headers,
            follow_redirects=True,
            cookies={}
        ) as client:
            response = await client.get(
                "https://steamcommunity.com/market/search/render/",
                params={"query": "AK-47", "appid": 730, "start": 0, "count": 10}
            )
            logger.info(f"   Статус: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"   ✅ Успешно: success={data.get('success')}, total={data.get('total_count', 0)}")
                return True
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "не указан")
                logger.warning(f"   ❌ 429: Retry-After={retry_after}")
                return False
            else:
                logger.warning(f"   ❌ HTTP {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False


async def test_method_4_curl_cffi(proxy_url: str):
    """Метод 4: curl_cffi (имитация реального браузера с TLS fingerprint)."""
    logger.info("=" * 70)
    logger.info("🧪 МЕТОД 4: curl_cffi (TLS fingerprint имитация)")
    logger.info("=" * 70)
    
    try:
        from curl_cffi import requests
        
        # curl_cffi имитирует реальный браузер, включая TLS fingerprint
        response = requests.get(
            "https://steamcommunity.com/market/search/render/",
            params={"query": "AK-47", "appid": 730, "start": 0, "count": 10},
            proxy=proxy_url,
            timeout=10,
            impersonate="chrome110"  # Имитация Chrome 110 (поддерживаемая версия)
        )
        
        logger.info(f"   Статус: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"   ✅ Успешно: success={data.get('success')}, total={data.get('total_count', 0)}")
            return True
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "не указан")
            logger.warning(f"   ❌ 429: Retry-After={retry_after}")
            return False
        else:
            logger.warning(f"   ❌ HTTP {response.status_code}")
            return False
    except ImportError:
        logger.warning("   ⚠️ curl_cffi не установлен. Установите: pip install curl_cffi")
        return None
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False


async def test_method_5_playwright(proxy_url: str):
    """Метод 5: Playwright (реальный браузер)."""
    logger.info("=" * 70)
    logger.info("🧪 МЕТОД 5: Playwright (реальный браузер Chromium)")
    logger.info("=" * 70)
    
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            # Запускаем браузер с прокси
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                proxy={"server": proxy_url},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Делаем запрос через браузер
            url = "https://steamcommunity.com/market/search/render/?query=AK-47&appid=730&start=0&count=10"
            response = await page.goto(url, wait_until="networkidle")
            
            logger.info(f"   Статус: {response.status if response else 'None'}")
            if response and response.status == 200:
                content = await page.content()
                logger.info(f"   ✅ Успешно: получен ответ (размер: {len(content)} байт)")
                await browser.close()
                return True
            elif response and response.status == 429:
                logger.warning(f"   ❌ 429: Too Many Requests")
                await browser.close()
                return False
            else:
                logger.warning(f"   ❌ HTTP {response.status if response else 'None'}")
                await browser.close()
                return False
    except ImportError:
        logger.warning("   ⚠️ Playwright не установлен. Установите: pip install playwright && playwright install chromium")
        return None
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False


async def test_method_6_httpx_with_session(proxy_url: str):
    """Метод 6: httpx с сессией (cookies, как реальный браузер)."""
    logger.info("=" * 70)
    logger.info("🧪 МЕТОД 6: httpx с сессией и cookies")
    logger.info("=" * 70)
    
    from core.steam_parser_constants import get_random_user_agent, get_browser_headers
    
    user_agent = get_random_user_agent()
    headers = get_browser_headers(user_agent)
    
    try:
        # Сначала заходим на главную страницу для получения cookies
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=10,
            headers=headers,
            follow_redirects=True
        ) as client:
            # Получаем cookies с главной страницы
            logger.info("   📥 Получаем cookies с главной страницы...")
            main_response = await client.get("https://steamcommunity.com/market/search?appid=730")
            logger.info(f"   Главная страница: {main_response.status_code}")
            
            # Используем те же cookies для API запроса
            await asyncio.sleep(2)  # Небольшая задержка
            
            response = await client.get(
                "https://steamcommunity.com/market/search/render/",
                params={"query": "AK-47", "appid": 730, "start": 0, "count": 10}
            )
            logger.info(f"   Статус: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"   ✅ Успешно: success={data.get('success')}, total={data.get('total_count', 0)}")
                return True
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "не указан")
                logger.warning(f"   ❌ 429: Retry-After={retry_after}")
                return False
            else:
                logger.warning(f"   ❌ HTTP {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False


async def main():
    """Основная функция."""
    logger.info("🔍 Тестируем различные методы защиты от 429 ошибок...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Получаем прокси с 429 ошибками (неактивные)
        result = await session.execute(
            select(Proxy).where(Proxy.is_active == False).order_by(Proxy.fail_count.desc())
        )
        blocked_proxies = list(result.scalars().all())
        
        if not blocked_proxies:
            logger.warning("⚠️ Нет заблокированных прокси для тестирования")
            # Берем любой прокси
            result = await session.execute(select(Proxy).limit(1))
            blocked_proxies = list(result.scalars().all())
        
        if not blocked_proxies:
            logger.error("❌ Нет прокси в базе данных")
            return
        
        test_proxy = blocked_proxies[0]
        logger.info(f"📋 Используем прокси для тестирования: ID={test_proxy.id}")
        logger.info(f"   URL: {test_proxy.url[:50]}...")
        logger.info(f"   Статистика: успешно={test_proxy.success_count}, ошибок={test_proxy.fail_count}")
        logger.info("")
        
        # Тестируем разные методы
        results = {}
        
        # Метод 1: Базовый httpx
        results["Метод 1: httpx базовый"] = await test_method_1_httpx_basic(test_proxy.url)
        await asyncio.sleep(3)
        
        # Метод 2: httpx с реалистичными заголовками
        results["Метод 2: httpx реалистичные заголовки"] = await test_method_2_httpx_realistic(test_proxy.url)
        await asyncio.sleep(3)
        
        # Метод 3: httpx с задержкой
        results["Метод 3: httpx с задержкой"] = await test_method_3_httpx_with_delay(test_proxy.url)
        await asyncio.sleep(3)
        
        # Метод 4: curl_cffi
        results["Метод 4: curl_cffi"] = await test_method_4_curl_cffi(test_proxy.url)
        await asyncio.sleep(3)
        
        # Метод 5: Playwright
        results["Метод 5: Playwright"] = await test_method_5_playwright(test_proxy.url)
        await asyncio.sleep(3)
        
        # Метод 6: httpx с сессией
        results["Метод 6: httpx с сессией"] = await test_method_6_httpx_with_session(test_proxy.url)
        
        # Выводим результаты
        logger.info("")
        logger.info("=" * 70)
        logger.info("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
        logger.info("=" * 70)
        for method, result in results.items():
            if result is None:
                logger.info(f"   {method}: ⚠️ Не установлен")
            elif result:
                logger.info(f"   {method}: ✅ Успешно")
            else:
                logger.info(f"   {method}: ❌ 429 или ошибка")
        logger.info("=" * 70)
        
        # Рекомендации
        successful_methods = [m for m, r in results.items() if r is True]
        if successful_methods:
            logger.info(f"\n💡 РЕКОМЕНДАЦИИ:")
            logger.info(f"   ✅ Работающие методы: {', '.join(successful_methods)}")
            logger.info(f"   Рекомендуется использовать один из этих методов для улучшения защиты от 429")
        else:
            logger.warning(f"\n⚠️ ВНИМАНИЕ:")
            logger.warning(f"   Все методы получили 429 ошибку")
            logger.warning(f"   Возможно, прокси действительно заблокирован Steam")
            logger.warning(f"   Рекомендуется подождать или использовать другой прокси")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

