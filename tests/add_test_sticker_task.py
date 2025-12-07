"""
Скрипт для добавления тестовой задачи с фильтром по наклейкам для проверки исправлений.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.database import DatabaseManager
from core.config import Config
from core.models import SearchFilters, StickersFilter
from sqlalchemy import select
from core.database import MonitoringTask
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")


async def add_test_task():
    """Добавляет тестовую задачу для проверки проблем с наклейками."""
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    try:
        # Проверяем, есть ли уже тестовая задача
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.name == "Тест наклеек (проверка исправлений)")
        )
        existing_task = result.scalar_one_or_none()
        
        if existing_task:
            logger.info(f"✅ Тестовая задача уже существует: ID={existing_task.id}")
            logger.info(f"   Название: {existing_task.name}")
            logger.info(f"   Предмет: {existing_task.item_name}")
            logger.info(f"   Активна: {existing_task.is_active}")
            await session.close()
            await db_manager.close()
            return
        
        # Создаем фильтры с проблемными параметрами из логов
        filters = SearchFilters(
            appid=730,
            currency=1,
            item_name="AK-47 | Redline (Minimal Wear)",
            stickers_filter=StickersFilter(
                min_stickers_price=20.0,  # Минимальная цена наклеек $20
                max_overpay_coefficient=1.0  # Максимальный коэффициент переплаты 1.0 (100%)
            )
        )
        
        # Создаем задачу
        task = MonitoringTask(
            name="Тест наклеек (проверка исправлений)",
            item_name="AK-47 | Redline (Minimal Wear)",
            filters_json=filters.model_dump(),
            is_active=True,
            check_interval=300  # 5 минут
        )
        
        session.add(task)
        await session.commit()
        
        logger.info(f"✅ Тестовая задача создана: ID={task.id}")
        logger.info(f"   Название: {task.name}")
        logger.info(f"   Предмет: {task.item_name}")
        logger.info(f"   Фильтры:")
        logger.info(f"     - min_stickers_price: ${filters.stickers_filter.min_stickers_price:.2f}")
        logger.info(f"     - max_overpay_coefficient: {filters.stickers_filter.max_overpay_coefficient}")
        logger.info(f"   Активна: {task.is_active}")
        logger.info(f"   Интервал проверки: {task.check_interval} сек")
        logger.info(f"\n📋 Эта задача поможет проверить:")
        logger.info(f"   1. Валидацию подозрительно низких цен наклеек")
        logger.info(f"   2. Валидацию подозрительно низкой базовой цены")
        logger.info(f"   3. Правильный расчет коэффициента переплаты")
        logger.info(f"   4. Обработку отсутствующих цен наклеек")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании задачи: {e}")
        await session.rollback()
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(add_test_task())

