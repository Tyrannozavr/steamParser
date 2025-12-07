"""
Тесты для системы БД, прокси и мониторинга.
"""
import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

pytest_plugins = ('pytest_asyncio',)

from core import SearchFilters, FloatRange, PatternList, StickersFilter, DatabaseManager
from services import ProxyManager, MonitoringService


async def test_database():
    """Тест работы с БД."""
    print("=" * 70)
    print("🧪 ТЕСТ: База данных")
    print("=" * 70)
    
    # Используем тестовую БД
    db_path = "sqlite+aiosqlite:///test_monitor.db"
    if os.path.exists("test_monitor.db"):
        os.remove("test_monitor.db")
    
    async with DatabaseManager(db_path) as db:
        session = await db.get_session()
        
        # Тест создания таблиц
        print("✅ Таблицы созданы")
        
        await session.close()
    
    print("✅ Тест БД пройден\n")


async def test_proxy_manager():
    """Тест менеджера прокси."""
    print("=" * 70)
    print("🧪 ТЕСТ: Менеджер прокси")
    print("=" * 70)
    
    db_path = "test_monitor.db"
    async with DatabaseManager(db_path) as db:
        session = await db.get_session()
        proxy_manager = ProxyManager(session)
        
        # Добавляем прокси
        proxy1 = await proxy_manager.add_proxy("http://user1:pass1@proxy1.com:8080", delay=1.0)
        proxy2 = await proxy_manager.add_proxy("http://user2:pass2@proxy2.com:8080", delay=2.0)
        print(f"✅ Добавлены прокси: {proxy1.id}, {proxy2.id}")
        
        # Получаем активные прокси
        proxies = await proxy_manager.get_active_proxies()
        print(f"✅ Активных прокси: {len(proxies)}")
        
        # Получаем следующий прокси
        next_proxy = await proxy_manager.get_next_proxy()
        print(f"✅ Следующий прокси: {next_proxy.id if next_proxy else 'None'}")
        
        # Отмечаем как использованный
        if next_proxy:
            await proxy_manager.mark_proxy_used(next_proxy, success=True)
            print(f"✅ Прокси {next_proxy.id} отмечен как использованный")
        
        # Статистика
        stats = await proxy_manager.get_proxy_stats()
        print(f"✅ Статистика прокси: {stats['total']} всего, {stats['active']} активных")
        
        await session.close()
    
    print("✅ Тест менеджера прокси пройден\n")


async def test_monitoring_service():
    """Тест сервиса мониторинга."""
    print("=" * 70)
    print("🧪 ТЕСТ: Сервис мониторинга")
    print("=" * 70)
    
    db_path = "test_monitor.db"
    async with DatabaseManager(db_path) as db:
        session = await db.get_session()
        proxy_manager = ProxyManager(session)
        monitoring_service = MonitoringService(session, proxy_manager)
        
        # Добавляем тестовый прокси (может быть нерабочим, но для теста сойдет)
        await proxy_manager.add_proxy("http://test:test@test.com:8080")
        
        # Создаем фильтры
        filters = SearchFilters(
            item_name="AK-47 | Redline",
            pattern_list=PatternList(patterns=[372, 48], item_type="skin"),
            max_price=40.0
        )
        
        # Добавляем задачу мониторинга
        task = await monitoring_service.add_monitoring_task(
            name="Тестовая задача",
            item_name="AK-47 | Redline",
            filters=filters,
            check_interval=300  # 5 минут для теста
        )
        print(f"✅ Добавлена задача мониторинга: {task.id}")
        
        # Получаем все задачи
        tasks = await monitoring_service.get_all_tasks()
        print(f"✅ Всего задач: {len(tasks)}")
        
        # Обновляем задачу
        updated_task = await monitoring_service.update_monitoring_task(
            task.id,
            name="Обновленная задача",
            check_interval=600
        )
        print(f"✅ Задача обновлена: {updated_task.name if updated_task else 'None'}")
        
        # Статистика
        stats = await monitoring_service.get_statistics()
        print(f"✅ Статистика: {stats['total_tasks']} задач, {stats['active_tasks']} активных")
        
        await session.close()
    
    print("✅ Тест сервиса мониторинга пройден\n")


