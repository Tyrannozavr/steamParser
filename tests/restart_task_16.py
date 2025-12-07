#!/usr/bin/env python3
"""
Скрипт для перезапуска задачи 16: удаляет и заново создает задачу.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager, MonitoringTask, FoundItem
from core import SearchFilters, StickersFilter
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from core.config import Config
from sqlalchemy import select, delete
from loguru import logger
import json

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def restart_task_16():
    """Удаляет и заново создает задачу 16."""
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    # Инициализируем ProxyManager
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    
    # Инициализируем MonitoringService
    monitoring_service = MonitoringService(
        session,
        proxy_manager,
        notification_callback=None,
        redis_service=redis_service
    )
    
    try:
        # Получаем задачу 16
        task = await session.get(MonitoringTask, 16)
        
        if task:
            logger.info(f"📋 Найдена задача 16: '{task.name}'")
            logger.info(f"   Предмет: {task.item_name}")
            logger.info(f"   Найдено предметов: {task.items_found}")
            
            # Сохраняем фильтры для восстановления
            filters_json = task.filters_json
            if isinstance(filters_json, str):
                filters_dict = json.loads(filters_json)
            else:
                filters_dict = filters_json
            
            # Удаляем все найденные предметы для задачи 16
            logger.info("🗑️ Удаляем найденные предметы для задачи 16...")
            await session.execute(
                delete(FoundItem).where(FoundItem.task_id == 16)
            )
            deleted_count = await session.execute(
                select(FoundItem).where(FoundItem.task_id == 16)
            )
            logger.info(f"   Удалено предметов: {len(list(deleted_count.scalars().all()))}")
            
            # Удаляем задачу
            logger.info("🗑️ Удаляем задачу 16...")
            deleted = await monitoring_service.delete_monitoring_task(16)
            
            if deleted:
                logger.info("✅ Задача 16 удалена")
            else:
                logger.error("❌ Не удалось удалить задачу 16")
                return
        else:
            logger.info("ℹ️ Задача 16 не найдена, создаем новую...")
            # Пробуем получить фильтры из последней найденной задачи с таким же предметом
            result = await session.execute(
                select(MonitoringTask)
                .where(MonitoringTask.item_name == "AK-47 | Redline (Minimal Wear)")
                .order_by(MonitoringTask.id.desc())
                .limit(1)
            )
            similar_task = result.scalar_one_or_none()
            if similar_task:
                filters_json = similar_task.filters_json
                if isinstance(filters_json, str):
                    filters_dict = json.loads(filters_json)
                else:
                    filters_dict = filters_json
                logger.info(f"📋 Используем фильтры из похожей задачи {similar_task.id}")
            else:
                # Создаем фильтры по умолчанию
                filters_dict = {
                    "item_name": "AK-47 | Redline (Minimal Wear)",
                    "appid": 730,
                    "currency": 1,
                    "max_price": 1000.0,
                    "stickers_filter": {
                        "min_stickers_price": 200.0
                    }
                }
                logger.info("📋 Используем фильтры по умолчанию (min_stickers_price: $200.00)")
        
        # Создаем фильтры из словаря
        stickers_filter = None
        if filters_dict.get('stickers_filter'):
            sf = filters_dict['stickers_filter']
            stickers_filter = StickersFilter(
                min_stickers_price=sf.get('min_stickers_price'),
                max_overpay_coefficient=sf.get('max_overpay_coefficient'),
                total_stickers_price_min=sf.get('total_stickers_price_min'),
                total_stickers_price_max=sf.get('total_stickers_price_max')
            )
        
        filters = SearchFilters(
            item_name=filters_dict.get('item_name', 'AK-47 | Redline (Minimal Wear)'),
            appid=filters_dict.get('appid', 730),
            currency=filters_dict.get('currency', 1),
            max_price=filters_dict.get('max_price', 1000.0),
            stickers_filter=stickers_filter
        )
        
        # Создаем новую задачу 16
        logger.info("➕ Создаем новую задачу 16...")
        
        # Создаем задачу напрямую с ID 16
        new_task = MonitoringTask(
            id=16,
            name=filters_dict.get('task_name', 'Проверка на стоимость'),
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
        
        logger.info("✅ Задача 16 создана успешно!")
        logger.info(f"   ID: {new_task.id}")
        logger.info(f"   Название: {new_task.name}")
        logger.info(f"   Предмет: {new_task.item_name}")
        logger.info(f"   Макс. цена: ${filters.max_price:.2f}")
        
        if filters.stickers_filter:
            if filters.stickers_filter.min_stickers_price is not None:
                logger.info(f"   Минимальная цена наклеек: ${filters.stickers_filter.min_stickers_price:.2f}")
            if filters.stickers_filter.max_overpay_coefficient is not None:
                logger.info(f"   Максимальный коэффициент переплаты: {filters.stickers_filter.max_overpay_coefficient}")
        
        logger.info(f"   Интервал проверки: {new_task.check_interval} сек")
        logger.info(f"   Активна: {new_task.is_active}")
        
        # Очищаем флаг выполнения в Redis
        if redis_service and redis_service.is_connected():
            try:
                task_running_key = f"parsing_task_running:16"
                await redis_service._client.delete(task_running_key)
                logger.info("🔓 Очищен флаг выполнения задачи 16 в Redis")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось очистить флаг выполнения: {e}")
        
        logger.info("")
        logger.info("✅ Задача 16 перезапущена! Парсер начнет работу автоматически.")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при перезапуске задачи 16: {e}")
        import traceback
        traceback.print_exc()
        await session.rollback()
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(restart_task_16())

