#!/usr/bin/env python3
"""Исправление задачи 30 - установка next_check"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask
from core.config import Config
from sqlalchemy import select, update

async def fix():
    db = DatabaseManager(Config.DATABASE_URL)
    await db.init_db()
    session = await db.get_session()
    try:
        # Получаем задачу 30
        result = await session.execute(select(MonitoringTask).where(MonitoringTask.id == 30))
        task = result.scalar_one_or_none()
        
        if not task:
            print('❌ Задача 30 не найдена')
            return
        
        print(f'Текущее состояние задачи 30:')
        print(f'  next_check: {task.next_check}')
        print(f'  last_check: {task.last_check}')
        print(f'  is_active: {task.is_active}')
        
        # Устанавливаем next_check на текущее время, чтобы задача попала в очередь
        now = datetime.now()
        await session.execute(
            update(MonitoringTask)
            .where(MonitoringTask.id == 30)
            .values(next_check=now)
        )
        await session.commit()
        
        print(f'\n✅ Установлен next_check = {now}')
        print(f'Задача должна быть обработана в ближайшее время')
        
    finally:
        await session.close()
        await db.close()

asyncio.run(fix())

