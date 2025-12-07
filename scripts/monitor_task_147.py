"""
Мониторинг выполнения задачи 147.
Проверяет, что задача выполняется и не зависла.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, FoundItem
from services.redis_service import RedisService
from core.config import Config
from loguru import logger
from sqlalchemy import select

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

TASK_ID = 147
MAX_WAIT_MINUTES = 15  # Максимальное время ожидания

async def monitor_task():
    logger.info(f"👀 Мониторинг задачи {TASK_ID}...")
    
    db_manager = DatabaseManager()
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    start_time = datetime.now()
    
    try:
        while True:
            elapsed = (datetime.now() - start_time).total_seconds() / 60
            
            if elapsed > MAX_WAIT_MINUTES:
                logger.error(f"❌ Превышено время ожидания ({MAX_WAIT_MINUTES} минут)")
                break
            
            # Проверяем задачу в БД
            task = await db_session.get(MonitoringTask, TASK_ID)
            if not task:
                logger.error(f"❌ Задача {TASK_ID} не найдена в БД")
                break
            
            # Проверяем флаг выполнения
            flag = await redis_service._client.get(f'parsing_task_running:{TASK_ID}')
            flag_status = "✅ Выполняется" if flag else "⏸️ Не выполняется"
            
            # Проверяем найденные предметы
            items_query = select(FoundItem).where(FoundItem.task_id == TASK_ID)
            items_result = await db_session.execute(items_query)
            found_items = items_result.scalars().all()
            
            logger.info(f"📊 Задача {TASK_ID} (прошло {elapsed:.1f} мин):")
            logger.info(f"   Статус: {flag_status}")
            logger.info(f"   Проверок: {task.total_checks}, Найдено: {task.items_found}")
            logger.info(f"   Предметов в БД: {len(found_items)}")
            
            # Проверяем файл логов
            from pathlib import Path
            log_file = Path(f"/app/logs/tasks/task_{TASK_ID}_{datetime.now().strftime('%Y-%m-%d')}.log")
            if log_file.exists():
                size = log_file.stat().st_size
                logger.info(f"   📄 Файл логов: существует ({size} байт)")
            else:
                logger.warning(f"   ⚠️ Файл логов: не найден")
            
            # Если задача завершилась (флаг снят и есть результаты)
            if not flag and task.total_checks > 0:
                logger.info(f"✅ Задача {TASK_ID} завершена!")
                logger.info(f"   Итоги: Проверок={task.total_checks}, Найдено={task.items_found}")
                if found_items:
                    logger.info(f"   Предметы в БД:")
                    for item in found_items[:5]:
                        logger.info(f"     - {item.item_name}: ${item.price:.2f}")
                break
            
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд
            
    except Exception as e:
        logger.exception(f"❌ Ошибка мониторинга: {e}")
    finally:
        await db_session.close()
        await redis_service.disconnect()
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(monitor_task())

