#!/usr/bin/env python3
"""
Простой скрипт для тестирования отправки уведомлений в Telegram.
Использует ResultsProcessorService для полной симуляции процесса.
"""
import asyncio
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask
from services import ResultsProcessorService
from services.redis_service import RedisService
from core.config import Config
from loguru import logger
from sqlalchemy import select

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def main():
    """Основная функция."""
    logger.info("🔔 Тестируем отправку уведомлений в Telegram...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    try:
        # Получаем активную задачу
        task_result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.is_active == True).limit(1)
        )
        task = task_result.scalar_one_or_none()
        
        if not task:
            logger.error("❌ Активная задача не найдена. Создайте задачу через Telegram бота.")
            return
        
        logger.info(f"✅ Найдена задача: {task.name} (ID: {task.id})")
        
        # Создаем тестовый предмет, который прошел фильтры
        test_item = {
            "name": "AK-47 | Redline (Field-Tested)",
            "asset_description": {
                "market_hash_name": "AK-47 | Redline (Field-Tested)"
            },
            "sell_price_text": "$45.73",
            "listingid": f"TEST_{asyncio.get_event_loop().time()}",
            "parsed_data": {
                "item_price": 45.73,
                "float_value": 0.350107,
                "pattern": 522,
                "stickers": [],
                "listing_id": f"TEST_{asyncio.get_event_loop().time()}",
                "item_name": "AK-47 | Redline (Field-Tested)",
                "item_type": "weapon",
                "is_stattrak": False
            }
        }
        
        logger.info(f"📦 Создаем тестовый предмет: {test_item['name']} (${test_item['parsed_data']['item_price']:.2f})")
        
        # Создаем ResultsProcessorService
        results_processor = ResultsProcessorService(
            db_session=session,
            redis_service=redis_service
        )
        
        # Обрабатываем предмет (сохраняет в БД и публикует в Redis)
        logger.info("💾 Сохраняем предмет в БД и публикуем уведомление в Redis...")
        found_count = await results_processor.process_results(
            task=task,
            items=[test_item],
            task_logger=None
        )
        
        logger.info(f"✅ Обработано предметов: {found_count}")
        
        if found_count > 0:
            logger.info("✅ Предмет сохранен в БД")
            logger.info("📤 Уведомление опубликовано в Redis канал 'found_items'")
            logger.info("")
            logger.info("🔔 Проверьте Telegram - должно прийти уведомление о найденном предмете!")
            logger.info(f"   Предмет: {test_item['name']}")
            logger.info(f"   Цена: ${test_item['parsed_data']['item_price']:.2f}")
            logger.info("")
            logger.info("💡 Если уведомление не пришло:")
            logger.info("   1. Убедитесь, что Telegram бот запущен")
            logger.info("   2. Проверьте, что бот подписан на канал 'found_items'")
            logger.info("   3. Проверьте логи бота на наличие ошибок")
        else:
            logger.warning("⚠️ Предмет не был сохранен (возможно, дубликат)")
            
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

