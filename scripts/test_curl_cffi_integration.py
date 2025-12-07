#!/usr/bin/env python3
"""
Скрипт для тестирования интеграции curl_cffi в основной код.
Проверяет, работает ли curl_cffi лучше чем httpx для обхода 429.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from sqlalchemy import select
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_curl_cffi_vs_httpx(proxy_url: str):
    """Сравнивает curl_cffi и httpx на одном прокси."""
    import httpx
    from curl_cffi import requests as curl_requests
    import random
    
    logger.info("=" * 70)
    logger.info("🔬 СРАВНЕНИЕ curl_cffi vs httpx")
    logger.info("=" * 70)
    logger.info(f"📋 Прокси: {proxy_url[:50]}...")
    logger.info("")
    
    params = {
        "query": "AK-47 | Redline",
        "appid": 730,
        "start": 0,
        "count": 10
    }
    url = "https://steamcommunity.com/market/search/render/"
    
    # Тест 1: httpx
    logger.info("🧪 ТЕСТ 1: httpx с реалистичными заголовками")
    try:
        from core.steam_parser_constants import get_random_user_agent, get_browser_headers
        user_agent = get_random_user_agent()
        headers = get_browser_headers(user_agent)
        
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=10,
            headers=headers,
            follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            logger.info(f"   Статус: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"   ✅ httpx: Успешно (total={data.get('total_count', 0)})")
                httpx_success = True
            elif response.status_code == 429:
                logger.warning(f"   ❌ httpx: 429 (Too Many Requests)")
                httpx_success = False
            else:
                logger.warning(f"   ❌ httpx: HTTP {response.status_code}")
                httpx_success = False
    except Exception as e:
        logger.error(f"   ❌ httpx: Ошибка - {e}")
        httpx_success = False
    
    await asyncio.sleep(5)  # Задержка между тестами
    
    # Тест 2: curl_cffi
    logger.info("")
    logger.info("🧪 ТЕСТ 2: curl_cffi с TLS fingerprint имитацией")
    try:
        # curl_cffi поддерживает: chrome110, chrome107, chrome104, chrome99, edge99, safari15_3, safari15_5
        browsers = ["chrome110", "chrome107", "edge99", "safari15_5"]
        browser = random.choice(browsers)
        logger.info(f"   Имитация браузера: {browser}")
        
        response = curl_requests.get(
            url,
            params=params,
            proxy=proxy_url,
            timeout=10,
            impersonate=browser
        )
        
        logger.info(f"   Статус: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"   ✅ curl_cffi: Успешно (total={data.get('total_count', 0)})")
            curl_success = True
        elif response.status_code == 429:
            logger.warning(f"   ❌ curl_cffi: 429 (Too Many Requests)")
            curl_success = False
        else:
            logger.warning(f"   ❌ curl_cffi: HTTP {response.status_code}")
            curl_success = False
    except Exception as e:
        logger.error(f"   ❌ curl_cffi: Ошибка - {e}")
        curl_success = False
    
    # Результаты
    logger.info("")
    logger.info("=" * 70)
    logger.info("📊 РЕЗУЛЬТАТЫ:")
    logger.info("=" * 70)
    logger.info(f"   httpx: {'✅ Успешно' if httpx_success else '❌ 429 или ошибка'}")
    logger.info(f"   curl_cffi: {'✅ Успешно' if curl_success else '❌ 429 или ошибка'}")
    
    if curl_success and not httpx_success:
        logger.info("")
        logger.info("💡 РЕКОМЕНДАЦИЯ: curl_cffi работает лучше! Рекомендуется использовать его вместо httpx")
    elif httpx_success and not curl_success:
        logger.info("")
        logger.info("💡 РЕКОМЕНДАЦИЯ: httpx работает лучше. Оставляем текущий подход")
    elif curl_success and httpx_success:
        logger.info("")
        logger.info("💡 ОБА метода работают. curl_cffi может быть более стабильным для обхода блокировок")
    else:
        logger.warning("")
        logger.warning("⚠️ ОБА метода получили 429. Прокси может быть заблокирован Steam")
    
    return curl_success, httpx_success


async def main():
    """Основная функция."""
    logger.info("🔍 Тестируем curl_cffi vs httpx...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Получаем активный прокси
        result = await session.execute(
            select(Proxy).where(Proxy.is_active == True).order_by(Proxy.success_count.desc()).limit(1)
        )
        proxy = result.scalar_one_or_none()
        
        if not proxy:
            logger.error("❌ Нет активных прокси")
            return
        
        await test_curl_cffi_vs_httpx(proxy.url)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

