"""
Простой тест запроса цен наклеек и сохранения в БД.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, SearchFilters, FloatRange, PatternList
from core.models import ParsedItemData, StickerInfo
from core.steam_parser import SteamMarketParser
from services import MonitoringService
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.steam_market_parser.process_results import process_item_result
from core.config import Config
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

TASK_ID = 143
ITEM_NAME = "StatTrak™ AK-47 | Redline (Field-Tested)"
MAX_PRICE = 200.0
FLOAT_MIN = 0.300000
FLOAT_MAX = 0.400000
PATTERN = 875

async def test_sticker_prices():
    logger.info("🧪 Тестируем запрос цен наклеек и сохранение в БД...")
    
    db_manager = DatabaseManager()
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    proxy_manager = ProxyManager(db_session, redis_service=redis_service)
    
    # Создаем парсер
    parser = SteamMarketParser(
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    monitoring_service = MonitoringService(db_session, None, None, None, redis_service)
    
    try:
        # 1. Удаляем старую задачу, если существует
        existing_task = await db_session.get(MonitoringTask, TASK_ID)
        if existing_task:
            logger.info(f"🗑️ Удаляем существующую задачу {TASK_ID}...")
            await monitoring_service.delete_monitoring_task(TASK_ID)
            logger.info(f"✅ Задача {TASK_ID} удалена.")
        
        # 2. Создаем новую задачу
        logger.info(f"➕ Создаем новую задачу {TASK_ID}...")
        
        filters = SearchFilters(
            item_name=ITEM_NAME,
            max_price=MAX_PRICE,
            float_range=FloatRange(min=FLOAT_MIN, max=FLOAT_MAX),
            pattern_list=PatternList(patterns=[PATTERN], item_type="skin")
        )
        
        new_task = await monitoring_service.add_monitoring_task(
            name=f"{ITEM_NAME} - Паттерн {PATTERN} (Sticker Test)",
            item_name=ITEM_NAME,
            filters=filters,
            check_interval=10
        )
        
        # Устанавливаем нужный ID
        if new_task.id != TASK_ID:
            # Удаляем старую задачу с нужным ID, если есть
            old_task = await db_session.get(MonitoringTask, TASK_ID)
            if old_task:
                await db_session.delete(old_task)
            # Обновляем ID новой задачи
            await db_session.execute(
                f"UPDATE monitoring_tasks SET id = {TASK_ID} WHERE id = {new_task.id}"
            )
            await db_session.commit()
            new_task.id = TASK_ID
            await db_session.refresh(new_task)
        
        if new_task:
            logger.info(f"✅ Задача {new_task.id} успешно создана.")
            
            # 3. Создаем тестовые данные с наклейками
            stickers = [
                StickerInfo(position=0, name='Team Liquid (Holo) | Stockholm 2021', wear='Team Liquid (Holo) | Stockholm 2021', price=None),
                StickerInfo(position=1, name='Team Liquid (Holo) | Stockholm 2021', wear='Team Liquid (Holo) | Stockholm 2021', price=None),
                StickerInfo(position=2, name='Team Liquid (Holo) | Stockholm 2021', wear='Team Liquid (Holo) | Stockholm 2021', price=None),
                StickerInfo(position=3, name='Team Liquid (Holo) | Stockholm 2021', wear='Team Liquid (Holo) | Stockholm 2021', price=None),
                StickerInfo(position=4, name='Team Liquid (Holo) | Stockholm 2021', wear='Team Liquid (Holo) | Stockholm 2021', price=None),
            ]
            
            parsed_data = ParsedItemData(
                float_value=0.321177,
                pattern=875,
                stickers=stickers,
                total_stickers_price=0.0,
                item_name=ITEM_NAME,
                item_price=115.73,
                listing_id='test_sticker_123'
            )
            
            logger.info(f"📋 Тестируем с {len(stickers)} наклейками")
            logger.info(f"   Парсер имеет метод get_stickers_prices: {hasattr(parser, 'get_stickers_prices')}")
            
            # 4. Тестируем process_item_result
            result = await process_item_result(
                parser=parser,
                task=new_task,
                parsed_data=parsed_data,
                filters=filters,
                db_session=db_session,
                redis_service=redis_service
            )
            
            logger.info(f"✅ Результат process_item_result: {result}")
            logger.info(f"💰 Общая цена наклеек в parsed_data: ${parsed_data.total_stickers_price:.2f}")
            for i, s in enumerate(parsed_data.stickers):
                logger.info(f"   Наклейка {i+1}: name={s.name}, price={s.price}")
            
            # 5. Проверяем, что сохранено в БД
            from core import FoundItem
            from sqlalchemy import select
            items = await db_session.execute(
                select(FoundItem).where(FoundItem.task_id == new_task.id)
            )
            found_items = items.scalars().all()
            
            if found_items:
                found_item = found_items[0]
                import json
                data = json.loads(found_item.item_data_json)
                total_price = data.get('total_stickers_price', 0)
                stickers_data = data.get('stickers', [])
                logger.info(f"📊 В БД сохранено:")
                logger.info(f"   total_stickers_price: ${total_price:.2f}")
                logger.info(f"   stickers count: {len(stickers_data)}")
                for i, s in enumerate(stickers_data):
                    logger.info(f"   Sticker {i+1}: name={s.get('name')}, price={s.get('price')}")
            else:
                logger.warning("⚠️ Предмет не найден в БД")
                
    except Exception as e:
        logger.exception(f"❌ Ошибка: {e}")
    finally:
        await db_session.close()
        await redis_service.disconnect()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_sticker_prices())

