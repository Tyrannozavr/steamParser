#!/usr/bin/env python3
"""
Скрипт для проверки всех прокси.
"""
import asyncio
import sys
from pathlib import Path
import httpx

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from services import ProxyManager
from core.config import Config
from loguru import logger
from sqlalchemy import select


async def check_proxy(proxy: Proxy, timeout: int = 10) -> dict:
    """Проверяет один прокси."""
    try:
        async with httpx.AsyncClient(proxy=proxy.url, timeout=timeout) as client:
            # Пробуем простой запрос к Google
            response = await client.get("https://www.google.com", follow_redirects=True)
            if response.status_code == 200:
                return {"status": "ok", "error": None}
            else:
                return {"status": "error", "error": f"HTTP {response.status_code}"}
    except httpx.ProxyError as e:
        return {"status": "error", "error": f"Proxy error: {str(e)[:100]}"}
    except httpx.TimeoutException:
        return {"status": "error", "error": "Timeout"}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}


async def main():
    """Основная функция."""
    logger.info("🔍 Начинаем проверку всех прокси...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        proxy_manager = ProxyManager(session, redis_service=None)
        
        # Получаем все прокси
        result = await session.execute(
            select(Proxy).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        logger.info(f"📋 Всего прокси в БД: {len(all_proxies)}")
        logger.info("=" * 70)
        
        # Проверяем каждый прокси
        results = []
        for proxy in all_proxies:
            logger.info(f"🔍 Проверяем прокси ID={proxy.id}: {proxy.url[:50]}...")
            result = await check_proxy(proxy)
            results.append({
                "proxy": proxy,
                "check": result
            })
            if result["status"] == "ok":
                logger.info(f"   ✅ Прокси ID={proxy.id} работает")
            else:
                logger.warning(f"   ❌ Прокси ID={proxy.id} не работает: {result['error']}")
            # Небольшая задержка между проверками
            await asyncio.sleep(0.5)
        
        # Выводим статистику
        logger.info("=" * 70)
        logger.info("📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ:")
        logger.info("=" * 70)
        
        active_ok = sum(1 for r in results if r["proxy"].is_active and r["check"]["status"] == "ok")
        active_error = sum(1 for r in results if r["proxy"].is_active and r["check"]["status"] == "error")
        inactive_ok = sum(1 for r in results if not r["proxy"].is_active and r["check"]["status"] == "ok")
        inactive_error = sum(1 for r in results if not r["proxy"].is_active and r["check"]["status"] == "error")
        
        logger.info(f"📋 Всего прокси: {len(all_proxies)}")
        logger.info(f"✅ Активных и работающих: {active_ok}")
        logger.info(f"❌ Активных, но не работающих: {active_error}")
        logger.info(f"✅ Неактивных, но работающих: {inactive_ok}")
        logger.info(f"❌ Неактивных и не работающих: {inactive_error}")
        
        # Список неработающих активных прокси
        if active_error > 0:
            logger.info("\n❌ Активные прокси, которые не работают:")
            for r in results:
                if r["proxy"].is_active and r["check"]["status"] == "error":
                    logger.warning(f"   ID={r['proxy'].id}: {r['check']['error']}")
        
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

