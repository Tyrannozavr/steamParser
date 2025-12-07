"""
Тесты для ResultsProcessorService.
Проверяем логику сохранения результатов парсинга и публикации уведомлений.
"""
import pytest
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

pytest_plugins = ('pytest_asyncio',)

from services.results_processor_service import ResultsProcessorService
from core import FoundItem, MonitoringTask
from services.redis_service import RedisService


@pytest.fixture
def mock_db_session():
    """Создает мок сессии БД."""
    session = AsyncMock(spec=AsyncSession)
    
    # Настраиваем execute для возврата результата с scalars().all()
    def create_mock_execute_result(items):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        return result
    
    # По умолчанию возвращаем пустой список (нет дубликатов)
    session.execute = AsyncMock(return_value=create_mock_execute_result([]))
    
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def mock_redis_service():
    """Создает мок Redis сервиса."""
    redis_service = AsyncMock(spec=RedisService)
    redis_service.publish = AsyncMock()
    return redis_service


@pytest.fixture
def mock_task():
    """Создает мок задачи мониторинга."""
    task = MagicMock(spec=MonitoringTask)
    task.id = 1
    task.name = "Test Task"
    task.item_name = "AK-47 | Redline (Field-Tested)"
    task.items_found = 0
    task.total_checks = 0
    return task


