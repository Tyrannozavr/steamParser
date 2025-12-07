#!/usr/bin/env python3
"""
Скрипт для добавления или обновления задачи 136.
AK-47 | Redline (Field-Tested) - Паттерн 522
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, SearchFilters, FloatRange, PatternList
from services import MonitoringService
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🚀 Добавляем/обновляем задачу 136...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    try:
        session = await db_manager.get_session()
        
        from services.proxy_manager import ProxyManager
        proxy_manager = ProxyManager(session, redis_service=redis_service)
        
        monitoring_service = MonitoringService(
            session,
            proxy_manager,
            notification_callback=None,
            redis_service=redis_service
        )
        
        from sqlalchemy import select
        
        # Проверяем, существует ли задача 136
        task_result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.id == 136)
        )
        existing_task = task_result.scalar_one_or_none()
        
        # Создаем фильтры
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            appid=730,
            currency=1,
            max_price=50.00,
            float_range=FloatRange(min=0.350000, max=0.360000),
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        if existing_task:
            logger.info(f"✅ Задача 136 уже существует: {existing_task.name}")
            logger.info("🔄 Обновляем задачу...")
            
            task = await monitoring_service.update_monitoring_task(
                task_id=136,
                name="AK-47 | Redline (Field-Tested) - Паттерн 522 (task 136)",
                filters=filters
            )
            
            if task:
                logger.info("✅ Задача 136 обновлена")
            else:
                logger.error("❌ Не удалось обновить задачу 136")
                return
        else:
            logger.info("➕ Создаем новую задачу 136...")
            
            # Создаем задачу напрямую с ID 136
            new_task = MonitoringTask(
                id=136,
                name="AK-47 | Redline (Field-Tested) - Паттерн 522 (task 136)",
                item_name=filters.item_name,
                filters_json=filters.model_dump_json(),
                is_active=True,
                total_checks=0,
                items_found=0,
                check_interval=60
            )
            
            session.add(new_task)
            await session.commit()
            await session.refresh(new_task)
            task = new_task
            
            logger.info("✅ Задача 136 создана")
        
        if task:
            logger.info(f"")
            logger.info(f"📋 Параметры задачи 136:")
            logger.info(f"   📦 Предмет: {task.item_name}")
            logger.info(f"   💰 Макс. цена: ${filters.max_price:.2f}")
            logger.info(f"   🔢 Float: {filters.float_range.min} - {filters.float_range.max}")
            logger.info(f"   🎨 Паттерны: {filters.pattern_list.patterns}")
            logger.info(f"   📊 Проверок: {task.total_checks}, Найдено: {task.items_found}")
            logger.info(f"   ✅ Активна: {task.is_active}")
            logger.info(f"")
            
            # Отправляем задачу в очередь Redis для немедленной обработки
            logger.info("📤 Отправляем задачу в очередь Redis для обработки...")
            task_data = {
                "task_id": task.id,
                "action": "parse"
            }
            await redis_service.push_to_queue("parsing_tasks", task_data)
            logger.info("✅ Задача отправлена в очередь 'parsing_tasks'")
            logger.info("")
            logger.info("🔍 Парсинг начнется автоматически. Проверьте логи parsing-worker для отслеживания прогресса.")
                
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

