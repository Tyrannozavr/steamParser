#!/usr/bin/env python3
"""
Сравнительный тест: старый способ (ORM) vs новый способ (атомарный UPDATE).

Показывает разницу в производительности и количестве блокировок.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import DatabaseManager, MonitoringTask
from core.config import Config
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


async def old_way_orm_update(
    session: AsyncSession,
    task_id: int,
    check_interval: int
):
    """Старый способ: обновление через ORM (вызывал блокировки)."""
    start_time = datetime.now()
    try:
        # Загружаем задачу
        task = await session.get(MonitoringTask, task_id)
        if not task:
            return False, (datetime.now() - start_time).total_seconds()
        
        # Обновляем через ORM (старый способ)
        task.total_checks += 1
        task.last_check = datetime.now()
        task.next_check = datetime.now() + timedelta(seconds=check_interval)
        
        # Commit (может заблокироваться)
        await asyncio.wait_for(
            session.commit(),
            timeout=5.0
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        return True, duration
        
    except Exception as e:
        try:
            await session.rollback()
        except Exception:
            pass
        duration = (datetime.now() - start_time).total_seconds()
        return False, duration


async def new_way_atomic_update(
    session: AsyncSession,
    task_id: int,
    check_interval: int
):
    """Новый способ: атомарный UPDATE (предотвращает блокировки)."""
    start_time = datetime.now()
    try:
        now = datetime.now()
        next_check = now + timedelta(seconds=check_interval)
        
        # Атомарный UPDATE (новый способ)
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
        return True, duration
        
    except Exception as e:
        try:
            await session.rollback()
        except Exception:
            pass
        duration = (datetime.now() - start_time).total_seconds()
        return False, duration


async def compare_methods(
    db_manager: DatabaseManager,
    task_id: int,
    check_interval: int,
    num_iterations: int = 50,
    num_concurrent: int = 10
):
    """Сравнивает старый и новый способы обновления."""
    print(f"\n📊 СРАВНЕНИЕ МЕТОДОВ ОБНОВЛЕНИЯ")
    print(f"   Задача: {task_id}")
    print(f"   Итераций: {num_iterations}")
    print(f"   Одновременных операций: {num_concurrent}")
    print("=" * 80)
    
    # Тест старого способа (ORM)
    print("\n🔴 ТЕСТ: Старый способ (ORM обновление)")
    print("-" * 80)
    old_success = 0
    old_failed = 0
    old_times = []
    
    for iteration in range(num_iterations):
        tasks = []
        for _ in range(num_concurrent):
            session = await db_manager.get_session()
            task = old_way_orm_update(session, task_id, check_interval)
            tasks.append((task, session))
        
        results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)
        
        for result, (_, session) in zip(results, tasks):
            try:
                await session.close()
            except Exception:
                pass
            
            if isinstance(result, Exception):
                old_failed += 1
            else:
                success, duration = result
                if success:
                    old_success += 1
                    old_times.append(duration)
                else:
                    old_failed += 1
        
        await asyncio.sleep(0.01)
    
    # Тест нового способа (атомарный UPDATE)
    print("\n🟢 ТЕСТ: Новый способ (атомарный UPDATE)")
    print("-" * 80)
    new_success = 0
    new_failed = 0
    new_times = []
    
    for iteration in range(num_iterations):
        tasks = []
        for _ in range(num_concurrent):
            session = await db_manager.get_session()
            task = new_way_atomic_update(session, task_id, check_interval)
            tasks.append((task, session))
        
        results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)
        
        for result, (_, session) in zip(results, tasks):
            try:
                await session.close()
            except Exception:
                pass
            
            if isinstance(result, Exception):
                new_failed += 1
            else:
                success, duration = result
                if success:
                    new_success += 1
                    new_times.append(duration)
                else:
                    new_failed += 1
        
        await asyncio.sleep(0.01)
    
    # Выводим результаты
    print("\n" + "=" * 80)
    print("📊 РЕЗУЛЬТАТЫ СРАВНЕНИЯ")
    print("=" * 80)
    
    total_ops = num_iterations * num_concurrent
    
    print(f"\n🔴 Старый способ (ORM):")
    print(f"   Успешных: {old_success}/{total_ops} ({old_success/total_ops*100:.1f}%)")
    print(f"   Неудачных: {old_failed}/{total_ops} ({old_failed/total_ops*100:.1f}%)")
    if old_times:
        print(f"   Среднее время: {sum(old_times)/len(old_times)*1000:.2f} мс")
        print(f"   Максимальное время: {max(old_times)*1000:.2f} мс")
    
    print(f"\n🟢 Новый способ (атомарный UPDATE):")
    print(f"   Успешных: {new_success}/{total_ops} ({new_success/total_ops*100:.1f}%)")
    print(f"   Неудачных: {new_failed}/{total_ops} ({new_failed/total_ops*100:.1f}%)")
    if new_times:
        print(f"   Среднее время: {sum(new_times)/len(new_times)*1000:.2f} мс")
        print(f"   Максимальное время: {max(new_times)*1000:.2f} мс")
    
    print("\n" + "=" * 80)
    
    # Вывод
    if new_success > old_success and new_failed < old_failed:
        print("✅ НОВЫЙ СПОСОБ ЛУЧШЕ: Меньше ошибок, больше успешных операций!")
        return True
    else:
        print("⚠️  Результаты требуют дополнительного анализа")
        return False


async def main():
    """Главная функция."""
    print("=" * 80)
    print("🔬 СРАВНИТЕЛЬНЫЙ ТЕСТ: ORM vs Атомарный UPDATE")
    print("=" * 80)
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    try:
        # Получаем задачу
        session = await db_manager.get_session()
        try:
            result = await session.execute(
                select(MonitoringTask).where(MonitoringTask.is_active == True).limit(1)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                print("❌ Нет активных задач в БД")
                return 1
            
            print(f"✅ Используем задачу: {task.id} ({task.name})")
            
        finally:
            await session.close()
        
        success = await compare_methods(
            db_manager,
            task.id,
            check_interval=60,
            num_iterations=30,
            num_concurrent=10
        )
        
        return 0 if success else 1
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await db_manager.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