@pytest.fixture
def sample_items():
    """Создает примерные данные результатов парсинга."""
    return [
        {
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
    ]


@pytest.mark.asyncio
async def test_process_results_saves_items_to_db(mock_db_session, mock_redis_service, mock_task, sample_items):
    """Тест: результаты сохраняются в БД."""
    call_count = 0
    
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars_mock = MagicMock()
        if call_count == 1:
            # Первый вызов - проверка дубликатов по listing_id
            scalars_mock.all.return_value = []
        else:
            # Второй вызов - проверка по name+price
            result.scalar_one_or_none.return_value = None
        result.scalars.return_value = scalars_mock
        return result
    
    mock_db_session.execute = mock_execute
    mock_db_session.get.return_value = mock_task
    
    # Создаем сервис
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Обрабатываем результаты
    found_count = await processor.process_results(
        task=mock_task,
        items=sample_items,
        task_logger=None
    )
    
    # Проверяем, что предмет был добавлен в сессию
    assert mock_db_session.add.called, "Предмет должен быть добавлен в сессию"
    assert found_count == 1, f"Ожидалось 1 предмет, получено {found_count}"
    
    # Проверяем, что commit был вызван
    assert mock_db_session.commit.called, "Commit должен быть вызван"
    
    # Проверяем, что счетчик обновлен
    assert mock_task.items_found == 1, "Счетчик items_found должен быть обновлен"


@pytest.mark.asyncio
async def test_process_results_skips_duplicates(mock_db_session, mock_redis_service, mock_task, sample_items):
    """Тест: дубликаты пропускаются."""
    # Создаем существующий предмет с тем же listing_id
    existing_item = MagicMock(spec=FoundItem)
    existing_item.id = 100
    existing_item.item_data_json = json.dumps({'listing_id': '765177620331184862'})
    
    # Настраиваем моки - возвращаем существующий предмет
    def create_mock_execute_result(items):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        return result
    
    # Первый вызов - проверка дубликатов по listing_id
    mock_db_session.execute = AsyncMock(return_value=create_mock_execute_result([existing_item]))
    mock_db_session.get.return_value = mock_task
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Обрабатываем результаты
    found_count = await processor.process_results(
        task=mock_task,
        items=sample_items,
        task_logger=None
    )
    
    # Проверяем, что предмет НЕ был добавлен (дубликат)
    assert not mock_db_session.add.called, "Дубликат не должен быть добавлен"
    assert found_count == 0, f"Ожидалось 0 предметов (дубликат), получено {found_count}"


@pytest.mark.asyncio
async def test_process_results_publishes_notifications(mock_db_session, mock_redis_service, mock_task, sample_items):
    """Тест: уведомления публикуются в Redis."""
    # Мокируем FoundItem для публикации
    found_item = MagicMock(spec=FoundItem)
    found_item.id = 1
    found_item.item_name = 'AK-47 | Redline (Field-Tested)'
    found_item.price = 45.73
    found_item.market_url = None
    found_item.item_data_json = json.dumps(sample_items[0]['parsed_data'])
    found_item.notification_sent = False
    
    # При втором вызове execute (для получения найденных предметов) возвращаем наш предмет
    call_count = 0
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars_mock = MagicMock()
        if call_count == 1:
            # Первый вызов - проверка дубликатов по listing_id
            scalars_mock.all.return_value = []
        elif call_count == 2:
            # Второй вызов - проверка по name+price
            result.scalar_one_or_none.return_value = None
        else:
            # Третий вызов - получение найденных предметов для публикации
            scalars_mock.all.return_value = [found_item]
        result.scalars.return_value = scalars_mock
        return result
    
    mock_db_session.execute = mock_execute
    mock_db_session.get.return_value = mock_task
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Обрабатываем результаты
    found_count = await processor.process_results(
        task=mock_task,
        items=sample_items,
        task_logger=None
    )
    
    # Проверяем, что уведомление было опубликовано
    assert mock_redis_service.publish.called, "Уведомление должно быть опубликовано"
    
    # Проверяем параметры публикации
    call_args = mock_redis_service.publish.call_args
    assert call_args[0][0] == "found_items", "Канал должен быть 'found_items'"
    
    notification_data = call_args[0][1]
    assert notification_data['type'] == 'found_item'
    assert notification_data['task_id'] == mock_task.id
    assert notification_data['item_name'] == 'AK-47 | Redline (Field-Tested)'


@pytest.mark.asyncio
async def test_process_results_handles_empty_items(mock_db_session, mock_redis_service, mock_task):
    """Тест: обработка пустого списка предметов."""
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    found_count = await processor.process_results(
        task=mock_task,
        items=[],
        task_logger=None
    )
    
    assert found_count == 0, "Для пустого списка должно быть 0 предметов"
    assert not mock_db_session.add.called, "Не должно быть вызовов add"
    assert not mock_redis_service.publish.called, "Не должно быть публикаций"


@pytest.mark.asyncio
async def test_process_results_handles_price_extraction(mock_db_session, mock_redis_service, mock_task):
    """Тест: извлечение цены из разных источников."""
    # Тест 1: цена из parsed_data
    items_with_parsed_price = [
        {
            'name': 'Test Item',
            'parsed_data': {'item_price': 50.0, 'listing_id': 'test123'},
            'sell_price_text': '$100.00',  # Должна быть проигнорирована
            'listingid': 'test123'
        }
    ]
    
    def create_mock_execute_result(items):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        # Для второго вызова (проверка по name+price) возвращаем None
        result.scalar_one_or_none.return_value = None
        return result
    
    mock_db_session.execute = AsyncMock(return_value=create_mock_execute_result([]))
    mock_db_session.get.return_value = mock_task
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    found_count = await processor.process_results(
        task=mock_task,
        items=items_with_parsed_price,
        task_logger=None
    )
    
    assert found_count == 1
    # Проверяем, что цена была взята из parsed_data
    add_call = mock_db_session.add.call_args[0][0]
    assert add_call.price == 50.0, "Цена должна быть из parsed_data"
    
    # Тест 2: цена из sell_price_text (fallback)
    items_without_parsed_price = [
        {
            'name': 'Test Item',
            'parsed_data': {'listing_id': 'test456'},  # Нет item_price
            'sell_price_text': '$75.50',
            'listingid': 'test456'
        }
    ]
    
    mock_db_session.add.reset_mock()
    mock_db_session.execute = AsyncMock(return_value=create_mock_execute_result([]))
    
    found_count = await processor.process_results(
        task=mock_task,
        items=items_without_parsed_price,
        task_logger=None
    )
    
    assert found_count == 1
    add_call = mock_db_session.add.call_args[0][0]
    assert add_call.price == 75.50, "Цена должна быть из sell_price_text"


@pytest.mark.asyncio
async def test_serialize_for_json_handles_pydantic_models(mock_db_session, mock_redis_service):
    """Тест: сериализация Pydantic моделей."""
    from core.models import StickerInfo
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Создаем объект с Pydantic моделью
    sticker = StickerInfo(position=0, wear='Test Sticker', name='Test Sticker', price=10.0)
    data = {
        'stickers': [sticker],
        'pattern': 522
    }
    
    # Сериализуем
    serialized = processor._serialize_for_json(data)
    
    # Проверяем, что Pydantic модель преобразована в dict
    assert isinstance(serialized['stickers'][0], dict), "StickerInfo должна быть преобразована в dict"
    assert serialized['stickers'][0]['position'] == 0
    assert serialized['stickers'][0]['wear'] == 'Test Sticker'
    assert serialized['pattern'] == 522


@pytest.mark.asyncio
async def test_process_results_updates_task_statistics(mock_db_session, mock_redis_service, mock_task, sample_items):
    """Тест: обновление статистики задачи."""
    def create_mock_execute_result(items):
        result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = items
        result.scalars.return_value = scalars_mock
        result.scalar_one_or_none.return_value = None
        return result
    
    mock_db_session.execute = AsyncMock(return_value=create_mock_execute_result([]))
    mock_db_session.get.return_value = mock_task
    
    processor = ResultsProcessorService(
        db_session=mock_db_session,
        redis_service=mock_redis_service
    )
    
    # Изначально items_found = 0
    assert mock_task.items_found == 0
    
    # Обрабатываем результаты
    found_count = await processor.process_results(
        task=mock_task,
        items=sample_items,
        task_logger=None
    )
    
    # Проверяем, что счетчик обновлен
    assert mock_task.items_found == 1, "items_found должен быть увеличен"
    assert found_count == 1, "found_count должен быть 1"

