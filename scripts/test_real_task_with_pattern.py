#!/usr/bin/env python3
"""
Скрипт для тестирования реальной задачи с паттерном из БД.
Находит задачу с паттерном, запускает парсинг и проверяет результаты.
"""
import asyncio
import sys
import json
import random
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from core import DatabaseManager, MonitoringTask, FoundItem
from services.parsing_service import ParsingService
from services.proxy_manager_factory import ProxyManagerFactory
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def find_task_with_pattern(db_session):
    """Находит задачу с паттерном из БД."""
    logger.info("🔍 Ищем задачу с паттерном...")
    
    # Получаем все активные задачи
    result = await db_session.execute(
        select(MonitoringTask)
        .where(MonitoringTask.is_active == True)
        .order_by(MonitoringTask.id)
    )
    tasks = result.scalars().all()
    
    if not tasks:
        logger.error("❌ Нет активных задач в БД")
        return None
    
    logger.info(f"📋 Найдено {len(tasks)} активных задач")
    
    # Ищем задачи с паттернами
    tasks_with_patterns = []
    for task in tasks:
        try:
            filters_json = task.filters_json
            if isinstance(filters_json, str):
                filters_json = json.loads(filters_json)
            
            # Проверяем, есть ли паттерны
            if isinstance(filters_json, dict):
                pattern_list = filters_json.get('pattern_list')
                if pattern_list and isinstance(pattern_list, dict):
                    patterns = pattern_list.get('patterns', [])
                    if patterns:
                        tasks_with_patterns.append((task, patterns))
        except Exception as e:
            logger.debug(f"⚠️ Ошибка при проверке задачи {task.id}: {e}")
            continue
    
    if not tasks_with_patterns:
        logger.warning("⚠️ Не найдено задач с паттернами, используем первую задачу")
        return tasks[0], None
    
    # Выбираем случайную задачу с паттерном
    task, patterns = random.choice(tasks_with_patterns)
    logger.info(f"✅ Выбрана задача ID={task.id}: '{task.name}'")
    logger.info(f"   Предмет: {task.item_name}")
    logger.info(f"   Паттерны: {patterns}")
    logger.info(f"   Проверок: {task.total_checks}, Найдено: {task.items_found}")
    
    return task, patterns


