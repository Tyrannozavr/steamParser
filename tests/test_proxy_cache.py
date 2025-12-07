"""
Тестовый скрипт для проверки кэширования прокси в Redis.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from core import Config, DatabaseManager, Proxy
from services import ProxyManager
from services.redis_service import RedisService
from loguru import logger
from sqlalchemy import select

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_proxy_cache():
    """Тестирует кэширование прокси в Redis."""
    logger.info("🧪 Начинаем тестирование кэширования прокси в Redis...")
    
    # Инициализируем БД
    db_manager = DatabaseManager(Config.DATABASE_PATH)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    try:
        await redis_service.connect()
        logger.info("✅ Redis подключен")
    except Exception as e:
        logger.error(f"❌ Не удалось подключиться к Redis: {e}")
        await db_session.close()
        await db_manager.close()
        return
    
    # Инициализируем ProxyManager
    proxy_manager = ProxyManager(db_session, redis_service=redis_service)
    
    # Тест 1: Проверяем, что кэш пуст изначально
    logger.info("\n📋 Тест 1: Проверка пустого кэша")
    cached_proxies = await proxy_manager._get_proxies_from_redis()
    if cached_proxies is None or len(cached_proxies) == 0:
        logger.info("✅ Кэш пуст (ожидаемо)")
    else:
        logger.warning(f"⚠️ Кэш не пуст: {len(cached_proxies)} прокси")
    
    # Тест 2: Добавляем тестовый прокси
    logger.info("\n📋 Тест 2: Добавление тестового прокси")
    test_proxy_url = "http://test:test@test.example.com:8080"
    
    # Удаляем тестовый прокси, если он существует
    result = await db_session.execute(
        select(Proxy).where(Proxy.url == test_proxy_url)
    )
    existing = result.scalar_one_or_none()
    if existing:
        logger.info(f"🗑️ Удаляем существующий тестовый прокси (ID: {existing.id})")
        await db_session.delete(existing)
        await db_session.commit()
    
    # Добавляем новый прокси
    logger.info(f"➕ Добавляем тестовый прокси: {test_proxy_url}")
    proxy = await proxy_manager.add_proxy(test_proxy_url)
    logger.info(f"✅ Прокси добавлен (ID: {proxy.id})")
    
    # Проверяем, что кэш обновился
    logger.info("🔍 Проверяем кэш после добавления...")
    await asyncio.sleep(0.5)  # Небольшая задержка для обновления кэша
    cached_proxies = await proxy_manager._get_proxies_from_redis()
    if cached_proxies and len(cached_proxies) > 0:
        logger.info(f"✅ Кэш обновлен: найдено {len(cached_proxies)} прокси в кэше")
        for p in cached_proxies:
            logger.info(f"   - Прокси ID={p['id']}: {p['url']}")
    else:
        logger.error("❌ Кэш не обновился после добавления прокси!")
    
    # Тест 3: Проверяем чтение из кэша через get_active_proxies
    logger.info("\n📋 Тест 3: Чтение прокси из кэша через get_active_proxies")
    proxies = await proxy_manager.get_active_proxies(force_refresh=False)
    if proxies:
        logger.info(f"✅ Получено {len(proxies)} прокси из кэша")
        for p in proxies:
            logger.info(f"   - Прокси ID={p.id}: {p.url}")
    else:
        logger.error("❌ Не удалось получить прокси из кэша!")
    
    # Тест 4: Проверяем get_next_proxy (должен использовать кэш)
    logger.info("\n📋 Тест 4: Получение следующего прокси (должен использовать кэш)")
    next_proxy = await proxy_manager.get_next_proxy(force_refresh=False)
    if next_proxy:
        logger.info(f"✅ Получен прокси из кэша: ID={next_proxy.id}, URL={next_proxy.url}")
    else:
        logger.error("❌ Не удалось получить прокси!")
    
    # Тест 5: Удаляем прокси и проверяем обновление кэша
    logger.info("\n📋 Тест 5: Удаление прокси и проверка обновления кэша")
    logger.info(f"🗑️ Удаляем прокси ID={proxy.id}")
    await proxy_manager.delete_proxy(proxy.id)
    logger.info("✅ Прокси удален")
    
    # Проверяем, что кэш обновился
    await asyncio.sleep(0.5)  # Небольшая задержка для обновления кэша
    cached_proxies = await proxy_manager._get_proxies_from_redis()
    if cached_proxies is None or len(cached_proxies) == 0:
        logger.info("✅ Кэш обновлен: прокси удален из кэша")
    else:
        logger.warning(f"⚠️ Кэш не обновился: в кэше осталось {len(cached_proxies)} прокси")
    
    # Тест 6: Проверяем принудительное обновление из БД
    logger.info("\n📋 Тест 6: Принудительное обновление из БД (force_refresh=True)")
    proxies = await proxy_manager.get_active_proxies(force_refresh=True)
    logger.info(f"✅ Получено {len(proxies)} прокси из БД (force_refresh)")
    
    # Закрываем соединения
    await redis_service.disconnect()
    await db_session.close()
    await db_manager.close()
    
    logger.info("\n🎉 Тестирование завершено!")


if __name__ == "__main__":
    asyncio.run(test_proxy_cache())

