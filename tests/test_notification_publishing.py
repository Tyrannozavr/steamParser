"""
Тест для проверки публикации уведомлений в Redis.
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from services.results_processor_service import ResultsProcessorService
from core import FoundItem, MonitoringTask
from services.redis_service import RedisService


@pytest.mark.asyncio
async def test_publish_notification_to_redis():
    """Тест: уведомления публикуются в Redis канал 'found_items'."""
    # Создаем моки
    mock_db_session = AsyncMock()
    mock_redis_service = AsyncMock(spec=RedisService)
    mock_redis_service.publish = AsyncMock()
    
    # Создаем мок задачи
    mock_task = MagicMock(spec=MonitoringTask)
    mock_task.id = 1
    mock_task.name = "Test Task"
    
    # Создаем мок найденного предмета
    found_item = MagicMock(spec=FoundItem)
    found_item.id = 100
    found_item.item_name = "AK-47 | Redline (Field-Tested)"
    found_item.price = 45.73
    found_item.market_url = None
    found_item.item_data_json = json.dumps({
        'listing_id': '765177620331184862',
        'pattern': 522,
        'float_value': 0.350107
    })
    found_item.notification_sent = False
    
    # Настраиваем мок execute для получения найденных предметов
    def create_mock_execute_result(items):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        return result
    
    mock_db_session.execute = AsyncMock(return_value=create_mock_execute_result([found_item]))
    
    # Создаем сервис
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Публикуем уведомления
    await processor._publish_notifications(mock_task, 1)
    
    # Проверяем, что publish был вызван
    assert mock_redis_service.publish.called, "publish должен быть вызван"
    
    # Проверяем параметры вызова
    call_args = mock_redis_service.publish.call_args
    assert call_args[0][0] == "found_items", f"Канал должен быть 'found_items', получен: {call_args[0][0]}"
    
    notification_data = call_args[0][1]
    assert notification_data['type'] == 'found_item'
    assert notification_data['item_id'] == 100
    assert notification_data['task_id'] == 1
    assert notification_data['item_name'] == "AK-47 | Redline (Field-Tested)"
    assert notification_data['price'] == 45.73
    
    print("✅ Тест пройден: уведомления публикуются в Redis канал 'found_items'")


@pytest.mark.asyncio
async def test_publish_notification_with_correct_data_format():
    """Тест: формат данных уведомления корректен."""
    mock_db_session = AsyncMock()
    mock_redis_service = AsyncMock(spec=RedisService)
    mock_redis_service.publish = AsyncMock()
    
    mock_task = MagicMock(spec=MonitoringTask)
    mock_task.id = 1
    mock_task.name = "Test Task"
    
    found_item = MagicMock(spec=FoundItem)
    found_item.id = 200
    found_item.item_name = "Test Item"
    found_item.price = 50.0
    found_item.market_url = "https://steamcommunity.com/market/listings/730/Test%20Item"
    found_item.item_data_json = json.dumps({
        'listing_id': '123456789',
        'pattern': 522,
        'float_value': 0.35,
        'stickers': []
    })
    found_item.notification_sent = False
    
    def create_mock_execute_result(items):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        return result
    
    mock_db_session.execute = AsyncMock(return_value=create_mock_execute_result([found_item]))
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    await processor._publish_notifications(mock_task, 1)
    
    # Проверяем формат данных
    call_args = mock_redis_service.publish.call_args
    notification_data = call_args[0][1]
    
    # Проверяем все обязательные поля
    required_fields = ['type', 'item_id', 'task_id', 'item_name', 'price', 'market_url', 'item_data_json', 'task_name']
    for field in required_fields:
        assert field in notification_data, f"Поле '{field}' отсутствует в уведомлении"
    
    # Проверяем типы данных
    assert isinstance(notification_data['item_id'], int)
    assert isinstance(notification_data['task_id'], int)
    assert isinstance(notification_data['price'], float)
    assert isinstance(notification_data['item_data_json'], str)
    
    # Проверяем, что item_data_json - валидный JSON
    parsed_json = json.loads(notification_data['item_data_json'])
    assert 'listing_id' in parsed_json
    
    print("✅ Тест пройден: формат данных уведомления корректен")


if __name__ == "__main__":
    asyncio.run(test_publish_notification_to_redis())
    asyncio.run(test_publish_notification_with_correct_data_format())

