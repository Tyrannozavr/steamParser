#!/usr/bin/env python3
"""
Скрипт для поиска, удаления и пересоздания задачи AK-47 | Redline (Field-Tested)
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
from core.config import Config
from sqlalchemy import select
from core import MonitoringTask


async def main():
    """Находит, удаляет и пересоздает задачу."""
    item_name = "AK-47 | Redline (Field-Tested)"
    
    logger.info(f"🔍 Ищем задачу для '{item_name}'...")
    
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
        # Ищем задачу
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.item_name == item_name)
        )
        tasks = result.scalars().all()
        
        if tasks:
            logger.info(f"📋 Найдено {len(tasks)} задач для '{item_name}':")
            for task in tasks:
                logger.info(f"   - ID: {task.id}, Название: {task.name}, Активна: {task.is_active}")
            
            # Удаляем все найденные задачи
            for task in tasks:
                logger.info(f"🗑️  Удаляем задачу ID={task.id}...")
                success = await monitoring_service.delete_monitoring_task(task.id)
                if success:
                    logger.info(f"✅ Задача {task.id} успешно удалена")
                else:
                    logger.error(f"❌ Не удалось удалить задачу {task.id}")
        else:
            logger.info(f"ℹ️  Задачи для '{item_name}' не найдены")
        
        # Создаем новую задачу
        logger.info(f"📝 Создаем новую задачу для '{item_name}'...")
        
        from core import SearchFilters, PatternList, StickersFilter
        
        filters = SearchFilters(
            item_name=item_name,
            max_price=100.0,
            pattern_list=PatternList(
                patterns=[160],  # Паттерн 160
                item_type="skin"
            ),
            stickers_filter=StickersFilter(
                min_stickers_price=0.0,
                max_overpay_coefficient=None
            )
        )
        
        new_task = await monitoring_service.add_monitoring_task(
            name=f"{item_name} - Паттерн 160 (пересоздана)",
            item_name=item_name,
            filters=filters,
            check_interval=300  # 5 минут
        )
        
        if new_task:
            logger.info(f"✅ Новая задача создана: ID={new_task.id}, Название: {new_task.name}")
            logger.info(f"   📋 Параметры: appid={new_task.appid}, check_interval={new_task.check_interval}с")
            logger.info(f"   🔍 Фильтры: max_price=${filters.max_price}, pattern={filters.pattern_list.patterns}")
        else:
            logger.error("❌ Не удалось создать новую задачу")
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

