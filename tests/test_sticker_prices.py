"""
Скрипт для тестирования парсинга наклеек и запроса цен после прохождения фильтров.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from services.monitoring_service import MonitoringService
from core.models import SearchFilters
from loguru import logger
from core.config import Config
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from sqlalchemy import select
from core.database import MonitoringTask

logger.remove()
logger.add(sys.stderr, level="INFO")

async def test_sticker_prices():
    """Тестирует парсинг наклеек и запрос цен после прохождения фильтров."""
    logger.info("🧪 Тестируем парсинг наклеек и запрос цен")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    logger.info(f"✅ Подключено к Redis: {Config.REDIS_URL}")
    
    session = await db_manager.get_session()
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    proxy_manager.start_background_proxy_check()
    
    monitoring_service = MonitoringService(db_session=session, proxy_manager=proxy_manager, redis_service=redis_service)
    
    # Получаем последнюю задачу
    result = await session.execute(
        select(MonitoringTask).order_by(MonitoringTask.id.desc()).limit(1)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        logger.error("❌ Нет задач в базе данных")
        await redis_service.disconnect()
        await session.close()
        await db_manager.close()
        return
    
    logger.info(f"\n🎯 ТЕСТОВАЯ ЗАДАЧА:")
    logger.info(f"   ID: {task.id}")
    logger.info(f"   Название: {task.name}")
    logger.info(f"   Предмет: {task.item_name}")
    logger.info(f"   Фильтр по наклейкам: {task.filters.stickers_filter is not None if task.filters else 'нет фильтров'}")
    
    # Запускаем проверку задачи вручную
    logger.info(f"\n🚀 Запускаем проверку задачи {task.id}...")
    await monitoring_service._check_task(task)
    
    logger.info(f"\n✅ Проверка завершена. Проверьте логи на наличие:")
    logger.info(f"   1. 'Предмет прошел фильтры, запрашиваем цены на наклейки для уведомления...'")
    logger.info(f"   2. 'Обновлены цены для X наклеек, общая цена: $X.XX'")
    logger.info(f"   3. В уведомлении должны быть цены на наклейки")
    
    await redis_service.disconnect()
    await session.close()
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_sticker_prices())

