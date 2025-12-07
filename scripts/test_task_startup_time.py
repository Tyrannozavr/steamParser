"""
Тест скорости запуска задачи - засекаем время от создания до начала выполнения.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, SearchFilters, FloatRange, PatternList
from services import MonitoringService
from services.redis_service import RedisService
from core.config import Config
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

TASK_ID = 144
ITEM_NAME = "AK-47 | Redline (Field-Tested)"
MAX_PRICE = 50.0
FLOAT_MIN = 0.350000
FLOAT_MAX = 0.360000
PATTERN = 522

async def test_task_startup_time():
    logger.info("⏱️ Тестируем скорость запуска задачи...")
    
    db_manager = DatabaseManager()
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    monitoring_service = MonitoringService(db_session, None, None, None, redis_service)
    
    try:
        # 1. Удаляем старую задачу, если существует
        existing_task = await db_session.get(MonitoringTask, TASK_ID)
        if existing_task:
            logger.info(f"🗑️ Удаляем существующую задачу {TASK_ID}...")
            await monitoring_service.delete_monitoring_task(TASK_ID)
            logger.info(f"✅ Задача {TASK_ID} удалена.")
            await asyncio.sleep(1)  # Небольшая задержка
        
        # 2. Засекаем время создания задачи
        logger.info(f"➕ Создаем новую задачу {TASK_ID}...")
        creation_start = datetime.now()
        
        filters = SearchFilters(
            item_name=ITEM_NAME,
            max_price=MAX_PRICE,
            float_range=FloatRange(min=FLOAT_MIN, max=FLOAT_MAX),
            pattern_list=PatternList(patterns=[PATTERN], item_type="skin")
        )
        
        new_task = await monitoring_service.add_monitoring_task(
            name=f"{ITEM_NAME} - Паттерн {PATTERN} (Startup Test)",
            item_name=ITEM_NAME,
            filters=filters,
            check_interval=10
        )
        
        creation_end = datetime.now()
        creation_time = (creation_end - creation_start).total_seconds()
        logger.info(f"✅ Задача {new_task.id} создана за {creation_time:.3f} сек")
        
        # 3. Добавляем задачу в очередь Redis вручную (как делает MonitoringService)
        task_data = {
            "type": "parsing_task",
            "task_id": new_task.id,
            "action": "parse"
        }
        push_start = datetime.now()
        await redis_service.push_to_queue("parsing_tasks", task_data)
        push_end = datetime.now()
        push_time = (push_end - push_start).total_seconds()
        logger.info(f"📤 Задача добавлена в очередь Redis за {push_time:.3f} сек")
        
        # 4. Мониторим логи воркера, чтобы понять, когда задача начала выполняться
        logger.info("👀 Ожидаем начала выполнения задачи воркером (макс. 120 сек)...")
        logger.info("   Проверяем логи воркера каждые 2 секунды...")
        
        start_time = datetime.now()
        max_wait = 120  # Максимальное время ожидания
        check_interval = 2  # Проверяем каждые 2 секунды
        
        task_started = False
        task_start_time = None
        
        while (datetime.now() - start_time).total_seconds() < max_wait:
            # Проверяем, появился ли флаг выполнения в Redis
            task_running_key = f"parsing_task_running:{new_task.id}"
            flag_exists = await redis_service._client.get(task_running_key)
            
            if flag_exists:
                task_start_time = datetime.now()
                task_started = True
                logger.info(f"🎯 Флаг выполнения установлен в Redis!")
                break
            
            await asyncio.sleep(check_interval)
        
        if task_started:
            total_time = (task_start_time - creation_start).total_seconds()
            queue_to_start_time = (task_start_time - push_end).total_seconds()
            
            logger.info("=" * 60)
            logger.info("📊 РЕЗУЛЬТАТЫ ИЗМЕРЕНИЯ ВРЕМЕНИ:")
            logger.info("=" * 60)
            logger.info(f"⏱️  Время создания задачи: {creation_time:.3f} сек")
            logger.info(f"⏱️  Время добавления в очередь: {push_time:.3f} сек")
            logger.info(f"⏱️  Время от добавления в очередь до начала выполнения: {queue_to_start_time:.3f} сек")
            logger.info(f"⏱️  ОБЩЕЕ ВРЕМЯ от создания до начала выполнения: {total_time:.3f} сек ({total_time:.1f} сек)")
            logger.info("=" * 60)
            
            if total_time > 10:
                logger.warning(f"⚠️  Задержка значительная: {total_time:.1f} сек")
            elif total_time > 5:
                logger.warning(f"⚠️  Задержка заметная: {total_time:.1f} сек")
            else:
                logger.success(f"✅ Задача начала выполняться быстро: {total_time:.1f} сек")
        else:
            logger.error(f"❌ Задача не начала выполняться в течение {max_wait} секунд")
            logger.info("   Возможные причины:")
            logger.info("   - Воркеры заняты другими задачами")
            logger.info("   - Воркеры не запущены")
            logger.info("   - Проблемы с подключением к Redis")
            
            # Проверяем длину очереди
            queue_length = await redis_service._client.llen("parsing_tasks")
            logger.info(f"   Длина очереди 'parsing_tasks': {queue_length}")
            
            # Проверяем активные флаги
            running_keys = await redis_service._client.keys("parsing_task_running:*")
            logger.info(f"   Активных задач (флаги): {len(running_keys)}")
            
    except Exception as e:
        logger.exception(f"❌ Ошибка: {e}")
    finally:
        await db_session.close()
        await redis_service.disconnect()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(test_task_startup_time())

