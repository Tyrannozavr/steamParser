#!/usr/bin/env python3
"""
Скрипт для добавления или обновления задачи 126: AK-47 | Redline (Field-Tested)
Запускается через Docker exec
"""
import subprocess
import sys

def add_task_126():
    """Добавляет или обновляет задачу 126 через Docker."""
    print("🚀 Добавляем/обновляем задачу 126 через Docker...")
    
    # Запускаем команду внутри контейнера parsing-worker
    cmd = [
        "docker", "exec", "steam-parsing-worker", "python3", "-c", """
import asyncio
import sys
sys.path.insert(0, '/app')

from core import DatabaseManager, SearchFilters, FloatRange, PatternList, MonitoringTask
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from core.config import Config
from sqlalchemy import select
from loguru import logger

async def main():
    logger.info("🔍 Проверяем задачу 126: AK-47 | Redline (Field-Tested)...")
    
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    
    session = await db_manager.get_session()
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    # Инициализируем ProxyManager
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    
    # Инициализируем MonitoringService
    monitoring_service = MonitoringService(
        session,
        proxy_manager,
        notification_callback=None,
        redis_service=redis_service
    )
    
    # Создаем фильтры для задачи 126
    filters = SearchFilters(
        item_name="AK-47 | Redline (Field-Tested)",
        appid=730,
        currency=1,
        max_price=50.0,  # Макс. цена: $50.00
        float_range=FloatRange(min=0.350000, max=0.360000),  # Float: 0.350000 - 0.360000
        pattern_list=PatternList(patterns=[522], item_type="skin")  # Паттерн: 522 (skin)
    )
    
    try:
        # Проверяем, существует ли задача 126
        result = await session.execute(
            select(MonitoringTask).where(MonitoringTask.id == 126)
        )
        existing_task = result.scalar_one_or_none()
        
        if existing_task:
            print(f"📝 Задача 126 уже существует, обновляем...")
            print(f"   Старое название: {existing_task.name}")
            print(f"   Старый предмет: {existing_task.item_name}")
            
            # Обновляем задачу
            task = await monitoring_service.update_monitoring_task(
                task_id=126,
                name="AK-47 | Redline (Field-Tested) - Паттерн 522",
                filters=filters
            )
            
            if task:
                print(f"✅ Задача 126 обновлена успешно!")
            else:
                print(f"❌ Не удалось обновить задачу 126")
                return
        else:
            print(f"➕ Задача 126 не найдена, создаем новую...")
            
            # Создаем новую задачу
            task = await monitoring_service.add_monitoring_task(
                name="AK-47 | Redline (Field-Tested) - Паттерн 522",
                item_name="AK-47 | Redline (Field-Tested)",
                filters=filters,
                check_interval=60  # Проверка каждую минуту
            )
            
            print(f"✅ Задача создана успешно!")
            print(f"   ID: {task.id} (будет другой, так как 126 уже занят)")
        
        print(f"   Название: {task.name}")
        print(f"   Предмет: {task.item_name}")
        print(f"   Макс. цена: ${filters.max_price:.2f}")
        print(f"   Float: {filters.float_range.min:.6f} - {filters.float_range.max:.6f}")
        print(f"   Паттерны: {filters.pattern_list.patterns} ({filters.pattern_list.item_type})")
        print(f"   Интервал проверки: {task.check_interval} сек")
        print(f"   Активна: {task.is_active}")
        print(f"")
        print(f"📋 Используйте команду /tasks в Telegram боте для просмотра задач")
        print(f"📊 Используйте команду /status для просмотра статистики")
        
    except Exception as e:
        print(f"❌ Ошибка при создании/обновлении задачи: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()

asyncio.run(main())
"""
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка выполнения команды: {e}", file=sys.stderr)
        if e.stdout:
            print(f"STDOUT: {e.stdout}", file=sys.stderr)
        if e.stderr:
            print(f"STDERR: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Docker не найден. Убедитесь, что Docker установлен и запущен.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    add_task_126()

