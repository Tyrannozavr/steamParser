#!/usr/bin/env python3
"""
Скрипт для проверки задачи 16 и анализа проблемы парсинга.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager, MonitoringTask, FoundItem
from core.config import Config
from sqlalchemy import select, desc, func
from loguru import logger
import json

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def check_task_16():
    """Проверяет задачу 16 и найденные предметы."""
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Получаем задачу 16
        task = await session.get(MonitoringTask, 16)
        
        if not task:
            logger.error("❌ Задача 16 не найдена в БД")
            return
        
        logger.info(f"📋 Задача 16: '{task.name}'")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Активна: {task.is_active}")
        logger.info(f"   Проверок: {task.total_checks}")
        logger.info(f"   Найдено: {task.items_found}")
        logger.info(f"   Последняя проверка: {task.last_check}")
        logger.info(f"   Следующая проверка: {task.next_check}")
        logger.info(f"   Интервал: {task.check_interval} сек")
        
        # Выводим фильтры
        if task.filters_json:
            filters = task.filters_json
            if isinstance(filters, str):
                filters = json.loads(filters)
            
            logger.info(f"\n📊 Фильтры задачи:")
            logger.info(f"   max_price: ${filters.get('max_price', 'N/A')}")
            
            if filters.get('stickers_filter'):
                sf = filters['stickers_filter']
                logger.info(f"   📊 Фильтры наклеек:")
                if sf.get('min_stickers_price') is not None:
                    logger.info(f"      - min_stickers_price: ${sf['min_stickers_price']:.2f}")
                if sf.get('max_overpay_coefficient') is not None:
                    logger.info(f"      - max_overpay_coefficient: {sf['max_overpay_coefficient']}")
                if sf.get('total_stickers_price_min') is not None:
                    logger.info(f"      - total_stickers_price_min: ${sf['total_stickers_price_min']:.2f}")
                if sf.get('total_stickers_price_max') is not None:
                    logger.info(f"      - total_stickers_price_max: ${sf['total_stickers_price_max']:.2f}")
        
        # Получаем все найденные предметы для задачи 16
        found_result = await session.execute(
            select(FoundItem)
            .where(FoundItem.task_id == 16)
            .order_by(desc(FoundItem.found_at))
        )
        found_items = list(found_result.scalars().all())
        
        logger.info(f"\n📦 Найдено предметов в БД: {len(found_items)}")
        
        if found_items:
            logger.info(f"\n📋 Последние 10 найденных предметов:")
            for i, item in enumerate(found_items[:10], 1):
                logger.info(f"   {i}. {item.item_name}: ${item.price:.2f} (найдено: {item.found_at})")
                if item.item_data_json:
                    try:
                        data = json.loads(item.item_data_json)
                        if data.get('stickers'):
                            stickers_price = sum(s.get('price', 0) for s in data['stickers'] if s.get('price'))
                            logger.info(f"      Наклейки: ${stickers_price:.2f}")
                    except:
                        pass
        
        # Статистика по ценам
        if found_items:
            prices = [item.price for item in found_items]
            logger.info(f"\n📊 Статистика по ценам:")
            logger.info(f"   Минимум: ${min(prices):.2f}")
            logger.info(f"   Максимум: ${max(prices):.2f}")
            logger.info(f"   Среднее: ${sum(prices)/len(prices):.2f}")
        
        # Проверяем, сколько предметов было найдено за последние 10 минут
        from datetime import datetime, timedelta
        ten_min_ago = datetime.now() - timedelta(minutes=10)
        recent_items = [item for item in found_items if item.found_at and item.found_at >= ten_min_ago]
        logger.info(f"\n⏰ Найдено за последние 10 минут: {len(recent_items)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(check_task_16())

