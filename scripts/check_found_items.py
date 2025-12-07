#!/usr/bin/env python3
"""
Скрипт для просмотра найденных предметов.
"""
import asyncio
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, FoundItem
from sqlalchemy import select, func
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔍 Просматриваем найденные предметы...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Подсчитываем по задачам
        result = await session.execute(
            select(FoundItem.task_id, func.count(FoundItem.id).label('count'))
            .group_by(FoundItem.task_id)
        )
        task_counts = result.all()
        
        logger.info(f"📊 Найдено предметов по задачам:")
        for task_id, count in task_counts:
            logger.info(f"  Задача {task_id}: {count} предметов")
        
        # Получаем последние найденные предметы
        result = await session.execute(
            select(FoundItem)
            .order_by(FoundItem.found_at.desc())
            .limit(10)
        )
        items = list(result.scalars().all())
        
        logger.info(f"\n📋 Последние {len(items)} найденных предметов:")
        for item in items:
            logger.info(f"  ID: {item.id}, Задача: {item.task_id}, Предмет: {item.item_name}, Цена: ${item.price:.2f}, Уведомление: {item.notification_sent}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

