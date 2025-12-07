"""
Тестовый скрипт для проверки работы ротации прокси и обработки 429 ошибок.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.steam_api_methods import SteamAPIMethods
from core.steam_helper_methods import SteamHelperMethods
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

class TestParser(SteamAPIMethods, SteamHelperMethods):
    """Тестовый парсер для проверки работы прокси."""
    def __init__(self, proxy_manager=None):
        self.proxy = None
        self.proxy_manager = proxy_manager
        self.timeout = 30
        self._client = None

async def main():
    """Основная функция тестирования."""
    # Подключение к БД
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/steam_db")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Подключение к Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_service = RedisService(redis_url=redis_url)
    await redis_service.connect()
    
    # Создание ProxyManager
    async with async_session() as session:
        proxy_manager = ProxyManager(db_session=session, redis_service=redis_service)
        
        # Создание тестового парсера
        parser = TestParser(proxy_manager=proxy_manager)
        
        # Тестируем validate_hash_name с разными вариантами
        test_items = [
            "AK-47 | Redline (Field-Tested)",
            "StatTrak™ AK-47 | Redline (Field-Tested)",
            "AK-47 | Redline (Well-Worn)",
            "StatTrak™ AK-47 | Redline (Well-Worn)",
        ]
        
        logger.info("🧪 Начинаю тестирование ротации прокси и обработки 429 ошибок")
        logger.info(f"📋 Тестирую {len(test_items)} вариантов предметов")
        
        for idx, hash_name in enumerate(test_items, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"📦 Тест {idx}/{len(test_items)}: {hash_name}")
            logger.info(f"{'='*60}")
            
            try:
                is_valid, total_count = await parser.validate_hash_name(appid=730, hash_name=hash_name)
                
                if is_valid:
                    logger.info(f"✅ Успех: {hash_name} - валиден, {total_count} лотов")
                else:
                    logger.warning(f"❌ Ошибка: {hash_name} - невалиден или не найден")
                
                # Небольшая задержка между тестами
                if idx < len(test_items):
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logger.error(f"❌ Исключение при тестировании {hash_name}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Закрываем клиент
        if parser._client:
            await parser._client.aclose()
        
        logger.info(f"\n{'='*60}")
        logger.info("✅ Тестирование завершено")
        logger.info(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())

