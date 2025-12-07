#!/usr/bin/env python3
"""
Скрипт для добавления тестовой задачи с фильтром наклеек.
Проверяет, что цены на наклейки парсятся корректно и задачи не зависают.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import DatabaseManager
from core import SearchFilters, StickersFilter, MonitoringTask
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from services.monitoring_service import MonitoringService
from loguru import logger
from sqlalchemy import select


async def main():
    """Основная функция."""
    logger.info("🚀 Создание тестовой задачи с фильтром наклеек...")
    
    db_manager = DatabaseManager()
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        
        # Инициализируем сервисы
        redis_service = None
        if Config.REDIS_ENABLED:
            redis_service = RedisService(Config.REDIS_URL)
            try:
                await redis_service.connect()
                logger.info("✅ Подключение к Redis установлено")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}")
        
        proxy_manager = ProxyManager(session, redis_service=redis_service)
        monitoring_service = MonitoringService(
            session, 
            proxy_manager,
            redis_service=redis_service
        )
        
        # Создаем фильтры для тестовой задачи
        # Используем предмет из логов, который точно имеет наклейки
        item_name = "AK-47 | Redline (Field-Tested)"
        
        filters = SearchFilters(item_name=item_name)
        
        # Фильтр по наклейкам: формула S = D + (P * x)
        # Максимальный коэффициент переплаты: 0.15 (15%)
        # Это позволит найти предметы с наклейками, но не слишком дорогие
        filters.stickers_filter = StickersFilter(
            max_overpay_coefficient=0.15,  # 15% переплата
            min_stickers_price=1.0  # Минимум $1 наклеек
        )
        
        # Проверяем, нет ли уже такой задачи
        from sqlalchemy import select
        result = await session.execute(
            select(MonitoringTask).where(
                MonitoringTask.item_name == item_name,
                MonitoringTask.is_active == True
            )
        )
        existing_task = result.scalar_one_or_none()
        
        if existing_task:
            logger.info(f"⚠️ Задача для '{item_name}' уже существует (ID: {existing_task.id})")
            logger.info(f"   Используем существующую задачу для тестирования")
            task = existing_task
        else:
            # Создаем задачу
            task = await monitoring_service.add_monitoring_task(
                name=f"ТЕСТ: {item_name} с наклейками",
                item_name=item_name,
                filters=filters,
                check_interval=60  # Проверка каждую минуту
            )
            
            logger.info(f"✅ Задача создана!")
        
        logger.info(f"   ID: {task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Макс. переплата за наклейки: {filters.stickers_filter.max_overpay_coefficient:.2%}")
        logger.info(f"   Мин. цена наклеек: ${filters.stickers_filter.min_stickers_price:.2f}")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        logger.info(f"   Активна: {task.is_active}")
        
        # Публикуем задачу в Redis для немедленного запуска
        if redis_service and redis_service.is_connected():
            task_data = {
                "type": "parsing_task",
                "task_id": task.id,
                "filters_json": task.filters_json,
                "item_name": task.item_name,
                "appid": task.appid,
                "currency": task.currency
            }
            await redis_service.push_to_queue("parsing_tasks", task_data)
            logger.info(f"✅ Задача добавлена в очередь Redis для немедленного запуска")
        
        logger.info(f"\n🎯 ТЕСТОВАЯ ЗАДАЧА ГОТОВА К РАБОТЕ!")
        logger.info(f"   Следите за логами parsing_worker для проверки:")
        logger.info(f"   - Получения цен наклеек через новый метод")
        logger.info(f"   - Отсутствия зависаний задач")
        logger.info(f"   - Корректной работы фильтров наклеек")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

