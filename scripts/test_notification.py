#!/usr/bin/env python3
"""
Скрипт для тестирования системы уведомлений.
Создает тестовый найденный предмет и отправляет уведомление.
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, FoundItem, MonitoringTask
from services.redis_service import RedisService
from core.config import Config
from loguru import logger
from sqlalchemy import select

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔔 Тестируем систему уведомлений...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    try:
        # Получаем активную задачу (любую активную)
        task_result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.is_active == True).limit(1)
        )
        task = task_result.scalar_one_or_none()
        
        if not task:
            logger.error("❌ Активная задача не найдена. Создайте задачу через Telegram бота.")
            return
        
        logger.info(f"✅ Найдена задача: {task.name} (ID: {task.id})")
        
        # Создаем тестовый найденный предмет
        test_item_data = {
            "float_value": 0.18,
            "pattern": 372,
            "stickers": [],
            "total_stickers_price": 0.0,
            "item_name": "AK-47 | Redline (Field-Tested)",
            "item_price": 45.50,
            "inspect_links": [],
            "item_type": "skin",
            "is_stattrak": False,
            "listing_id": 999999999999999999  # Тестовый ID
        }
        
        found_item = FoundItem(
            task_id=task.id,
            item_name="AK-47 | Redline (Field-Tested)",
            price=45.50,
            item_data_json=json.dumps(test_item_data, ensure_ascii=False),
            market_url="AK-47 | Redline (Field-Tested)",
            notification_sent=False
        )
        
        session.add(found_item)
        await session.commit()
        
        logger.info(f"✅ Создан тестовый предмет: ID={found_item.id}, цена=${found_item.price:.2f}")
        
        # Публикуем уведомление в Redis
        notification_data = {
            "type": "found_item",
            "item_id": found_item.id,
            "task_id": task.id,
            "item_name": found_item.item_name,
            "price": found_item.price,
            "market_url": found_item.market_url,
            "item_data_json": found_item.item_data_json,
            "task_name": task.name
        }
        
        logger.info(f"📤 Публикуем уведомление в Redis канал 'found_items'...")
        await redis_service.publish("found_items", notification_data)
        logger.info(f"✅ Уведомление опубликовано в Redis")
        logger.info(f"")
        logger.info(f"🔔 Проверьте Telegram бота - должно прийти уведомление о найденном предмете")
        logger.info(f"   Предмет: {found_item.item_name}")
        logger.info(f"   Цена: ${found_item.price:.2f}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

