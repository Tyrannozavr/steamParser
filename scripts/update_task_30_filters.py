#!/usr/bin/env python3
"""Обновление фильтров задачи 30 - ослабление для теста"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, SearchFilters, StickersFilter
from core.config import Config
from sqlalchemy import select

async def update():
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
        
        # Обновляем фильтры - ослабляем для теста
        filters = SearchFilters.model_validate_json(task.filters_json)
        
        # Ослабляем фильтры:
        # - Увеличиваем максимальную цену до $150
        # - Увеличиваем коэффициент переплаты до 0.3 (30%)
        # - Уменьшаем минимальную цену наклеек до $2.0
        filters.max_price = 150.0
        filters.stickers_filter.max_overpay_coefficient = 0.3  # 30% вместо 10%
        filters.stickers_filter.min_stickers_price = 2.0  # $2 вместо $5
        
        # Сохраняем обновленные фильтры
        task.filters_json = filters.model_dump_json()
        await session.commit()
        
        print(f'✅ Фильтры задачи 30 обновлены:')
        print(f'  Макс. цена: ${filters.max_price}')
        print(f'  Макс. переплата: {filters.stickers_filter.max_overpay_coefficient * 100}%')
        print(f'  Мин. цена наклеек: ${filters.stickers_filter.min_stickers_price}')
        
    finally:
        await session.close()
        await db.close()

asyncio.run(update())

