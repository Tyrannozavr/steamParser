#!/usr/bin/env python3
"""
Скрипт для удаления найденного предмета из БД
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.database import DatabaseManager
from core.config import Config
from sqlalchemy import select, delete
from core import FoundItem


async def main():
    """Удаляет найденный предмет из БД."""
    if len(sys.argv) < 2:
        logger.error("❌ Использование: python3 scripts/delete_found_item.py <item_id>")
        return
    
    item_id = int(sys.argv[1])
    logger.info(f"🗑️  Удаление предмета ID={item_id}...")
    
    # Инициализация БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Получаем предмет
        item = await session.get(FoundItem, item_id)
        
        if not item:
            logger.error(f"❌ Предмет ID={item_id} не найден")
            return
        
        logger.info(f"📋 Предмет найден: {item.item_name} (${item.price:.2f})")
        logger.info(f"   Задача: {item.task_id}")
        
        # Удаляем предмет
        await session.delete(item)
        await session.commit()
        
        logger.info(f"✅ Предмет ID={item_id} успешно удален")
        
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


