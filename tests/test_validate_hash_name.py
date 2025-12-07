"""
Тестовый скрипт для проверки validate_hash_name через parser_api.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.parser_api_client import ParserAPIClient
from core import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_validate_hash_name():
    """Тестирует validate_hash_name для разных вариантов."""
    logger.info("🧪 Начинаем тест validate_hash_name")
    
    client = ParserAPIClient(redis_url=Config.REDIS_URL)
    
    # Тестируем несколько вариантов
    test_cases = [
        "StatTrak™ AK-47 | Redline (Field-Tested)",
        "AK-47 | Redline (Field-Tested)",
        "StatTrak™ AK-47 | Redline (Well-Worn)",
    ]
    
    for hash_name in test_cases:
        logger.info(f"\n🔍 Тестируем: {hash_name}")
        try:
            is_valid, total_count = await client.validate_hash_name(appid=730, hash_name=hash_name)
            logger.info(f"   Результат: is_valid={is_valid}, total_count={total_count}")
            if is_valid:
                logger.info(f"   ✅ Предмет валиден: {total_count} лотов")
            else:
                logger.warning(f"   ❌ Предмет невалиден")
        except Exception as e:
            logger.error(f"   ❌ Ошибка: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Задержка между запросами
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(test_validate_hash_name())
