#!/usr/bin/env python3
"""
Скрипт для ручной проверки всех прокси.
Проверяет доступность прокси через реальные HTTP запросы.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from services import ProxyManager
from core.config import Config
from loguru import logger
from sqlalchemy import select
import httpx

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def check_proxy_httpbin(proxy_url: str, timeout: int = 10) -> dict:
    """Проверяет прокси через httpbin.org."""
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout) as client:
            response = await client.get("http://httpbin.org/ip")
            response.raise_for_status()
            data = response.json()
            return {
                "status": "working",
                "ip": data.get("origin", "unknown"),
                "proxy_url": proxy_url[:50] + "..." if len(proxy_url) > 50 else proxy_url
            }
    except httpx.TimeoutException:
        return {"status": "timeout", "error": "Timeout"}
    except httpx.ProxyError as e:
        return {"status": "proxy_error", "error": str(e)[:100]}
    except httpx.HTTPStatusError as e:
        return {"status": "http_error", "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}


async def check_proxy_steam(proxy_url: str, timeout: int = 10) -> dict:
    """Проверяет прокси через запрос к Steam Market API."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout, headers=headers) as client:
            # Простой запрос к Steam Market API
            response = await client.get(
                "https://steamcommunity.com/market/search/render/",
                params={"query": "AK-47", "appid": 730, "start": 0, "count": 1}
            )
            if response.status_code == 200:
                return {"status": "working", "steam_status": "ok"}
            elif response.status_code == 429:
                return {"status": "rate_limited", "steam_status": "429 Too Many Requests"}
            else:
                return {"status": "http_error", "steam_status": f"HTTP {response.status_code}"}
    except httpx.TimeoutException:
        return {"status": "timeout", "error": "Timeout"}
    except httpx.ProxyError as e:
        return {"status": "proxy_error", "error": str(e)[:100]}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}


async def main():
    """Основная функция."""
    logger.info("🔍 Начинаем ручную проверку всех прокси...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Получаем все прокси
        result = await session.execute(
            select(Proxy).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        logger.info(f"📋 Всего прокси в БД: {len(all_proxies)}")
        logger.info("=" * 70)
        
        working_httpbin = 0
        working_steam = 0
        blocked_httpbin = 0
        blocked_steam = 0
        rate_limited = 0
        
        for proxy in all_proxies:
            logger.info(f"\n🔍 Проверяем прокси ID={proxy.id}: {proxy.url[:50]}...")
            logger.info(f"   Статус в БД: {'✅ Активен' if proxy.is_active else '❌ Заблокирован'}")
            logger.info(f"   Статистика: успешно={proxy.success_count}, ошибок={proxy.fail_count}")
            logger.info(f"   Задержка: {proxy.delay_seconds}с")
            
            # Проверка через httpbin
            logger.info(f"   📡 Проверка через httpbin.org...")
            httpbin_result = await check_proxy_httpbin(proxy.url, timeout=10)
            if httpbin_result["status"] == "working":
                working_httpbin += 1
                logger.info(f"   ✅ httpbin: работает (IP: {httpbin_result.get('ip', 'unknown')})")
            else:
                blocked_httpbin += 1
                logger.info(f"   ❌ httpbin: {httpbin_result['status']} - {httpbin_result.get('error', 'unknown')}")
            
            # Небольшая задержка между проверками
            await asyncio.sleep(1)
            
            # Проверка через Steam
            logger.info(f"   📡 Проверка через Steam Market API...")
            steam_result = await check_proxy_steam(proxy.url, timeout=10)
            if steam_result["status"] == "working":
                working_steam += 1
                logger.info(f"   ✅ Steam: работает")
            elif steam_result["status"] == "rate_limited":
                rate_limited += 1
                logger.info(f"   ⚠️ Steam: rate limited (429) - прокси работает, но Steam ограничивает")
            else:
                blocked_steam += 1
                logger.info(f"   ❌ Steam: {steam_result['status']} - {steam_result.get('error', 'unknown')}")
            
            # Задержка между прокси
            await asyncio.sleep(2)
        
        logger.info("\n" + "=" * 70)
        logger.info("📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ:")
        logger.info("=" * 70)
        logger.info(f"📋 Всего прокси: {len(all_proxies)}")
        logger.info(f"✅ Работают через httpbin: {working_httpbin}")
        logger.info(f"❌ Не работают через httpbin: {blocked_httpbin}")
        logger.info(f"✅ Работают через Steam: {working_steam}")
        logger.info(f"⚠️ Rate limited через Steam (429): {rate_limited}")
        logger.info(f"❌ Не работают через Steam: {blocked_steam}")
        logger.info("=" * 70)
        
        # Анализ
        if working_steam > 0 or rate_limited > 0:
            logger.info(f"\n💡 РЕКОМЕНДАЦИИ:")
            logger.info(f"   • {working_steam + rate_limited} прокси работают (или rate limited)")
            logger.info(f"   • Рекомендуется использовать {max(5, (working_steam + rate_limited) * 2)} прокси для стабильной работы")
            logger.info(f"   • При {working_steam + rate_limited} рабочих прокси задержка может быть: {max(2.0, 10.0 / (working_steam + rate_limited)):.1f}с")
        else:
            logger.warning(f"\n⚠️ ВНИМАНИЕ:")
            logger.warning(f"   • Все прокси не работают или заблокированы Steam")
            logger.warning(f"   • Необходимо добавить новые прокси или подождать снятия блокировки")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

