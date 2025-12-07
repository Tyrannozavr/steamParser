#!/usr/bin/env python3
"""
Скрипт для очистки кэша цен наклеек в Redis
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from services.redis_service import RedisService
from core.config import Config


async def main():
    """Очищает кэш цен наклеек."""
    logger.info("🧹 Очистка кэша цен наклеек в Redis...")
    
    # Инициализация Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    logger.info("✅ Redis подключен")
    
    try:
        # Ищем все ключи с ценами наклеек
        pattern = "sticker_price:*"
        keys = []
        
        async for key in redis_service._client.scan_iter(match=pattern):
            keys.append(key)
        
        logger.info(f"📋 Найдено {len(keys)} ключей в кэше наклеек")
        
        if keys:
            # Удаляем все ключи
            deleted = await redis_service._client.delete(*keys)
            logger.info(f"✅ Удалено {deleted} ключей из кэша")
            
            # Также удаляем конкретные ключи для "Battle Scarred"
            specific_keys = [
                "sticker_price:Battle Scarred:730:1",
                "sticker_price:Sticker | Battle Scarred:730:1"
            ]
            for key in specific_keys:
                deleted = await redis_service._client.delete(key)
                if deleted:
                    logger.info(f"✅ Удален ключ: {key}")
        else:
            logger.info("ℹ️  Кэш наклеек пуст")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке кэша: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await redis_service.disconnect()
        logger.info("✅ Отключено от Redis")


if __name__ == "__main__":
    asyncio.run(main())