async def run_parsing_test(task: MonitoringTask, db_session, redis_service, proxy_manager):
    """Запускает парсинг для задачи и проверяет результаты."""
    logger.info("=" * 70)
    logger.info(f"🚀 ЗАПУСК ПАРСИНГА для задачи {task.id}")
    logger.info("=" * 70)
    
    # Загружаем задачу заново для получения актуальных данных
    await db_session.refresh(task)
    
    initial_checks = task.total_checks
    initial_found = task.items_found
    initial_last_check = task.last_check
    
    logger.info(f"📊 Начальное состояние:")
    logger.info(f"   Проверок: {initial_checks}")
    logger.info(f"   Найдено: {initial_found}")
    logger.info(f"   Последняя проверка: {initial_last_check}")
    
    # Создаем ParsingService
    parsing_service = ParsingService(
        db_session=db_session,
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    # Подготавливаем фильтры
    from core.models import SearchFilters
    filters_json = task.filters_json
    if isinstance(filters_json, str):
        filters_json = json.loads(filters_json)
    
    filters = SearchFilters.model_validate(filters_json)
    filters.item_name = task.item_name
    
    logger.info(f"🔍 Начинаем парсинг для '{task.item_name}'...")
    logger.info(f"   Фильтры: паттерны={filters.pattern_list.patterns if filters.pattern_list else 'нет'}")
    
    start_time = datetime.now()
    
    try:
        # Запускаем парсинг
        result = await parsing_service.parse_items(
            item_name=task.item_name,
            filters=filters,
            appid=task.appid,
            currency=task.currency
        )
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info("=" * 70)
        logger.info(f"✅ ПАРСИНГ ЗАВЕРШЕН за {duration:.1f} секунд")
        logger.info("=" * 70)
        logger.info(f"📊 Результат:")
        logger.info(f"   Успех: {result.get('success', False)}")
        logger.info(f"   Всего найдено: {result.get('total', 0)}")
        logger.info(f"   После фильтрации: {result.get('filtered', 0)}")
        logger.info(f"   Предметов в результате: {len(result.get('items', []))}")
        
        # Проверяем обновление задачи в БД
        await db_session.refresh(task)
        
        final_checks = task.total_checks
        final_found = task.items_found
        final_last_check = task.last_check
        
        logger.info("=" * 70)
        logger.info(f"📊 ФИНАЛЬНОЕ СОСТОЯНИЕ ЗАДАЧИ:")
        logger.info("=" * 70)
        logger.info(f"   Проверок: {initial_checks} → {final_checks} (изменение: {final_checks - initial_checks:+d})")
        logger.info(f"   Найдено: {initial_found} → {final_found} (изменение: {final_found - initial_found:+d})")
        logger.info(f"   Последняя проверка: {initial_last_check} → {final_last_check}")
        logger.info(f"   next_check: {task.next_check}")
        
        # Проверяем, были ли найдены новые предметы
        if result.get('items'):
            logger.info(f"\n🎯 НАЙДЕНО {len(result['items'])} ПОДХОДЯЩИХ ПРЕДМЕТОВ:")
            for i, item in enumerate(result['items'][:5], 1):  # Показываем первые 5
                parsed_data = item.get('parsed_data', {})
                price = item.get('sell_price_text', 'N/A')
                pattern = parsed_data.get('pattern', 'N/A')
                float_val = parsed_data.get('float', 'N/A')
                logger.info(f"   {i}. Цена: {price}, Паттерн: {pattern}, Float: {float_val}")
            
            if len(result['items']) > 5:
                logger.info(f"   ... и еще {len(result['items']) - 5} предметов")
        
        # Проверяем, были ли сохранены предметы в БД
        found_items_result = await db_session.execute(
            select(FoundItem)
            .where(FoundItem.task_id == task.id)
            .order_by(FoundItem.found_at.desc())
            .limit(10)
        )
        recent_items = found_items_result.scalars().all()
        
        if recent_items:
            logger.info(f"\n💾 ПОСЛЕДНИЕ СОХРАНЕННЫЕ ПРЕДМЕТЫ В БД:")
            for item in recent_items[:5]:
                logger.info(f"   ID={item.id}: {item.item_name} (${item.price:.2f}), найдено: {item.found_at}")
        
        # Проверяем, что изменения сохранились
        if final_checks > initial_checks:
            logger.info(f"\n✅ Счетчик проверок обновлен: {initial_checks} → {final_checks}")
        else:
            logger.warning(f"\n⚠️ Счетчик проверок НЕ обновлен: {initial_checks} → {final_checks}")
        
        if final_last_check and final_last_check != initial_last_check:
            logger.info(f"✅ last_check обновлен: {initial_last_check} → {final_last_check}")
        else:
            logger.warning(f"⚠️ last_check НЕ обновлен")
        
        if task.next_check:
            logger.info(f"✅ next_check установлен: {task.next_check}")
        else:
            logger.warning(f"⚠️ next_check НЕ установлен")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка при парсинге: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def main():
    """Основная функция."""
    logger.info("=" * 70)
    logger.info("🧪 ТЕСТ РЕАЛЬНОЙ ЗАДАЧИ С ПАТТЕРНОМ")
    logger.info("=" * 70)
    
    # Инициализируем БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    try:
        # Инициализируем Redis
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        if Config.REDIS_ENABLED:
            await redis_service.connect()
            logger.info("✅ Redis подключен")
        else:
            logger.warning("⚠️ Redis отключен")
            redis_service = None
        
        # Инициализируем ProxyManager
        proxy_manager = await ProxyManagerFactory.get_instance(
            db_session=db_session,
            redis_service=redis_service
        )
        logger.info("✅ ProxyManager инициализирован")
        
        # Находим задачу с паттерном
        task_data = await find_task_with_pattern(db_session)
        if not task_data:
            logger.error("❌ Не удалось найти задачу для тестирования")
            return
        
        task, patterns = task_data
        
        # Запускаем парсинг
        result = await run_parsing_test(task, db_session, redis_service, proxy_manager)
        
        if result:
            logger.info("\n" + "=" * 70)
            logger.info("✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО")
            logger.info("=" * 70)
        else:
            logger.error("\n" + "=" * 70)
            logger.error("❌ ТЕСТ ЗАВЕРШЕН С ОШИБКАМИ")
            logger.error("=" * 70)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_session.close()
        await db_manager.close()
        if redis_service:
            await redis_service.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
