#!/usr/bin/env python3
"""
Стресс-тест для проверки защиты от блокировок БД при обновлении monitoring_tasks.

Симулирует реальные сценарии:
1. ParsingWorker обновляет задачу (total_checks, last_check, next_check)
2. MonitoringService обновляет next_check
3. process_results обновляет items_found и total_checks

Все эти операции могут происходить одновременно для одной задачи.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import DatabaseManager, MonitoringTask
from core.config import Config
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


class StressTestResults:
    """Результаты стресс-теста."""
    def __init__(self):
        self.total_operations = 0
        self.successful_operations = 0
        self.failed_operations = 0
        self.timeout_errors = 0
        self.lock_errors = 0
        self.other_errors = 0
        self.operation_times = []
    
    def add_result(self, success: bool, duration: float, error: Exception = None):
        """Добавляет результат операции."""
        self.total_operations += 1
        self.operation_times.append(duration)
        
        if success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
            if error:
                error_type = type(error).__name__
                if "Timeout" in error_type or "timeout" in str(error).lower():
                    self.timeout_errors += 1
                elif "lock" in str(error).lower() or "deadlock" in str(error).lower():
                    self.lock_errors += 1
                else:
                    self.other_errors += 1
    
    def print_summary(self):
        """Выводит сводку результатов."""
        print("\n" + "=" * 80)
        print("📊 РЕЗУЛЬТАТЫ СТРЕСС-ТЕСТА")
        print("=" * 80)
        print(f"Всего операций: {self.total_operations}")
        print(f"✅ Успешных: {self.successful_operations} ({self.successful_operations/self.total_operations*100:.1f}%)")
        print(f"❌ Неудачных: {self.failed_operations} ({self.failed_operations/self.total_operations*100:.1f}%)")
        print(f"\nДетализация ошибок:")
        print(f"  ⏱️  Таймауты: {self.timeout_errors}")
        print(f"  🔒 Блокировки: {self.lock_errors}")
        print(f"  ⚠️  Другие ошибки: {self.other_errors}")
        
        if self.operation_times:
            avg_time = sum(self.operation_times) / len(self.operation_times)
            max_time = max(self.operation_times)
            min_time = min(self.operation_times)
            print(f"\nВремя выполнения операций:")
            print(f"  Среднее: {avg_time*1000:.2f} мс")
            print(f"  Минимальное: {min_time*1000:.2f} мс")
            print(f"  Максимальное: {max_time*1000:.2f} мс")
        
        print("=" * 80)
        
        # Проверяем, что нет блокировок
        if self.lock_errors > 0:
            print("\n❌ ОБНАРУЖЕНЫ БЛОКИРОВКИ БД! Защита не работает.")
            return False
        elif self.timeout_errors > self.total_operations * 0.1:  # Более 10% таймаутов
            print("\n⚠️  СЛИШКОМ МНОГО ТАЙМАУТОВ! Возможны проблемы с производительностью.")
            return False
        else:
            print("\n✅ ТЕСТ ПРОЙДЕН: Блокировки не обнаружены, защита работает!")
            return True


async def simulate_parsing_worker_update(
    session: AsyncSession,
    task_id: int,
    check_interval: int,
    results: StressTestResults
):
    """
    Симулирует обновление задачи из ParsingWorker.
    Обновляет: total_checks, last_check, next_check через атомарный UPDATE.
    """
    start_time = datetime.now()
    try:
        now = datetime.now()
        next_check = now + timedelta(seconds=check_interval)
        
        # Атомарный UPDATE (как в parsing_worker.py после исправления)
        update_query = update(MonitoringTask).where(
            MonitoringTask.id == task_id
        ).values(
            total_checks=MonitoringTask.total_checks + 1,
            last_check=now,
            next_check=next_check
        )
        
        await asyncio.wait_for(
            session.execute(update_query),
            timeout=5.0
        )
        
        await asyncio.wait_for(
            session.commit(),
            timeout=3.0
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        results.add_result(True, duration)
        logger.debug(f"✅ ParsingWorker: Задача {task_id} обновлена за {duration*1000:.2f} мс")
        
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        results.add_result(False, duration, e)
        logger.error(f"❌ ParsingWorker: Ошибка при обновлении задачи {task_id}: {e}")
        try:
            await session.rollback()
        except Exception:
            pass


async def simulate_monitoring_service_update(
    session: AsyncSession,
    task_id: int,
    check_interval: int,
    results: StressTestResults
):
    """
    Симулирует обновление next_check из MonitoringService.
    Обновляет только next_check через атомарный UPDATE.
    """
    start_time = datetime.now()
    try:
        now = datetime.now()
        next_check = now + timedelta(seconds=check_interval)
        
        # Атомарный UPDATE (как в monitoring_service.py)
        update_query = update(MonitoringTask).where(
            MonitoringTask.id == task_id
        ).values(next_check=next_check)
        
        await asyncio.wait_for(
            session.execute(update_query),
            timeout=5.0
        )
        
        await asyncio.wait_for(
            session.commit(),
            timeout=3.0
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        results.add_result(True, duration)
        logger.debug(f"✅ MonitoringService: next_check для задачи {task_id} обновлен за {duration*1000:.2f} мс")
        
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        results.add_result(False, duration, e)
        logger.error(f"❌ MonitoringService: Ошибка при обновлении next_check для задачи {task_id}: {e}")
        try:
            await session.rollback()
        except Exception:
            pass


async def simulate_process_results_update(
    session: AsyncSession,
    task_id: int,
    results: StressTestResults
):
    """
    Симулирует обновление из process_results.
    Обновляет: items_found, total_checks через атомарный UPDATE.
    """
    start_time = datetime.now()
    try:
        # Атомарный UPDATE (как в process_results.py)
        update_query = update(MonitoringTask).where(
            MonitoringTask.id == task_id
        ).values(
            items_found=MonitoringTask.items_found + 1,
            total_checks=MonitoringTask.total_checks + 1
        )
        
        await asyncio.wait_for(
            session.execute(update_query),
            timeout=5.0
        )
        
        await asyncio.wait_for(
            session.commit(),
            timeout=3.0
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        results.add_result(True, duration)
        logger.debug(f"✅ process_results: Задача {task_id} обновлена за {duration*1000:.2f} мс")
        
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        results.add_result(False, duration, e)
        logger.error(f"❌ process_results: Ошибка при обновлении задачи {task_id}: {e}")
        try:
            await session.rollback()
        except Exception:
            pass


async def stress_test_single_task(
    db_manager: DatabaseManager,
    task_id: int,
    check_interval: int,
    num_iterations: int = 100,
    num_concurrent: int = 10
):
    """
    Стресс-тест для одной задачи.
    
    Args:
        db_manager: Менеджер БД
        task_id: ID задачи для тестирования
        check_interval: Интервал проверки
        num_iterations: Количество итераций
        num_concurrent: Количество одновременных операций
    """
    results = StressTestResults()
    
    print(f"\n🧪 СТРЕСС-ТЕСТ: Задача {task_id}")
    print(f"   Итераций: {num_iterations}")
    print(f"   Одновременных операций: {num_concurrent}")
    print("=" * 80)
    
    # Проверяем, что задача существует
    session = await db_manager.get_session()
    try:
        task = await session.get(MonitoringTask, task_id)
        if not task:
            print(f"❌ Задача {task_id} не найдена в БД")
            return False
        print(f"✅ Задача найдена: {task.name}")
    finally:
        await session.close()
    
    # Запускаем стресс-тест
    for iteration in range(num_iterations):
        if (iteration + 1) % 10 == 0:
            logger.info(f"Итерация {iteration + 1}/{num_iterations}...")
        
        # Создаем несколько одновременных операций
        tasks = []
        for _ in range(num_concurrent):
            # Создаем отдельную сессию для каждой операции (как в реальной системе)
            session = await db_manager.get_session()
            
            # Случайно выбираем тип операции
            import random
            operation_type = random.choice([
                'parsing_worker',
                'monitoring_service',
                'process_results'
            ])
            
            if operation_type == 'parsing_worker':
                task = simulate_parsing_worker_update(session, task_id, check_interval, results)
            elif operation_type == 'monitoring_service':
                task = simulate_monitoring_service_update(session, task_id, check_interval, results)
            else:  # process_results
                task = simulate_process_results_update(session, task_id, results)
            
            tasks.append((task, session))
        
        # Ждем завершения всех операций
        await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)
        
        # Закрываем сессии
        for _, session in tasks:
            try:
                await session.close()
            except Exception:
                pass
        
        # Небольшая задержка между итерациями
        await asyncio.sleep(0.01)
    
    return results.print_summary()


async def stress_test_multiple_tasks(
    db_manager: DatabaseManager,
    task_ids: list,
    check_interval: int,
    num_iterations: int = 50,
    num_concurrent: int = 5
):
    """
    Стресс-тест для нескольких задач одновременно.
    """
    results = StressTestResults()
    
    print(f"\n🧪 СТРЕСС-ТЕСТ: Несколько задач одновременно")
    print(f"   Задач: {len(task_ids)}")
    print(f"   Итераций: {num_iterations}")
    print(f"   Одновременных операций на задачу: {num_concurrent}")
    print("=" * 80)
    
    for iteration in range(num_iterations):
        if (iteration + 1) % 10 == 0:
            logger.info(f"Итерация {iteration + 1}/{num_iterations}...")
        
        # Создаем операции для всех задач одновременно
        all_tasks = []
        for task_id in task_ids:
            for _ in range(num_concurrent):
                session = await db_manager.get_session()
                
                import random
                operation_type = random.choice([
                    'parsing_worker',
                    'monitoring_service',
                    'process_results'
                ])
                
                if operation_type == 'parsing_worker':
                    task = simulate_parsing_worker_update(session, task_id, check_interval, results)
                elif operation_type == 'monitoring_service':
                    task = simulate_monitoring_service_update(session, task_id, check_interval, results)
                else:
                    task = simulate_process_results_update(session, task_id, results)
                
                all_tasks.append((task, session))
        
        # Ждем завершения всех операций
        await asyncio.gather(*[t[0] for t in all_tasks], return_exceptions=True)
        
        # Закрываем сессии
        for _, session in all_tasks:
            try:
                await session.close()
            except Exception:
                pass
        
        await asyncio.sleep(0.01)
    
    return results.print_summary()


async def main():
    """Главная функция теста."""
    print("=" * 80)
    print("🔥 СТРЕСС-ТЕСТ: Защита от блокировок БД")
    print("=" * 80)
    print("\nЭтот тест проверяет, что атомарные UPDATE запросы предотвращают")
    print("блокировки при одновременном обновлении одной задачи из разных процессов.")
    print("\nСимулируемые сценарии:")
    print("  1. ParsingWorker обновляет total_checks, last_check, next_check")
    print("  2. MonitoringService обновляет next_check")
    print("  3. process_results обновляет items_found, total_checks")
    print()
    
    # Инициализируем БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        # Получаем список задач из БД
        session = await db_manager.get_session()
        try:
            result = await session.execute(
                select(MonitoringTask).where(MonitoringTask.is_active == True).limit(5)
            )
            tasks = list(result.scalars().all())
            
            if not tasks:
                print("❌ Нет активных задач в БД для тестирования")
                print("   Создайте хотя бы одну задачу через Telegram бота или скрипт")
                return
            
            print(f"✅ Найдено {len(tasks)} активных задач")
            task_ids = [task.id for task in tasks]
            
        finally:
            await session.close()
        
        # Тест 1: Стресс-тест для одной задачи
        print("\n" + "=" * 80)
        print("ТЕСТ 1: Стресс-тест для одной задачи")
        print("=" * 80)
        success1 = await stress_test_single_task(
            db_manager,
            task_ids[0],
            check_interval=60,
            num_iterations=100,
            num_concurrent=10
        )
        
        # Тест 2: Стресс-тест для нескольких задач
        if len(task_ids) > 1:
            print("\n" + "=" * 80)
            print("ТЕСТ 2: Стресс-тест для нескольких задач одновременно")
            print("=" * 80)
            success2 = await stress_test_multiple_tasks(
                db_manager,
                task_ids[:min(3, len(task_ids))],
                check_interval=60,
                num_iterations=50,
                num_concurrent=5
            )
        else:
            success2 = True
            print("\n⚠️  Пропущен тест 2: нужно минимум 2 задачи")
        
        # Итоговый результат
        print("\n" + "=" * 80)
        print("📋 ИТОГОВЫЙ РЕЗУЛЬТАТ")
        print("=" * 80)
        if success1 and success2:
            print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ: Защита от блокировок работает!")
            return 0
        else:
            print("❌ ТЕСТЫ НЕ ПРОЙДЕНЫ: Обнаружены проблемы с блокировками")
            return 1
            
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        traceback.print_exc()
        return 1
    finally:
        await db_manager.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
