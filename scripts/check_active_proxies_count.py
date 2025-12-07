#!/usr/bin/env python3
"""
Скрипт для быстрой проверки количества активных прокси.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, Proxy
from services import ProxyManager
from core.config import Config
from loguru import logger
from sqlalchemy import select, func


async def main():
    """Основная функция."""
    logger.info("🔍 Проверяю количество активных прокси...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        try:
            proxy_manager = ProxyManager(session, redis_service=None)
            
            # Получаем статистику через ProxyManager
            stats = await proxy_manager.get_proxy_stats()
            
            # Выводим результат
            logger.info("=" * 70)
            logger.info("📊 СТАТИСТИКА ПРОКСИ:")
            logger.info("=" * 70)
            logger.info(f"📋 Всего прокси: {stats['total']}")
            logger.info(f"✅ Активных: {stats['active']}")
            logger.info(f"❌ Неактивных: {stats['inactive']}")
            logger.info("=" * 70)
            
            # Дополнительная информация: статистика по успешным/неуспешным запросам
            total_success = sum(p.get('success_count', 0) for p in stats.get('proxies', []))
            total_fail = sum(p.get('fail_count', 0) for p in stats.get('proxies', []))
            
            if total_success + total_fail > 0:
                success_rate = (total_success / (total_success + total_fail)) * 100
                logger.info(f"📈 Успешных запросов: {total_success}")
                logger.info(f"📉 Ошибок: {total_fail}")
                logger.info(f"📊 Успешность: {success_rate:.1f}%")
                logger.info("=" * 70)
            
            # Показываем список активных прокси
            if stats['active'] > 0:
                logger.info(f"\n✅ Список активных прокси ({stats['active']}):")
                active_proxies = [p for p in stats['proxies'] if p['active']]
                for p in active_proxies:
                    logger.info(f"   ID={p['id']}: {p['url']} (успешно={p['success_count']}, ошибок={p['fail_count']}, задержка={p['delay_seconds']:.1f}с)")
        finally:
            await session.close()
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

