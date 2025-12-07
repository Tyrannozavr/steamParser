"""
Скрипт для запуска последней задачи через Docker.
"""
import subprocess
import sys

def run_last_task():
    """Запускает последнюю задачу через Docker."""
    print("🚀 Запускаю последнюю задачу через Docker...")
    
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
from sqlalchemy import select
from core.database import MonitoringTask

async def main():
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    # Получаем последнюю задачу
    result = await session.execute(
        select(MonitoringTask).order_by(MonitoringTask.id.desc()).limit(1)
    )
    task = result.scalar_one_or_none()
    
    if not task:
        print("❌ Нет задач в базе данных")
        await session.close()
        await db_manager.close()
        return
    
    print(f"📋 Найдена задача: ID={task.id}, название='{task.name}', предмет='{task.item_name}'")
    
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
    print("✅ Задача отправлена, проверяйте логи")

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
    run_last_task()

