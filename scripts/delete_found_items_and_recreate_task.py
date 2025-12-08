#!/usr/bin/env python3
"""
Скрипт для удаления всех найденных предметов и пересоздания задачи
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
from sqlalchemy import select, delete
from core import MonitoringTask, FoundItem, SearchFilters, PatternList, StickersFilter


async def main():
    """Удаляет все найденные предметы и пересоздает задачу."""
    item_name = "MP9 | Starlight Protector (Field-Tested)"
    
    logger.info(f"🗑️  Удаляем все найденные предметы для '{item_name}'...")
    
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
        # ВАЖНО: Удаляем ВСЕ найденные предметы для этого item_name, независимо от task_id
        # Это нужно, чтобы предметы с теми же ценами могли быть сохранены заново
        logger.info(f"🗑️  Удаляем ВСЕ найденные предметы для '{item_name}' (независимо от task_id)...")
        delete_result = await session.execute(
            delete(FoundItem).where(FoundItem.item_name == item_name)
        )
        deleted_count = delete_result.rowcount
        logger.info(f"✅ Удалено {deleted_count} найденных предметов для '{item_name}'")
        
        # Находим все задачи для этого предмета
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.item_name == item_name)
        )
        tasks = result.scalars().all()
        
        if tasks:
            for task in tasks:
                # Удаляем саму задачу
                logger.info(f"🗑️  Удаляем задачу {task.id}...")
                await monitoring_service.delete_monitoring_task(task.id)
                logger.info(f"✅ Задача {task.id} удалена")
        else:
            logger.warning(f"⚠️  Задачи для '{item_name}' не найдены")
        
        await session.commit()
        
        # Создаем новую задачу
        logger.info(f"📝 Создаем новую задачу для '{item_name}'...")
        
        filters = SearchFilters(
            item_name=item_name,
            appid=730,
            currency=1,
            max_price=100.0,
            pattern_list=PatternList(
                patterns=[173, 864, 208, 567],
                item_type="skin"
            ),
            stickers_filter=StickersFilter(
                min_stickers_price=0.0,
                max_overpay_coefficient=None
            )
        )
        
        new_task = await monitoring_service.add_monitoring_task(
            name=item_name,
            item_name=item_name,
            filters=filters,
            check_interval=60  # 1 минута для быстрого теста
        )
        
        if new_task:
            logger.info(f"✅ Новая задача создана: ID={new_task.id}, Название: {new_task.name}")
            
            # Сбрасываем next_check для немедленного запуска
            from datetime import datetime
            new_task.next_check = datetime.now()
            await session.commit()
            logger.info(f"   ⏰ next_check установлен на текущее время для немедленного запуска")
            
            # Публикуем задачу в Redis очередь для немедленного выполнения
            if redis_service and redis_service.is_connected():
                try:
                    queue_key = "parsing_tasks"
                    task_message = {
                        "task_id": new_task.id,
                        "action": "parse"
                    }
                    await redis_service.push_to_queue(queue_key, task_message)
                    logger.info(f"   📤 Задача добавлена в Redis очередь для немедленного выполнения")
                except Exception as e:
                    logger.warning(f"   ⚠️ Не удалось добавить задачу в очередь: {e}")
        else:
            logger.error("❌ Не удалось создать новую задачу")
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        if redis_service:
            await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

