#!/usr/bin/env python3
"""
Скрипт для просмотра всех задач в БД
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.database import DatabaseManager
from core.config import Config
from sqlalchemy import select
from core import MonitoringTask


async def main():
    """Показывает все задачи в БД."""
    logger.info("📋 Получение списка задач из БД...")
    
    # Инициализация БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Получаем все задачи
        result = await session.execute(
            select(MonitoringTask).order_by(MonitoringTask.id)
        )
        tasks = result.scalars().all()
        
        if not tasks:
            logger.warning("⚠️ Задач в БД не найдено")
            return
        
        logger.info(f"✅ Найдено задач: {len(tasks)}\n")
        
        for task in tasks:
            logger.info(f"📌 Задача ID={task.id}: {task.name}")
            logger.info(f"   Предмет: {task.item_name}")
            logger.info(f"   AppID: {task.appid}, Валюта: {task.currency}")
            logger.info(f"   Активна: {task.is_active}")
            logger.info(f"   Интервал проверки: {task.check_interval}с")
            logger.info(f"   Следующая проверка: {task.next_check}")
            logger.info("")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
