#!/usr/bin/env python3
"""
Скрипт для создания задачи мониторинга MP5-SD | Kitbash (Field-Tested, Pattern 695).
Предмет находится на 200+ странице, поэтому нужен длительный парсинг.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from core.database import DatabaseManager
from services.redis_service import RedisService
from services.proxy_manager_factory import ProxyManagerFactory
from services.monitoring_service import MonitoringService
from core.models import SearchFilters, PatternList, FloatRange
from core.config import Config


async def main():
    """Создает задачу мониторинга для MP5-SD | Kitbash."""
    logger.info("🚀 Создание задачи мониторинга для MP5-SD | Kitbash...")
    
    # Инициализация БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    # Инициализация Redis
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        logger.info("✅ Redis подключен")
    
    # Инициализация ProxyManager через фабрику
    proxy_manager = await ProxyManagerFactory.get_instance(
        db_session=session,
        redis_service=redis_service,
        default_delay=0.2,
        site="steam"
    )
    
    # Инициализация MonitoringService
    monitoring_service = MonitoringService(
        db_session=session,
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    try:
        # Данные из изображения:
        # - Item: MP5-SD | Kitbash
        # - Condition: Field-Tested
        # - Pattern: 695
        # - Float: 0.350077748
        
        item_name = "MP5-SD | Kitbash (Field-Tested)"
        
        # Создаем фильтры
        filters = SearchFilters(
            appid=730,
            currency=1,
            item_name=item_name,
            max_price=1000.0,  # Широкий диапазон цены
            pattern_list=PatternList(
                patterns=[695],
                item_type="skin"
            ),
            float_range=FloatRange(
                min=0.35,  # Точное значение float из изображения
                max=0.35
            ),
            auto_update_base_price=False
        )
        
        # Создаем задачу
        task = await monitoring_service.add_monitoring_task(
            name="🔍 MP5-SD | Kitbash (Field-Tested, Pattern 695, Float 0.35)",
            item_name=item_name,
            filters=filters,
            check_interval=120  # Проверка каждые 2 минуты (предмет далеко)
        )
        
        logger.info(f"✅ Задача создана успешно!")
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Паттерн: 695")
        logger.info(f"   Float: 0.35")
        logger.info(f"   Макс. цена: ${filters.max_price}")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        logger.info(f"   Активна: {task.is_active}")
        logger.info(f"")
        logger.info(f"⚠️ ВНИМАНИЕ: Предмет находится на 200+ странице!")
        logger.info(f"   Парсинг может занять длительное время.")
        logger.info(f"   Используйте скрипт monitor_parsing.py для мониторинга процесса.")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании задачи: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

