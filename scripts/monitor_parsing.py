#!/usr/bin/env python3
"""
Скрипт для мониторинга процесса парсинга.
Проверяет каждые 2 минуты, что парсинг работает и не завис.
"""
import asyncio
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from core.database import DatabaseManager, MonitoringTask, FoundItem
from core.config import Config
from sqlalchemy import select, func, desc


async def check_parsing_status(task_id: int, session):
    """Проверяет статус парсинга задачи."""
    # Получаем задачу
    task = await session.get(MonitoringTask, task_id)
    if not task:
        logger.error(f"❌ Задача {task_id} не найдена")
        return False
    
    # Подсчитываем найденные предметы
    items_count_result = await session.execute(
        select(func.count(FoundItem.id))
        .where(FoundItem.task_id == task_id)
    )
    items_count = items_count_result.scalar()
    
    # Получаем последний найденный предмет
    last_item_result = await session.execute(
        select(FoundItem)
        .where(FoundItem.task_id == task_id)
        .order_by(desc(FoundItem.found_at))
        .limit(1)
    )
    last_item = last_item_result.scalar_one_or_none()
    
    # Получаем статистику задачи
    logger.info("=" * 70)
    logger.info(f"📊 Статус задачи #{task_id}: {task.name}")
    logger.info(f"   Предмет: {task.item_name}")
    logger.info(f"   Активна: {'✅' if task.is_active else '❌'}")
    logger.info(f"   Всего проверок: {task.total_checks}")
    logger.info(f"   Найдено предметов: {items_count}")
    logger.info(f"   Последняя проверка: {task.last_check.isoformat() if task.last_check else 'Никогда'}")
    logger.info(f"   Следующая проверка: {task.next_check.isoformat() if task.next_check else 'Не запланирована'}")
    
    if last_item:
        item_data = last_item.get_item_data()
        logger.info(f"   Последний найденный предмет:")
        logger.info(f"      - ID: {last_item.id}")
        logger.info(f"      - Цена: ${last_item.price:.2f}")
        logger.info(f"      - Float: {item_data.get('float_value', 'N/A')}")
        logger.info(f"      - Паттерн: {item_data.get('pattern', 'N/A')}")
        logger.info(f"      - Найден: {last_item.found_at.isoformat()}")
    else:
        logger.info(f"   ⏳ Предметы еще не найдены")
    
    # Проверяем, не завис ли парсинг
    if task.last_check:
        time_since_check = datetime.now() - task.last_check
        if time_since_check > timedelta(minutes=10):
            logger.warning(f"⚠️ ВНИМАНИЕ: Последняя проверка была {time_since_check.total_seconds()/60:.1f} минут назад!")
            logger.warning(f"   Парсинг может зависнуть. Проверьте логи parsing_worker.")
        else:
            logger.info(f"✅ Парсинг активен (последняя проверка {time_since_check.total_seconds()/60:.1f} мин назад)")
    else:
        logger.warning(f"⚠️ Задача еще не выполнялась")
    
    logger.info("=" * 70)
    
    return True


async def main():
    """Основная функция мониторинга."""
    import sys
    
    if len(sys.argv) < 2:
        logger.error("❌ Укажите ID задачи для мониторинга")
        logger.info("   Использование: python monitor_parsing.py <task_id>")
        logger.info("   Пример: python monitor_parsing.py 1")
        return
    
    try:
        task_id = int(sys.argv[1])
    except ValueError:
        logger.error(f"❌ Неверный ID задачи: {sys.argv[1]}")
        return
    
    logger.info(f"🔍 Начинаем мониторинг задачи #{task_id}")
    logger.info(f"   Проверка каждые 2 минуты")
    logger.info(f"   Для остановки нажмите Ctrl+C")
    logger.info("")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    try:
        # Первая проверка
        await check_parsing_status(task_id, session)
        
        # Цикл мониторинга
        check_count = 1
        while True:
            await asyncio.sleep(120)  # Ждем 2 минуты
            check_count += 1
            
            logger.info(f"")
            logger.info(f"🔄 Проверка #{check_count} ({datetime.now().strftime('%H:%M:%S')})")
            
            # Обновляем сессию для получения актуальных данных
            await session.commit()  # Сбрасываем кэш
            await check_parsing_status(task_id, session)
            
    except KeyboardInterrupt:
        logger.info("")
        logger.info("⏹️ Мониторинг остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Ошибка при мониторинге: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
    finally:
        await session.close()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

