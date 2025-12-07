"""
Скрипт для проверки созданной задачи и запуска тестов.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from core.config import Config
from sqlalchemy import select, desc
from core.database import MonitoringTask
from loguru import logger
import json

logger.remove()
logger.add(sys.stderr, level="INFO")


async def check_task():
    """Проверяет созданную задачу."""
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Получаем последние 5 задач
        result = await session.execute(
            select(MonitoringTask)
            .order_by(desc(MonitoringTask.id))
            .limit(5)
        )
        tasks = result.scalars().all()
        
        if not tasks:
            logger.error("❌ Нет задач в базе данных")
            return
        
        logger.info(f"📋 Найдено {len(tasks)} последних задач:\n")
        
        for task in tasks:
            logger.info(f"🔍 Задача ID={task.id}:")
            logger.info(f"   Название: {task.name}")
            logger.info(f"   Предмет: {task.item_name}")
            logger.info(f"   Активна: {task.is_active}")
            logger.info(f"   Интервал: {task.check_interval} сек")
            
            if task.filters_json:
                filters = task.filters_json
                if isinstance(filters, dict):
                    if filters.get('stickers_filter'):
                        sf = filters['stickers_filter']
                        logger.info(f"   📊 Фильтры наклеек:")
                        if sf.get('min_stickers_price'):
                            logger.info(f"      - min_stickers_price: ${sf['min_stickers_price']:.2f}")
                        if sf.get('max_overpay_coefficient') is not None:
                            logger.info(f"      - max_overpay_coefficient: {sf['max_overpay_coefficient']}")
            
            logger.info("")
        
        # Находим задачу с фильтром по наклейкам
        sticker_tasks = [t for t in tasks if t.filters_json and isinstance(t.filters_json, dict) and t.filters_json.get('stickers_filter')]
        
        if sticker_tasks:
            logger.info(f"✅ Найдено {len(sticker_tasks)} задач с фильтром по наклейкам")
            logger.info(f"   Последняя: ID={sticker_tasks[0].id}, '{sticker_tasks[0].name}'")
        else:
            logger.warning("⚠️ Не найдено задач с фильтром по наклейкам")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке задач: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(check_task())

