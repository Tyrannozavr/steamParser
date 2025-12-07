#!/usr/bin/env python3
"""
Скрипт для проверки дубликатов прокси в базе данных (только проверка, без удаления).
"""
import asyncio
import sys
from pathlib import Path
from collections import defaultdict

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from services import ProxyManager
from core.config import Config
from loguru import logger
from sqlalchemy import select


async def main():
    """Основная функция."""
    logger.info("🔍 Начинаем проверку дубликатов прокси...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        proxy_manager = ProxyManager(session, redis_service=None)
        
        # Получаем все прокси
        result = await session.execute(
            select(Proxy).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        logger.info(f"📋 Всего прокси в БД: {len(all_proxies)}")
        logger.info("=" * 70)
        
        # Группируем по нормализованному URL
        normalized_groups: dict[str, list[Proxy]] = defaultdict(list)
        for proxy in all_proxies:
            normalized = ProxyManager._normalize_proxy_url(proxy.url)
            normalized_groups[normalized].append(proxy)
        
        # Находим дубликаты
        duplicates_found = 0
        total_duplicates = 0
        
        logger.info("🔍 Проверка на дубликаты...")
        logger.info("=" * 70)
        
        for normalized_url, proxies in sorted(normalized_groups.items()):
            if len(proxies) > 1:
                duplicates_found += 1
                total_duplicates += len(proxies) - 1
                
                logger.info(f"\n🔴 ДУБЛИКАТЫ для нормализованного URL: {normalized_url}")
                proxies_sorted = sorted(proxies, key=lambda p: p.id)
                logger.info(f"   ✅ Оставить (самый старый): ID={proxies_sorted[0].id}, URL={proxies_sorted[0].url}")
                for dup in proxies_sorted[1:]:
                    logger.info(f"   ❌ Удалить: ID={dup.id}, URL={dup.url}")
        
        logger.info("=" * 70)
        logger.info("📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ:")
        logger.info("=" * 70)
        logger.info(f"📋 Всего прокси: {len(all_proxies)}")
        logger.info(f"📋 Уникальных нормализованных URL: {len(normalized_groups)}")
        logger.info(f"🔴 Групп с дубликатами: {duplicates_found}")
        logger.info(f"🗑️ Прокси-дубликатов (к удалению): {total_duplicates}")
        logger.info("=" * 70)
        
        if duplicates_found == 0:
            logger.info("✅ Дубликатов не найдено! Все прокси уникальны.")
        else:
            logger.info(f"⚠️ Найдено {duplicates_found} групп дубликатов!")
            logger.info(f"💡 Запустите cleanup_proxy_duplicates.py для удаления дубликатов")
        
        await session.close()
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке дубликатов: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

