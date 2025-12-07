"""
Интеграционный тест для полного цикла: предмет прошел фильтры -> сохранение в БД -> публикация в Redis.
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from services.results_processor_service import ResultsProcessorService
from core import FoundItem, MonitoringTask
from services.redis_service import RedisService
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_full_flow_item_passed_filters_to_db_and_redis():
    """
    Полный тест: предмет прошел фильтры -> ResultsProcessorService -> БД -> Redis.
    Симулирует реальный сценарий из parsing_worker.
    """
    # Создаем моки
    mock_db_session = AsyncMock(spec=AsyncSession)
    mock_redis_service = AsyncMock(spec=RedisService)
    mock_redis_service.publish = AsyncMock()
    
    # Создаем мок задачи
    mock_task = MagicMock(spec=MonitoringTask)
    mock_task.id = 135
    mock_task.name = "AK-47 | Redline (Field-Tested) - Паттерн 522"
    mock_task.items_found = 0
    mock_task.total_checks = 0
    
    # Создаем предмет, который прошел фильтры (формат из parsing_worker)
    item_that_passed_filters = {
        'name': 'AK-47 | Redline (Field-Tested)',
        'asset_description': {'market_hash_name': 'AK-47 | Redline (Field-Tested)'},
        'sell_price_text': '$45.73',
        'listingid': '765177620331184862',
        'parsed_data': {
            'item_price': 45.73,
            'float_value': 0.350107,
            'pattern': 522,
            'stickers': [
                {'position': 0, 'wear': 'Overloaded (Glitter)', 'name': 'Overloaded (Glitter)', 'price': None}
            ],
            'listing_id': '765177620331184862'
        }
    }
    
    items_list = [item_that_passed_filters]
    
    # Настраиваем моки для проверки дубликатов
    call_count = 0
    
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars_mock = MagicMock()
        
        if call_count == 1:
            # Первый вызов - проверка дубликатов по listing_id (всех предметов задачи)
            scalars_mock.all.return_value = []  # Нет дубликатов
        elif call_count == 2:
            # Второй вызов - проверка по name+price
            result.scalar_one_or_none.return_value = None  # Нет дубликатов
        else:
            # Третий вызов - получение найденных предметов для публикации
            # Создаем мок FoundItem, который был бы сохранен в БД
            found_item = MagicMock(spec=FoundItem)
            found_item.id = 1000
            found_item.item_name = 'AK-47 | Redline (Field-Tested)'
            found_item.price = 45.73
            found_item.market_url = None
            found_item.item_data_json = json.dumps(item_that_passed_filters['parsed_data'])
            found_item.notification_sent = False
            found_item.found_at = datetime.now()
            scalars_mock.all.return_value = [found_item]
        
        result.scalars.return_value = scalars_mock
        return result
    
    mock_db_session.execute = mock_execute
    mock_db_session.get = AsyncMock(return_value=mock_task)
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()
    mock_db_session.refresh = AsyncMock()
    
    # Создаем сервис
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Симулируем вызов из parsing_worker
    print(f"📦 Обрабатываем {len(items_list)} предметов, которые прошли фильтры...")
    found_count = await processor.process_results(
        task=mock_task,
        items=items_list,
        task_logger=None
    )
    
    # Проверки
    print(f"\n🔍 Результаты теста:")
    print(f"  - found_count: {found_count}")
    print(f"  - mock_db_session.add.called: {mock_db_session.add.called}")
    print(f"  - mock_db_session.commit.called: {mock_db_session.commit.called}")
    print(f"  - mock_redis_service.publish.called: {mock_redis_service.publish.called}")
    
    # Проверяем, что предмет был добавлен в сессию
    assert found_count == 1, f"Ожидалось 1 предмет, получено {found_count}"
    assert mock_db_session.add.called, "Предмет должен быть добавлен в сессию"
    
    # Проверяем, что commit был вызван
    assert mock_db_session.commit.called, "Commit должен быть вызван"
    
    # Проверяем, что уведомление было опубликовано
    assert mock_redis_service.publish.called, "Уведомление должно быть опубликовано"
    
    # Проверяем параметры публикации
    call_args = mock_redis_service.publish.call_args
    assert call_args[0][0] == "found_items", "Канал должен быть 'found_items'"
    
    notification_data = call_args[0][1]
    assert notification_data['type'] == 'found_item'
    assert notification_data['item_name'] == 'AK-47 | Redline (Field-Tested)'
    assert notification_data['price'] == 45.73
    
    print(f"\n✅ Тест пройден: предмет прошел фильтры -> сохранен в БД -> опубликован в Redis")


@pytest.mark.asyncio
async def test_multiple_items_flow():
    """Тест: несколько предметов, которые прошли фильтры."""
    mock_db_session = AsyncMock(spec=AsyncSession)
    mock_redis_service = AsyncMock(spec=RedisService)
    mock_redis_service.publish = AsyncMock()
    
    mock_task = MagicMock(spec=MonitoringTask)
    mock_task.id = 136
    mock_task.name = "Test Task"
    mock_task.items_found = 0
    mock_task.total_checks = 0
    
    items_list = [
        {
            'name': 'Item 1',
            'asset_description': {'market_hash_name': 'Item 1'},
            'sell_price_text': '$10.00',
            'listingid': '111',
            'parsed_data': {
                'item_price': 10.0,
                'float_value': 0.35,
                'pattern': 522,
                'listing_id': '111'
            }
        },
        {
            'name': 'Item 2',
            'asset_description': {'market_hash_name': 'Item 2'},
            'sell_price_text': '$20.00',
            'listingid': '222',
            'parsed_data': {
                'item_price': 20.0,
                'float_value': 0.36,
                'pattern': 523,
                'listing_id': '222'
            }
        }
    ]
    
    call_count = 0
    
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars_mock = MagicMock()
        
        if call_count <= 2:
            # Первые два вызова - проверка дубликатов для каждого предмета
            scalars_mock.all.return_value = []
            result.scalar_one_or_none.return_value = None
        else:
            # Третий вызов - получение найденных предметов для публикации
            found_items = []
            for idx, item in enumerate(items_list):
                found_item = MagicMock(spec=FoundItem)
                found_item.id = 1000 + idx
                found_item.item_name = item['name']
                found_item.price = item['parsed_data']['item_price']
                found_item.market_url = None
                found_item.item_data_json = json.dumps(item['parsed_data'])
                found_item.notification_sent = False
                found_item.found_at = datetime.now()
                found_items.append(found_item)
            scalars_mock.all.return_value = found_items
        
        result.scalars.return_value = scalars_mock
        return result
    
    mock_db_session.execute = mock_execute
    mock_db_session.get = AsyncMock(return_value=mock_task)
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()
    mock_db_session.refresh = AsyncMock()
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    found_count = await processor.process_results(
        task=mock_task,
        items=items_list,
        task_logger=None
    )
    
    assert found_count == 2, f"Ожидалось 2 предмета, получено {found_count}"
    assert mock_db_session.add.call_count == 2, f"add должен быть вызван 2 раза, вызван {mock_db_session.add.call_count}"
    assert mock_redis_service.publish.call_count == 2, f"publish должен быть вызван 2 раза, вызван {mock_redis_service.publish.call_count}"
    
    print(f"✅ Тест пройден: 2 предмета обработаны корректно")


if __name__ == "__main__":
    asyncio.run(test_full_flow_item_passed_filters_to_db_and_redis())
    asyncio.run(test_multiple_items_flow())

