"""
Прямой тест Parser API через Redis для проверки validate_hash_name.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.parser_api_client import ParserAPIClient
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

async def test_validate_hash_name():
    """Тестирует validate_hash_name через Parser API."""
    logger.info("=" * 80)
    logger.info("🧪 Тест validate_hash_name через Parser API")
    logger.info("=" * 80)
    
    try:
        # Инициализация Redis
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        
        # Инициализация Parser API клиента
        client = ParserAPIClient(redis_service=redis_service)
        
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
            
            try:
                result = await client.validate_hash_name(appid=730, hash_name=variant)
                
                is_valid = result.get('is_valid', False)
                total_count = result.get('total_count', None)
                
                if is_valid and total_count:
                    logger.info(f"✅ '{variant}' валиден: {total_count} лотов доступно")
                    valid_count += 1
                else:
                    logger.warning(f"❌ '{variant}' невалиден: is_valid={is_valid}, total_count={total_count}")
                    logger.warning(f"   Полный ответ: {json.dumps(result, indent=2, ensure_ascii=False)}")
                
            except Exception as e:
                logger.error(f"❌ Ошибка при проверке '{variant}': {e}")
                import traceback
                traceback.print_exc()
            
            await asyncio.sleep(1)  # Задержка между запросами
        
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
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_validate_hash_name())

