"""
Скрипт для принудительного запуска парсинга задачи.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core import Config, DatabaseManager, MonitoringTask
from services.redis_service import RedisService
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def force_parse_task(task_id: int = None):
    """Принудительно запускает парсинг задачи."""
    # Инициализируем БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    # Получаем задачу
    if task_id is None:
        # Берем первую активную задачу
        from sqlalchemy import select
        result = await db_session.execute(
            select(MonitoringTask).where(MonitoringTask.is_active == True).limit(1)
        )
        task = result.scalar_one_or_none()
    else:
        task = await db_session.get(MonitoringTask, task_id)
    
    if not task:
        logger.error("❌ Задача не найдена")
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
    
    message = {
        "type": "parsing_task",
        "task_id": task.id,
        "filters_json": filters_json,  # Уже dict (JSONB)
        "item_name": task.item_name,
        "appid": task.appid,
        "currency": task.currency
    }
    
    await redis_service.publish("parsing_tasks", message)
    logger.info(f"📤 Опубликована задача парсинга в Redis: task_id={task.id}")
    
    await redis_service.disconnect()
    await db_session.close()
    await db_manager.close()
    
    logger.info("✅ Задача отправлена, проверяйте логи parsing-worker")


if __name__ == "__main__":
    task_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(force_parse_task(task_id))

