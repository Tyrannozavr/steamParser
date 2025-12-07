"""
Скрипт для тестирования отправки уведомлений в Telegram.
Симулирует полный цикл: сохранение предмета -> публикация в Redis -> отправка в Telegram.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, FoundItem
from services import ResultsProcessorService, RedisService
from core.logger import get_task_logger
from loguru import logger
from core.config import Config


async def test_telegram_notification():
    """Тестирует отправку уведомления в Telegram."""
    
    logger.info("🚀 Начинаем тест отправки уведомлений в Telegram...")
    
    # Инициализируем БД
    db_manager = DatabaseManager()
    await db_manager.initialize()
    
    # Инициализируем Redis
    redis_service = RedisService()
    await redis_service.initialize()
    
    try:
        # Получаем активную задачу (или создаем тестовую)
        async with db_manager.get_session() as session:
            from sqlalchemy import select
            
            # Ищем активную задачу
            result = await session.execute(
                select(MonitoringTask)
                .where(MonitoringTask.is_active == True)
                .limit(1)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                logger.error("❌ Не найдено активных задач. Создайте задачу через Telegram бота.")
                return
            
            logger.info(f"✅ Найдена задача: {task.name} (ID: {task.id})")
            
            # Создаем тестовый предмет, который прошел фильтры
            test_item = {
                "name": "AK-47 | Redline (Field-Tested)",
                "asset_description": {
                    "market_hash_name": "AK-47 | Redline (Field-Tested)"
                },
                "sell_price_text": "$45.73",
                "listingid": "765177620331184862",
                "parsed_data": {
                    "item_price": 45.73,
                    "float_value": 0.350107,
                    "pattern": 522,
                    "stickers": [],
                    "listing_id": "765177620331184862",
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
            
            # Получаем task_logger
            task_logger = get_task_logger(task.id)
            
            # Обрабатываем предмет (сохраняет в БД и публикует в Redis)
            logger.info("💾 Сохраняем предмет в БД и публикуем уведомление в Redis...")
            found_count = await results_processor.process_results(
                task=task,
                items=[test_item],
                task_logger=task_logger
            )
            
            logger.info(f"✅ Обработано предметов: {found_count}")
            
            if found_count > 0:
                logger.info("✅ Предмет сохранен в БД")
                logger.info("📤 Уведомление опубликовано в Redis канал 'found_items'")
                logger.info("⏳ Ожидаем обработки уведомления Telegram ботом...")
                logger.info("")
                logger.info("🔔 Проверьте Telegram - должно прийти уведомление о найденном предмете!")
                logger.info("")
                logger.info("💡 Если уведомление не пришло:")
                logger.info("   1. Убедитесь, что Telegram бот запущен")
                logger.info("   2. Проверьте, что бот подписан на канал 'found_items'")
                logger.info("   3. Проверьте логи бота на наличие ошибок")
            else:
                logger.warning("⚠️ Предмет не был сохранен (возможно, дубликат)")
                
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()
        if redis_service:
            await redis_service.close()


if __name__ == "__main__":
    asyncio.run(test_telegram_notification())

