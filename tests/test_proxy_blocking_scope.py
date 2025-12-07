"""
Тест для проверки: если прокси получил 429 на search/render, 
будет ли он заблокирован для listings/render?
"""
import asyncio
import httpx
import sys
from pathlib import Path
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))

from core import DatabaseManager, Config, Proxy
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>", level="INFO")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://steamcommunity.com/market/",
    "Origin": "https://steamcommunity.com",
}

async def test_proxy_blocking_scope():
    """Тестирует, блокируется ли прокси по IP или по эндпоинту."""
    logger.info("🧪 Тест: Блокировка прокси по IP или по эндпоинту?")
    logger.info("="*80)
    
    # Подключение к БД
    database_url = Config.DATABASE_URL
    if "localhost" in database_url or "127.0.0.1" in database_url:
        database_url = database_url.replace("localhost", "127.0.0.1")
    
    db_manager = DatabaseManager(database_url)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        
        # Получаем активные прокси
        result = await session.execute(
            select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        if len(all_proxies) == 0:
            logger.error("❌ Нет активных прокси в базе данных")
            return
        
        # Берем первый прокси
        test_proxy = all_proxies[0]
        logger.info(f"✅ Используем прокси ID={test_proxy.id}: {test_proxy.url[:60]}...")
        
        # URL для тестирования
        search_url = "https://steamcommunity.com/market/search/render/"
        search_params = {
            "query": "AK-47",
            "appid": 730,
            "start": 0,
            "count": 1,
            "norender": 1
        }
        
        listings_url = "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20%28Field-Tested%29/render/"
        listings_params = {
            "query": "",
            "start": 0,
            "count": 1,
            "country": "US",
            "language": "english",
            "currency": 1
        }
        
        async with httpx.AsyncClient(
            proxy=test_proxy.url,
            timeout=15.0,
            headers=HEADERS,
            follow_redirects=True
        ) as client:
            
            # ШАГ 1: Делаем запрос к search/render до получения 429
            logger.info("\n" + "="*80)
            logger.info("ШАГ 1: Делаем запросы к search/render до получения 429...")
            logger.info("="*80)
            
            search_429_received = False
            search_requests = 0
            
            for i in range(1, 21):  # До 20 запросов
                try:
                    response = await client.get(search_url, params=search_params, headers=HEADERS)
                    search_requests += 1
                    
                    if response.status_code == 200:
                        logger.info(f"   Запрос {i}: ✅ 200 OK")
                    elif response.status_code == 429:
                        logger.warning(f"   Запрос {i}: 🚫 429 Too Many Requests")
                        search_429_received = True
                        break
                    else:
                        logger.error(f"   Запрос {i}: ❌ {response.status_code}")
                        break
                    
                    # Задержка 0.5 сек между запросами
                    if i < 20:
                        await asyncio.sleep(0.5)
                        
                except Exception as e:
                    logger.error(f"   Запрос {i}: ❌ Ошибка: {e}")
                    break
            
            logger.info(f"\n📊 Результат: Сделано {search_requests} запросов к search/render")
            if search_429_received:
                logger.warning(f"   ⚠️ Прокси получил 429 на search/render")
            else:
                logger.info(f"   ✅ Прокси не получил 429 на search/render (сделано {search_requests} запросов)")
            
            # ШАГ 2: Сразу после 429 (или после всех запросов) делаем запрос к listings/render
            logger.info("\n" + "="*80)
            logger.info("ШАГ 2: Делаем запрос к listings/render (сразу после search/render)...")
            logger.info("="*80)
            
            # Небольшая задержка перед проверкой listings
            await asyncio.sleep(1.0)
            
            try:
                response = await client.get(listings_url, params=listings_params, headers=HEADERS)
                
                if response.status_code == 200:
                    logger.info(f"   ✅ listings/render: 200 OK - Прокси НЕ заблокирован для listings!")
                    logger.info(f"   💡 Вывод: Блокировка по ЭНДПОИНТУ, а не по IP")
                elif response.status_code == 429:
                    logger.warning(f"   🚫 listings/render: 429 Too Many Requests - Прокси заблокирован и для listings!")
                    logger.warning(f"   💡 Вывод: Блокировка по IP (все эндпоинты заблокированы)")
                else:
                    logger.error(f"   ❌ listings/render: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"   ❌ Ошибка при запросе к listings/render: {e}")
            
            # ШАГ 3: Делаем еще несколько запросов к listings/render для проверки
            logger.info("\n" + "="*80)
            logger.info("ШАГ 3: Делаем еще 5 запросов к listings/render для проверки...")
            logger.info("="*80)
            
            listings_success = 0
            listings_429 = 0
            
            for i in range(1, 6):
                try:
                    await asyncio.sleep(0.5)  # Задержка 0.5 сек
                    response = await client.get(listings_url, params=listings_params, headers=HEADERS)
                    
                    if response.status_code == 200:
                        listings_success += 1
                        logger.info(f"   Запрос {i}/5: ✅ 200 OK")
                    elif response.status_code == 429:
                        listings_429 += 1
                        logger.warning(f"   Запрос {i}/5: 🚫 429 Too Many Requests")
                    else:
                        logger.error(f"   Запрос {i}/5: ❌ {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"   Запрос {i}/5: ❌ Ошибка: {e}")
            
            logger.info(f"\n📊 Результат listings/render: {listings_success} успешных, {listings_429} с 429")
            
            # Финальный вывод
            logger.info("\n" + "="*80)
            logger.info("📊 ФИНАЛЬНЫЙ ВЫВОД")
            logger.info("="*80)
            
            if search_429_received:
                if listings_429 > 0:
                    logger.warning("🚫 БЛОКИРОВКА ПО IP: Прокси заблокирован для ВСЕХ эндпоинтов")
                    logger.warning("   Если прокси получил 429 на search/render, он также заблокирован для listings/render")
                else:
                    logger.info("✅ БЛОКИРОВКА ПО ЭНДПОИНТУ: Прокси заблокирован только для search/render")
                    logger.info("   Прокси может работать с listings/render даже после 429 на search/render")
            else:
                logger.info("ℹ️ Прокси не получил 429 на search/render, тест неполный")
                if listings_success > 0:
                    logger.info("   ✅ listings/render работает нормально")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(test_proxy_blocking_scope())

