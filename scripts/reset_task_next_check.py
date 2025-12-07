#!/usr/bin/env python3
"""
Скрипт для сброса next_check задачи, чтобы она обработалась немедленно
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.database import DatabaseManager
from core.config import Config
from sqlalchemy import select, update
from core import MonitoringTask


async def main():
    """Сбрасывает next_check для задачи."""
    if len(sys.argv) < 2:
        logger.error("❌ Использование: python3 scripts/reset_task_next_check.py <task_id>")
        return
    
    task_id = int(sys.argv[1])
    logger.info(f"🔄 Сброс next_check для задачи {task_id}...")
    
    # Инициализация БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Получаем задачу
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            logger.error(f"❌ Задача {task_id} не найдена")
            return
        
        logger.info(f"📋 Задача найдена: {task.name}")
        logger.info(f"   Текущий next_check: {task.next_check}")
        
        # Сбрасываем next_check на текущее время
        await session.execute(
            update(MonitoringTask)
            .where(MonitoringTask.id == task_id)
            .values(next_check=datetime.now())
        )
        await session.commit()
        
        logger.info(f"✅ next_check сброшен на текущее время")
        logger.info(f"   Задача будет обработана при следующей проверке")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        await session.rollback()
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

