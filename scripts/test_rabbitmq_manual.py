"""
Скрипт для ручного тестирования RabbitMQ.
Добавляет несколько задач и проверяет их выполнение.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Config, DatabaseManager, MonitoringTask, SearchFilters
from services.rabbitmq_service import RabbitMQService
from services.monitoring_service import MonitoringService
from services.proxy_manager_factory import ProxyManagerFactory
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)


async def test_rabbitmq_manual():
    """Ручное тестирование RabbitMQ с реальными задачами."""
    logger.info("=" * 80)
    logger.info("🧪 РУЧНОЕ ТЕСТИРОВАНИЕ RABBITMQ")
    logger.info("=" * 80)
    
    # Инициализация
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    try:
        # Инициализируем RabbitMQ
        logger.info("📡 Подключаемся к RabbitMQ...")
        rabbitmq_service = RabbitMQService(rabbitmq_url=Config.RABBITMQ_URL)
        await rabbitmq_service.connect()
        logger.info("✅ RabbitMQ подключен")
        
        # Инициализируем ProxyManager (для MonitoringService)
        proxy_manager = await ProxyManagerFactory.get_instance(
            db_session=db_session,
            redis_service=None,
            default_delay=0.2,
            site="steam"
        )
        
        # Инициализируем MonitoringService
        monitoring_service = MonitoringService(
            db_session=db_session,
            proxy_manager=proxy_manager,
            notification_callback=None,
            redis_service=None,
            rabbitmq_service=rabbitmq_service,
            db_manager=db_manager
        )
        
        # Создаем несколько тестовых задач
        logger.info("\n📋 Создаем тестовые задачи...")
        test_tasks = []
        
        for i in range(3):
            filters = SearchFilters(
                item_name=f"AK-47 | Redline (Test {i+1})",
                appid=730,
                currency=1
            )
            
            task = await monitoring_service.add_monitoring_task(
                name=f"Test Task {i+1}",
                item_name=f"AK-47 | Redline",
                filters=filters,
                check_interval=30  # 30 секунд для быстрого тестирования
            )
            
            test_tasks.append(task)
            logger.info(f"✅ Создана задача #{task.id}: {task.name}")
        
        logger.info(f"\n✅ Создано {len(test_tasks)} задач")
        logger.info("\n⏳ Ожидаем выполнения задач...")
        logger.info("   Задачи должны выполняться каждые 30 секунд")
        logger.info("   Проверьте логи parsing-worker для подтверждения выполнения")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        # Ждем выполнения задач
        try:
            await asyncio.sleep(300)  # Ждем 5 минут для нескольких итераций
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановка тестирования...")
        
        # Получаем статистику
        logger.info("\n📊 Статистика задач:")
        stats = await monitoring_service.get_statistics()
        for task_info in stats["tasks"]:
            if task_info["id"] in [t.id for t in test_tasks]:
                logger.info(
                    f"   Задача #{task_info['id']}: "
                    f"проверок={task_info['total_checks']}, "
                    f"найдено={task_info['items_found']}, "
                    f"последняя проверка={task_info['last_check']}"
                )
        
        # Удаляем тестовые задачи
        logger.info("\n🗑️ Удаляем тестовые задачи...")
        for task in test_tasks:
            await monitoring_service.delete_monitoring_task(task.id)
            logger.info(f"✅ Удалена задача #{task.id}")
        
        logger.info("\n✅ Тестирование завершено")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        if db_session:
            await db_session.close()
        if db_manager:
            await db_manager.close()
        logger.info("🔌 Соединения закрыты")


if __name__ == "__main__":
    asyncio.run(test_rabbitmq_manual())
