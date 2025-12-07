"""
Тестовый скрипт для проверки Well-Worn варианта.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.parser_api_client import ParserAPIClient
from services.redis_service import RedisService
from core import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_well_worn():
    """Тестирует Well-Worn вариант."""
    logger.info("🧪 Начинаем тест Well-Worn варианта")
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    client = ParserAPIClient(redis_service=redis_service)
    
    # Сначала получаем варианты
    logger.info("\n1️⃣ Получаем варианты для 'AK-47 | Redline'")
    try:
        variants = await client.get_item_variants("AK-47 | Redline")
        logger.info(f"   Найдено {len(variants)} вариантов")
        
        # Ищем Well-Worn StatTrak
        well_worn_stattrak = None
        for v in variants:
            name = v.get('market_hash_name', '')
            if 'Well-Worn' in name and 'StatTrak' in name:
                well_worn_stattrak = name
                logger.info(f"   ✅ Найден Well-Worn StatTrak: {name}")
                break
        
        if not well_worn_stattrak:
            logger.warning("   ❌ Well-Worn StatTrak не найден в вариантах")
            # Пробуем вручную
            well_worn_stattrak = "StatTrak™ AK-47 | Redline (Well-Worn)"
            logger.info(f"   🔍 Пробуем вручную: {well_worn_stattrak}")
    except Exception as e:
        logger.error(f"   ❌ Ошибка при получении вариантов: {e}")
        well_worn_stattrak = "StatTrak™ AK-47 | Redline (Well-Worn)"
    
    # Тестируем validate_hash_name
    logger.info(f"\n2️⃣ Проверяем validate_hash_name для '{well_worn_stattrak}'")
    try:
        is_valid, total_count = await client.validate_hash_name(appid=730, hash_name=well_worn_stattrak)
        logger.info(f"   Результат: is_valid={is_valid}, total_count={total_count}")
        
        if is_valid:
            logger.info(f"   ✅ Предмет валиден: {total_count} лотов")
        else:
            logger.warning(f"   ❌ Предмет невалиден (total_count={total_count})")
            logger.warning(f"   ⚠️ Но на маркете есть лоты! Проблема в validate_hash_name")
    except Exception as e:
        logger.error(f"   ❌ Ошибка при validate_hash_name: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    await redis_service.disconnect()


if __name__ == "__main__":
    asyncio.run(test_well_worn())

