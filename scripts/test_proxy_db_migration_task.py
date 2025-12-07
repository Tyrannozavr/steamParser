#!/usr/bin/env python3
"""
Скрипт для создания тестовой задачи для проверки миграции данных прокси из Redis в БД.
Создает задачу с паттерном 739 для Desert Eagle | Printstream (Factory New).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import DatabaseManager
from services.redis_service import RedisService
from services.proxy_manager_factory import ProxyManagerFactory
from services.monitoring_service import MonitoringService
from core import SearchFilters, PatternList
from loguru import logger


async def main():
    """Создает тестовую задачу для проверки миграции."""
    logger.info("🚀 Создание тестовой задачи для проверки миграции Redis -> БД...")
    
    # Инициализация
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    redis_service = RedisService()
    await redis_service.connect()
    
    proxy_manager = await ProxyManagerFactory.get_proxy_manager(
        db_session=session,
        redis_service=redis_service
    )
    
    monitoring_service = MonitoringService(
        db_session=session,
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    # Создаем фильтры для Desert Eagle | Printstream (Factory New) с паттерном 739
    filters = SearchFilters(
        item_name="Desert Eagle | Printstream (Factory New)",
        pattern_list=PatternList(patterns=[739], item_type="skin"),
        appid=730,
        currency=1
    )
    
    try:
        task = await monitoring_service.add_monitoring_task(
            name="🧪 Тест миграции Redis->БД (Pattern 739)",
            item_name="Desert Eagle | Printstream (Factory New)",
            filters=filters,
            check_interval=60  # Проверка каждую минуту
        )
        
        logger.info(f"✅ Задача создана успешно!")
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Паттерн: 739")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        logger.info(f"   Активна: {task.is_active}")
        logger.info(f"")
        logger.info(f"📋 Задача будет проверяться каждые {task.check_interval} секунд")
        logger.info(f"📊 Используйте команду /tasks в Telegram боте для просмотра задач")
        logger.info(f"🔔 Уведомления будут отправляться в Telegram при нахождении предметов")
        logger.info(f"")
        logger.info(f"🔍 Проверьте логи в /logs/tasks/task_{task.id}_*.log для отслеживания выполнения")
        logger.info(f"   Ожидайте логи вида:")
        logger.info(f"   - [ШАГ 1/4] Получение прокси")
        logger.info(f"   - [ШАГ 2/4] Создание парсера")
        logger.info(f"   - [ШАГ 3/4] Инициализация парсера")
        logger.info(f"   - [ШАГ 4/4] Выполнение поиска")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании задачи: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

