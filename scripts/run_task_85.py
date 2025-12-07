"""
Скрипт для принудительного запуска парсинга задачи #85.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Config, DatabaseManager, MonitoringTask
from services.redis_service import RedisService
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def run_task_85():
    """Принудительно запускает парсинг задачи #85."""
    # Инициализируем БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    # Получаем задачу #85
    task = await db_session.get(MonitoringTask, 85)
    
    if not task:
        logger.error("❌ Задача #85 не найдена")
        await db_session.close()
        await db_manager.close()
        return
    
    logger.info(f"📋 Найдена задача: ID={task.id}, название='{task.name}', предмет='{task.item_name}'")
    
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
    
    # Публикуем задачу в Redis
    from core import SearchFilters
    filters_json = task.filters_json
    if isinstance(filters_json, str):
        import json
        filters_json = json.loads(filters_json)
    
    task_data = {
        "type": "parsing_task",
        "task_id": task.id,
        "filters_json": filters_json,  # Уже dict (JSONB)
        "item_name": task.item_name,
        "appid": task.appid,
        "currency": task.currency
    }
    
    await redis_service.publish("parsing_tasks", task_data)
    logger.info(f"📤 Опубликована задача парсинга в Redis: task_id={task.id}")
    logger.info(f"   Предмет: {task.item_name}")
    logger.info(f"   Фильтры: {filters_json}")
    
    await redis_service.disconnect()
    await db_session.close()
    await db_manager.close()
    logger.info("✅ Задача отправлена, проверяйте логи в logs/tasks/task_85_*.log")


if __name__ == "__main__":
    asyncio.run(run_task_85())

