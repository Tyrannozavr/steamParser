#!/usr/bin/env python3
"""Проверка задачи 63"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, FoundItem
from core.config import Config
from sqlalchemy import select, desc
import json

async def check():
    db = DatabaseManager(Config.DATABASE_URL)
    await db.init_db()
    session = await db.get_session()
    try:
        # Проверяем задачу 63
        result = await session.execute(select(MonitoringTask).where(MonitoringTask.id == 63))
        task = result.scalar_one_or_none()
        if task:
            print(f'Задача 63:')
            print(f'  Название: {task.name}')
            print(f'  Активна: {task.is_active}')
            print(f'  Предмет: {task.item_name}')
            print(f'  Проверок: {task.total_checks}')
            print(f'  Найдено: {task.items_found}')
            print(f'  Последняя проверка: {task.last_check}')
            print(f'  Следующая проверка: {task.next_check}')
            print(f'  Интервал проверки: {task.check_interval} сек')
            print(f'  Фильтры: {json.dumps(task.filters_json, ensure_ascii=False, indent=2)}')
        else:
            print('Задача 63 не найдена')
        
        # Проверяем найденные предметы для задачи 63
        found_result = await session.execute(
            select(FoundItem)
            .where(FoundItem.task_id == 63)
            .order_by(desc(FoundItem.found_at))
            .limit(10)
        )
        found_items = list(found_result.scalars().all())
        print(f'\nНайдено предметов для задачи 63: {len(found_items)}')
        for item in found_items:
            print(f'  - {item.item_name}: ${item.price:.2f} (найдено: {item.found_at})')
    finally:
        await session.close()
        await db.close()

asyncio.run(check())





