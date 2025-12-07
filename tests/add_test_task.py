"""
Скрипт для добавления тестовой задачи через Docker.
"""
import subprocess
import sys

def add_test_task():
    """Добавляет тестовую задачу через Docker."""
    print("🚀 Добавляю тестовую задачу через Docker...")
    
    # Запускаем команду внутри контейнера parsing-worker
    cmd = [
        "docker", "exec", "steam-parsing-worker", "python3", "-c", """
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, '/app')

from core.database import DatabaseManager
from services.redis_service import RedisService
from core.config import Config
from core.database import MonitoringTask
from core.models import SearchFilters, PatternList

async def main():
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    # Создаем тестовую задачу
    filters = SearchFilters(
        appid=730,
        currency=1,
        item_name="StatTrak™ AK-47 | Redline (Well-Worn)",
        pattern_list=PatternList(patterns=[419], item_type="skin"),
        auto_update_base_price=False
    )
    
    task = MonitoringTask(
        name="ТЕСТ ПРОКСИ И НАКЛЕЕК",
        item_name="StatTrak™ AK-47 | Redline (Well-Worn)",
        filters_json=filters.model_dump(),
        appid=730,
        currency=1,
        is_active=True,
        check_interval=60
    )
    
    session.add(task)
    await session.commit()
    await session.refresh(task)
    
    print(f"✅ Создана задача: ID={task.id}, название='{task.name}', предмет='{task.item_name}'")
    
    # Инициализируем Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    print("✅ Redis подключен")
    
    # Публикуем задачу в Redis
    message = {
        "type": "parsing_task",
        "task_id": task.id,
        "filters_json": task.filters_json,
        "item_name": task.item_name,
        "appid": task.appid,
        "currency": task.currency
    }
    
    await redis_service.publish("parsing_tasks", message)
    print(f"📤 Опубликована задача парсинга в Redis: task_id={task.id}")
    
    await redis_service.disconnect()
    await session.close()
    await db_manager.close()
    print("✅ Задача добавлена и отправлена на парсинг")

asyncio.run(main())
"""
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка: {e}")
        print(e.stdout)
        print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    add_test_task()