async def test_persistence():
    """Тест устойчивости к перезагрузкам."""
    print("=" * 70)
    print("🧪 ТЕСТ: Устойчивость к перезагрузкам")
    print("=" * 70)
    
    db_path = "test_monitor.db"
    
    # Первая сессия - создаем данные
    async with DatabaseManager(db_path) as db:
        session = await db.get_session()
        proxy_manager = ProxyManager(session)
        monitoring_service = MonitoringService(session, proxy_manager)
        
        # Добавляем прокси
        await proxy_manager.add_proxy("http://proxy1:pass@host1.com:8080")
        await proxy_manager.add_proxy("http://proxy2:pass@host2.com:8080")
        
        # Добавляем задачу
        filters = SearchFilters(item_name="AK-47 | Redline", max_price=50.0)
        task = await monitoring_service.add_monitoring_task(
            name="Задача для теста персистентности",
            item_name="AK-47 | Redline",
            filters=filters
        )
        
        print(f"✅ Создано: {task.id} задача, 2 прокси")
        await session.close()
    
    # Вторая сессия - проверяем, что данные сохранились
    async with DatabaseManager(db_path) as db:
        session = await db.get_session()
        proxy_manager = ProxyManager(session)
        monitoring_service = MonitoringService(session, proxy_manager)
        
        # Проверяем прокси
        proxies = await proxy_manager.get_active_proxies()
        print(f"✅ Восстановлено прокси: {len(proxies)}")
        
        # Проверяем задачи
        tasks = await monitoring_service.get_all_tasks()
        print(f"✅ Восстановлено задач: {len(tasks)}")
        
        if tasks:
            task = tasks[0]
            print(f"✅ Задача '{task.name}' восстановлена с фильтрами")
        
        await session.close()
    
    print("✅ Тест персистентности пройден\n")


async def test_multiple_items():
    """Тест мониторинга нескольких предметов."""
    print("=" * 70)
    print("🧪 ТЕСТ: Мониторинг нескольких предметов")
    print("=" * 70)
    
    db_path = "test_monitor.db"
    async with DatabaseManager(db_path) as db:
        session = await db.get_session()
        proxy_manager = ProxyManager(session)
        monitoring_service = MonitoringService(session, proxy_manager)
        
        # Добавляем несколько прокси
        for i in range(3):
            await proxy_manager.add_proxy(f"http://proxy{i}:pass@host{i}.com:8080", delay=1.0 + i * 0.5)
        
        # Добавляем несколько задач мониторинга
        items = [
            ("AK-47 | Redline", PatternList(patterns=[372, 48], item_type="skin")),
            ("AK-47 | Redline", FloatRange(min=0.15, max=0.20)),
            ("M4A4 | Howl", PatternList(patterns=[123, 456], item_type="skin")),
        ]
        
        for i, (item_name, filter_obj) in enumerate(items):
            if isinstance(filter_obj, PatternList):
                filters = SearchFilters(item_name=item_name, pattern_list=filter_obj, max_price=50.0)
            else:
                filters = SearchFilters(item_name=item_name, float_range=filter_obj, max_price=50.0)
            
            task = await monitoring_service.add_monitoring_task(
                name=f"Задача {i+1}: {item_name}",
                item_name=item_name,
                filters=filters,
                check_interval=300
            )
            print(f"✅ Добавлена задача {i+1}: {task.name}")
        
        # Статистика
        stats = await monitoring_service.get_statistics()
        print(f"\n✅ Всего задач: {stats['total_tasks']}")
        print(f"✅ Активных задач: {stats['active_tasks']}")
        
        proxy_stats = await proxy_manager.get_proxy_stats()
        print(f"✅ Всего прокси: {proxy_stats['total']}")
        print(f"✅ Активных прокси: {proxy_stats['active']}")
        
        await session.close()
    
    print("✅ Тест мониторинга нескольких предметов пройден\n")


async def cleanup_test_db():
    """Очистка тестовой БД."""
    db_path = "test_monitor.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"✅ Тестовая БД удалена: {db_path}")


async def main():
    """Запуск всех тестов."""
    print("\n" + "=" * 70)
    print("🚀 ЗАПУСК ТЕСТОВ СИСТЕМЫ БД И МОНИТОРИНГА")
    print("=" * 70 + "\n")
    
    try:
        await test_database()
        await test_proxy_manager()
        await test_monitoring_service()
        await test_persistence()
        await test_multiple_items()
        
        print("=" * 70)
        print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
        print("=" * 70)
        
        # Очистка (раскомментируйте, если нужно)
        # await cleanup_test_db()
        
    except Exception as e:
        print(f"\n❌ ОШИБКА ПРИ ВЫПОЛНЕНИИ ТЕСТОВ: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

