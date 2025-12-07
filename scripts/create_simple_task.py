"""
Скрипт для создания простой задачи и публикации её в Redis.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import SearchFilters
from core.database import DatabaseManager, MonitoringTask
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")


async def create_and_publish_task():
    """Создает простую задачу и публикует её в Redis."""
    
    # Инициализируем БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Создаем простую задачу
        filters = SearchFilters(
            item_name="AK-47 | Redline",
            appid=730,
            max_price=50.0
        )
        
        # Создаем задачу в БД
        task = MonitoringTask(
            name="ТЕСТ: Простая задача",
            item_name=filters.item_name,
            appid=filters.appid,
            currency=1,
            filters_json=filters.model_dump(),
            is_active=True,
            check_interval=60,
            created_at=datetime.utcnow()
        )
        
        session.add(task)
        await session.commit()
        await session.refresh(task)
        
        logger.info(f"✅ Создана задача ID={task.id}: '{task.name}'")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Макс. цена: ${filters.max_price}")
        
        # Инициализируем Redis
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        try:
            await redis_service.connect()
            logger.info("✅ Redis подключен")
            
            # Публикуем задачу в Redis
            task_data = {
                "type": "parsing_task",
                "task_id": task.id,
                "filters_json": task.filters_json,  # Уже dict (JSONB)
                "item_name": task.item_name,
                "appid": task.appid,
                "currency": task.currency
            }
            
            logger.info(f"📤 Публикуем задачу {task.id} в Redis канал 'parsing_tasks'")
            await redis_service.publish("parsing_tasks", task_data)
            logger.info(f"✅ Задача {task.id} успешно опубликована в Redis")
            logger.info(f"⏱️  Время публикации: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"\n📋 Следите за логами parsing-worker для проверки выполнения")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при работе с Redis: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
        finally:
            await redis_service.disconnect()
    
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(create_and_publish_task())
