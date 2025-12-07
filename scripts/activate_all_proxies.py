#!/usr/bin/env python3
"""
Скрипт для активации всех прокси.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from sqlalchemy import select, update
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔍 Активируем все прокси...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Получаем все прокси
        result = await session.execute(
            select(Proxy).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        logger.info(f"📋 Всего прокси в БД: {len(all_proxies)}")
        
        # Активируем все прокси и увеличиваем задержку
        activated = 0
        for proxy in all_proxies:
            if not proxy.is_active:
                proxy.is_active = True
                # Увеличиваем задержку до 3 секунд для всех прокси
                if proxy.delay_seconds < 3.0:
                    proxy.delay_seconds = 3.0
                activated += 1
                logger.info(f"✅ Активирован прокси ID={proxy.id}, задержка установлена: {proxy.delay_seconds}с")
            else:
                # Увеличиваем задержку и для активных
                if proxy.delay_seconds < 3.0:
                    old_delay = proxy.delay_seconds
                    proxy.delay_seconds = 3.0
                    logger.info(f"⏱️ Увеличена задержка для прокси ID={proxy.id}: {old_delay}с → {proxy.delay_seconds}с")
        
        await session.commit()
        
        logger.info("=" * 70)
        logger.info(f"✅ Активировано прокси: {activated}")
        logger.info(f"📊 Всего активных прокси: {len(all_proxies)}")
        logger.info(f"⏱️ Задержка установлена: 3.0с для всех прокси")
        logger.info("=" * 70)
        
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

