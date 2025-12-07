"""
Создание задачи 147 с параметрами:
- StatTrak™ AK-47 | Redline (Field-Tested)
- Float: 0.27 - 0.29
- Паттерны: 801 (skin)
- Мин. цена наклеек: $0.01
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, SearchFilters, FloatRange, PatternList, StickersFilter
from services import MonitoringService
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

TASK_ID = 147
ITEM_NAME = "StatTrak™ AK-47 | Redline (Field-Tested)"
FLOAT_MIN = 0.27
FLOAT_MAX = 0.29
PATTERN = 801
MIN_STICKERS_PRICE = 0.01

async def create_task():
    logger.info("🚀 Создание задачи 147...")
    
    db_manager = DatabaseManager()
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    monitoring_service = MonitoringService(db_session, None, None, None, redis_service)
    
    try:
        # Удаляем старую задачу, если существует
        existing_task = await db_session.get(MonitoringTask, TASK_ID)
        if existing_task:
            logger.info(f"🗑️ Удаляем существующую задачу {TASK_ID}...")
            await monitoring_service.delete_monitoring_task(TASK_ID)
            logger.info(f"✅ Задача {TASK_ID} удалена.")
        
        # Создаем фильтры
        filters = SearchFilters(
            item_name=ITEM_NAME,
            float_range=FloatRange(min=FLOAT_MIN, max=FLOAT_MAX),
            pattern_list=PatternList(patterns=[PATTERN], item_type="skin"),
            stickers_filter=StickersFilter(
                min_stickers_price=MIN_STICKERS_PRICE
            )
        )
        
        # Создаем задачу
        new_task = await monitoring_service.add_monitoring_task(
            name=f"{ITEM_NAME} - Паттерн {PATTERN}",
            item_name=ITEM_NAME,
            filters=filters,
            check_interval=10
        )
        
        if new_task:
            logger.info(f"✅ Задача {new_task.id} успешно создана!")
            logger.info(f"   📦 Предмет: {ITEM_NAME}")
            logger.info(f"   🎯 Float: {FLOAT_MIN} - {FLOAT_MAX}")
            logger.info(f"   🔢 Паттерны: {PATTERN} (skin)")
            logger.info(f"   💰 Мин. цена наклеек: ${MIN_STICKERS_PRICE}")
            logger.info(f"   ✅ Задача активна: {new_task.is_active}")
            logger.info(f"   📋 Интервал проверки: {new_task.check_interval} сек")
        else:
            logger.error("❌ Не удалось создать задачу")
            sys.exit(1)
            
    except Exception as e:
        logger.exception(f"❌ Ошибка: {e}")
        sys.exit(1)
    finally:
        await db_session.close()
        await redis_service.disconnect()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(create_task())

