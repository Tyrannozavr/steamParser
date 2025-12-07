#!/usr/bin/env python3
"""
Скрипт для проверки и очистки дубликатов прокси в базе данных.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager
from services import ProxyManager
from core.config import Config
from loguru import logger


async def main():
    """Основная функция."""
    logger.info("🔍 Начинаем проверку дубликатов прокси...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        proxy_manager = ProxyManager(session, redis_service=None)
        
        # Проверяем и удаляем дубликаты
        result = await proxy_manager.remove_duplicate_proxies()
        
        logger.info("=" * 70)
        logger.info("📊 РЕЗУЛЬТАТЫ ОЧИСТКИ ДУБЛИКАТОВ:")
        logger.info("=" * 70)
        logger.info(f"✅ Оставлено уникальных прокси: {result['kept']}")
        logger.info(f"🗑️ Удалено дубликатов: {result['removed']}")
        logger.info("=" * 70)
        
        if result['removed'] == 0:
            logger.info("✅ Дубликатов не найдено!")
        else:
            logger.info(f"✅ Очистка завершена! Удалено {result['removed']} дубликатов.")
        
        await session.close()
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке дубликатов: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

