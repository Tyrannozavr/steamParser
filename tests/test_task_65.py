#!/usr/bin/env python3
"""
Тестовый скрипт для проверки задачи 65 (StatTrak™ AK-47 | Redline (Minimal Wear)).
Добавляет задачу и проверяет, что все 9 лотов найдены.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from core import DatabaseManager, MonitoringTask, SearchFilters
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.config import Config
from loguru import logger
from sqlalchemy import select
import json


async def main():
    """Основная функция."""
    logger.info("🔍 Тестирую задачу 65: StatTrak™ AK-47 | Redline (Minimal Wear)")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Инициализация Redis
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        
        # Инициализация ProxyManager
        proxy_manager = ProxyManager(session, redis_service=redis_service)
        proxy_manager.start_background_proxy_check()
        
        # Проверяем, существует ли задача 65
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.id == 65)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            logger.error("❌ Задача 65 не найдена в БД")
            return
        
        logger.info(f"✅ Задача найдена: {task.item_name}, активна: {task.is_active}")
        logger.info(f"   Фильтры: {task.filters_json}")
        
        # Проверяем, что задача активна
        if not task.is_active:
            logger.warning("⚠️ Задача неактивна, активирую...")
            task.is_active = True
            await session.commit()
        
        # Публикуем задачу в Redis для парсинга
        logger.info("📤 Публикую задачу в Redis...")
        task_data = {
            "task_id": task.id,
            "item_name": task.item_name,
            "filters": task.filters_json
        }
        await redis_service.push_to_queue("parsing_tasks", task_data)
        logger.info("✅ Задача опубликована в Redis")
        
        # Ждем немного, чтобы задача обработалась
        logger.info("⏳ Ждем 10 секунд для обработки задачи...")
        await asyncio.sleep(10)
        
        # Проверяем результаты в Redis
        logger.info("🔍 Проверяю результаты в Redis...")
        found_items = await redis_service.pop_from_queue("found_items", timeout=1)
        
        if found_items:
            logger.info(f"✅ Найдено предметов: {len(found_items.get('items', []))}")
            for item in found_items.get('items', [])[:10]:  # Показываем первые 10
                logger.info(f"   - {item.get('name', 'Unknown')}: ${item.get('price', 0):.2f}")
        else:
            logger.warning("⚠️ Результаты не найдены в Redis")
        
        # Проверяем статистику задачи
        await session.refresh(task)
        logger.info(f"📊 Статистика задачи: проверок={task.checks_count}, найдено={task.found_count}")
        
        if task.found_count >= 9:
            logger.info("✅ УСПЕХ: Найдено 9 или более предметов!")
        else:
            logger.warning(f"⚠️ Найдено только {task.found_count} предметов, ожидалось 9")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}", exc_info=True)
    finally:
        await session.close()
        await db_manager.close()
        if redis_service:
            await redis_service.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
