"""
Скрипт для тестирования поиска AK-47 | Nightwish.
Добавляет задачу и проверяет её выполнение через RabbitMQ.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Config, DatabaseManager, MonitoringTask, SearchFilters, FloatRange, PatternRange
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


async def test_ak47_nightwish():
    """Тестирование поиска AK-47 | Nightwish."""
    logger.info("=" * 80)
    logger.info("🧪 ТЕСТИРОВАНИЕ ПОИСКА: AK-47 | Nightwish")
    logger.info("=" * 80)
    logger.info("📋 Параметры предмета:")
    logger.info("   - Название: AK-47 | Nightwish")
    logger.info("   - Wear: Minimal Wear")
    logger.info("   - Pattern Template: 156")
    logger.info("   - Wear Rating: 0.121866539")
    logger.info("   - Sticker: Hydro Stream")
    logger.info("=" * 80)
    
    # Инициализация
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    try:
        # Инициализируем RabbitMQ
        logger.info("\n📡 Подключаемся к RabbitMQ...")
        rabbitmq_service = RabbitMQService(rabbitmq_url=Config.RABBITMQ_URL)
        await rabbitmq_service.connect()
        logger.info("✅ RabbitMQ подключен")
        
        # Инициализируем ProxyManager
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
        
        # Создаем фильтры для AK-47 | Nightwish
        logger.info("\n📋 Создаем фильтры для поиска...")
        filters = SearchFilters(
            item_name="AK-47 | Nightwish",
            appid=730,
            currency=1,
            # Float range для Minimal Wear (примерно 0.07 - 0.15)
            float_range=FloatRange(min=0.10, max=0.15),
            # Pattern Template: 156
            pattern_range=PatternRange(min=156, max=156, item_type="skin"),
            # Максимальная цена (можно настроить)
            max_price=100.0
        )
        
        logger.info(f"   ✅ Float range: {filters.float_range.min} - {filters.float_range.max}")
        logger.info(f"   ✅ Pattern: {filters.pattern_range.min} - {filters.pattern_range.max}")
        logger.info(f"   ✅ Max price: ${filters.max_price}")
        
        # Создаем задачу мониторинга
        logger.info("\n📝 Создаем задачу мониторинга...")
        task = await monitoring_service.add_monitoring_task(
            name="Test: AK-47 | Nightwish (MW, Pattern 156)",
            item_name="AK-47 | Nightwish",
            filters=filters,
            check_interval=30  # 30 секунд для быстрого тестирования
        )
        
        logger.info(f"✅ Задача создана!")
        logger.info(f"   📋 ID задачи: {task.id}")
        logger.info(f"   📋 Название: {task.name}")
        logger.info(f"   📋 Интервал проверки: {task.check_interval} сек")
        logger.info(f"   📋 Следующая проверка: {task.next_check.strftime('%Y-%m-%d %H:%M:%S') if task.next_check else 'Сразу'}")
        
        # Проверяем, что задача добавлена в RabbitMQ
        logger.info("\n🔍 Проверяем статус задачи в RabbitMQ...")
        queue_info = await rabbitmq_service.get_queue_info()
        logger.info(f"   📊 Информация об очередях: {queue_info}")
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ЗАДАЧА УСПЕШНО СОЗДАНА И ДОБАВЛЕНА В RABBITMQ")
        logger.info("=" * 80)
        logger.info("\n📊 Мониторинг выполнения:")
        logger.info("   1. Проверьте логи parsing-worker:")
        logger.info("      docker compose logs -f parsing-worker | grep -E '(Задача|AK-47|Nightwish)'")
        logger.info("\n   2. Проверьте RabbitMQ Management UI:")
        logger.info("      http://localhost:15672 (guest/guest)")
        logger.info("      Очередь: parsing_tasks")
        logger.info("\n   3. Задача будет выполняться каждые 30 секунд")
        logger.info("   4. Проверьте, что задача не зависает и выполняется несколько раз")
        logger.info("\n⏳ Ожидаем выполнения задачи...")
        logger.info("   Нажмите Ctrl+C для остановки\n")
        
        # Ждем выполнения задачи
        try:
            # Ждем несколько итераций (5 минут = 10 итераций по 30 секунд)
            for iteration in range(10):
                await asyncio.sleep(30)
                
                # Получаем статистику задачи
                stats = await monitoring_service.get_statistics()
                task_stats = next(
                    (t for t in stats["tasks"] if t["id"] == task.id),
                    None
                )
                
                if task_stats:
                    logger.info(
                        f"📊 Итерация {iteration + 1}: "
                        f"проверок={task_stats['total_checks']}, "
                        f"найдено={task_stats['items_found']}, "
                        f"последняя проверка={task_stats['last_check']}"
                    )
                else:
                    logger.warning(f"⚠️ Задача {task.id} не найдена в статистике")
        except KeyboardInterrupt:
            logger.info("\n🛑 Остановка мониторинга...")
        
        # Финальная статистика
        logger.info("\n" + "=" * 80)
        logger.info("📊 ФИНАЛЬНАЯ СТАТИСТИКА")
        logger.info("=" * 80)
        stats = await monitoring_service.get_statistics()
        task_stats = next(
            (t for t in stats["tasks"] if t["id"] == task.id),
            None
        )
        
        if task_stats:
            logger.info(f"   Задача ID: {task_stats['id']}")
            logger.info(f"   Название: {task_stats['name']}")
            logger.info(f"   Всего проверок: {task_stats['total_checks']}")
            logger.info(f"   Найдено предметов: {task_stats['items_found']}")
            logger.info(f"   Последняя проверка: {task_stats['last_check']}")
            logger.info(f"   Следующая проверка: {task_stats['next_check']}")
            logger.info(f"   Активна: {task_stats['is_active']}")
            
            if task_stats['total_checks'] >= 3:
                logger.info("\n✅ УСПЕХ: Задача выполнилась несколько раз без зависаний!")
            else:
                logger.warning("\n⚠️ ВНИМАНИЕ: Задача выполнилась менее 3 раз")
        else:
            logger.error(f"\n❌ ОШИБКА: Задача {task.id} не найдена в статистике")
        
        # Спрашиваем, удалять ли задачу
        logger.info("\n" + "=" * 80)
        logger.info("🗑️ Удалить тестовую задачу? (оставьте для дальнейшего тестирования)")
        logger.info("=" * 80)
        # Не удаляем автоматически, чтобы можно было продолжить тестирование
        
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
    asyncio.run(test_ak47_nightwish())
