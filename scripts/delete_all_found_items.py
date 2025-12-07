#!/usr/bin/env python3
"""
Скрипт для удаления всех найденных предметов из БД.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete
from loguru import logger

from core.database import DatabaseManager, FoundItem
from core.config import Config


async def main():
    """Удаляет все найденные предметы из БД."""
    logger.info("🗑️ Начинаем удаление всех найденных предметов...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Подсчитываем количество предметов перед удалением
        from sqlalchemy import select, func
        count_result = await session.execute(select(func.count(FoundItem.id)))
        total_count = count_result.scalar()
        
        logger.info(f"📊 Найдено предметов в БД: {total_count}")
        
        if total_count == 0:
            logger.info("✅ В БД нет предметов для удаления")
            return
        
        # Удаляем все предметы
        await session.execute(delete(FoundItem))
        await session.commit()
        
        logger.info(f"✅ Удалено {total_count} предметов из БД")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении предметов: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        await session.rollback()
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

