#!/usr/bin/env python3
"""
Скрипт для просмотра всех задач мониторинга.
"""
import asyncio
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask
from sqlalchemy import select
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔍 Просматриваем все задачи мониторинга...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        result = await session.execute(
            select(MonitoringTask).order_by(MonitoringTask.id)
        )
        tasks = list(result.scalars().all())
        
        logger.info(f"📋 Всего задач в БД: {len(tasks)}")
        logger.info("=" * 70)
        
        for task in tasks:
            filters = task.get_filters_dict()
            logger.info(f"ID: {task.id}")
            logger.info(f"  Название: {task.name}")
            logger.info(f"  Предмет: {task.item_name}")
            logger.info(f"  Активна: {task.is_active}")
            logger.info(f"  Интервал: {task.check_interval} сек")
            logger.info(f"  Проверок: {task.total_checks}")
            logger.info(f"  Найдено: {task.items_found}")
            logger.info(f"  Фильтры: {json.dumps(filters, ensure_ascii=False, indent=2)}")
            logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

