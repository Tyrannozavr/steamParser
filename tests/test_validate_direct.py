"""
Прямой тест validate_hash_name через Parser API с прокси.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.steam_parser import SteamMarketParser
from core import DatabaseManager, Config
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from loguru import logger

async def test_validate_with_proxy():
    """Тестирует validate_hash_name с прокси"""
    logger.info("=" * 80)
    logger.info("🧪 Тест validate_hash_name с прокси")
    logger.info("=" * 80)
    
    # Инициализация
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        logger.info("✅ Redis подключен")
    
    proxy_manager = ProxyManager(db_session, redis_service=redis_service)
    proxy_manager.start_background_proxy_check()
    logger.info("✅ ProxyManager инициализирован")
    
    # Проверяем активные прокси
    active_proxies = await proxy_manager.get_active_proxies(force_refresh=True)
    logger.info(f"📊 Активных прокси: {len(active_proxies)}")
    if not active_proxies:
        logger.error("❌ Нет активных прокси! Нужно добавить прокси.")
        return
    
    # Создаем парсер с proxy_manager
    parser = SteamMarketParser(redis_service=redis_service, proxy_manager=proxy_manager)
    await parser._ensure_client()
    logger.info("✅ Парсер инициализирован")
    
    # Тестируем один вариант
    test_hash_name = "AK-47 | Redline (Field-Tested)"
    logger.info(f"\n🔍 Тестируем: {test_hash_name}")
    
    is_valid, total_count = await parser.validate_hash_name(appid=730, hash_name=test_hash_name)
    
    logger.info(f"\n📊 Результат:")
    logger.info(f"   is_valid: {is_valid}")
    logger.info(f"   total_count: {total_count}")
    
    if is_valid:
        logger.info(f"✅ Предмет валиден: {total_count} лотов")
    else:
        logger.error(f"❌ Предмет невалиден: total_count={total_count}")
    
    # Закрываем соединения
    await parser.close()
    if redis_service:
        await redis_service.disconnect()
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_validate_with_proxy())

