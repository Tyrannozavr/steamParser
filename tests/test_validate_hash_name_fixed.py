"""
Тест validate_hash_name с count=20 через Parser API.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.config import Config
from core.database import DatabaseManager
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.steam_parser import SteamMarketParser
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

async def test_validate_hash_name():
    """Тестирует validate_hash_name с count=20."""
    logger.info("=" * 80)
    logger.info("🧪 Тест validate_hash_name с count=20")
    logger.info("=" * 80)
    
    try:
        # Инициализация БД
        db_manager = DatabaseManager(Config.DATABASE_URL)
        await db_manager.init_db()
        db_session = await db_manager.get_session()
        
        # Инициализация Redis
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        
        # Инициализация ProxyManager
        proxy_manager = ProxyManager(db_session, redis_service=redis_service)
        await proxy_manager.load_proxies_from_db()
        active_proxies = await proxy_manager.get_active_proxies()
        logger.info(f"📊 Загружено прокси: {len(active_proxies)}")
        
        if not active_proxies:
            logger.error("❌ Нет активных прокси в базе данных!")
            return
        
        # Инициализация парсера
        parser = SteamMarketParser(redis_service=redis_service, proxy_manager=proxy_manager)
        await parser._ensure_client()
        
        # Тестируем варианты
        variants = [
            "AK-47 | Redline (Field-Tested)",
            "AK-47 | Redline (Minimal Wear)",
            "AK-47 | Redline (Well-Worn)",
            "AK-47 | Redline (Battle-Scarred)",
        ]
        
        logger.info(f"\n🔍 Тестируем {len(variants)} вариантов...")
        
        valid_count = 0
        for variant in variants:
            logger.info(f"\n{'='*80}")
            logger.info(f"🔍 Тестируем: '{variant}'")
            
            is_valid, total_count = await parser.validate_hash_name(appid=730, hash_name=variant)
            
            if is_valid and total_count:
                logger.info(f"✅ '{variant}' валиден: {total_count} лотов доступно")
                valid_count += 1
            else:
                logger.warning(f"❌ '{variant}' невалиден: is_valid={is_valid}, total_count={total_count}")
            
            await asyncio.sleep(2)  # Задержка между запросами
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 ИТОГИ: {valid_count}/{len(variants)} вариантов валидны")
        logger.info("=" * 80)
        
        if valid_count == 0:
            logger.error("❌ НИ ОДИН вариант не прошел проверку!")
        elif valid_count < len(variants):
            logger.warning(f"⚠️  Только {valid_count} из {len(variants)} вариантов валидны")
        else:
            logger.success(f"✅ ВСЕ {valid_count} вариантов валидны!")
        
        await redis_service.disconnect()
        await db_session.close()
        await db_manager.close()
        await parser.close()
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_validate_hash_name())

