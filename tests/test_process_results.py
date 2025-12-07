"""
Тесты для модуля process_results.
Проверяет обработку результатов парсинга: фильтрацию, запрос цен наклеек и отправку уведомлений.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from core import MonitoringTask, FoundItem
from core.models import ParsedItemData, SearchFilters, StickerInfo, PatternList, FloatRange
from core.steam_market_parser.process_results import process_item_result, _serialize_for_json
from services.redis_service import RedisService


@pytest.fixture
def mock_task():
    """Создает тестовую задачу мониторинга."""
    task = MagicMock(spec=MonitoringTask)
    task.id = 1
    task.name = "Test Task"
    task.item_name = "AK-47 | Redline (Field-Tested)"
    task.items_found = 0
    task.total_checks = 0
    return task


@pytest.fixture
def mock_parsed_data():
    """Создает тестовые распарсенные данные."""
    return ParsedItemData(
        item_name="AK-47 | Redline (Field-Tested)",
        item_price=45.73,
        float_value=0.350107,
        pattern=522,
        stickers=[],
        total_stickers_price=0.0,
        listing_id="765177620331184862",
        item_type="skin",
        is_stattrak=False
    )


@pytest.fixture
def mock_filters():
    """Создает тестовые фильтры."""
    from core.models import PatternList, FloatRange
    return SearchFilters(
        item_name="AK-47 | Redline (Field-Tested)",
        appid=730,
        currency=1,
        max_price=50.0,
        float_range=FloatRange(min=0.350000, max=0.360000),
        pattern_list=PatternList(patterns=[522], item_type="skin")
    )


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
        result.scalar_one_or_none.return_value = None
        return result
    
    # По умолчанию возвращаем пустой список (нет дубликатов)
    session.execute = AsyncMock(return_value=create_mock_execute_result([]))
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_redis_service():
    """Создает мок Redis сервиса."""
    redis = AsyncMock(spec=RedisService)
    redis.is_connected = MagicMock(return_value=True)
    redis.publish = AsyncMock()
    return redis


@pytest.fixture
def mock_parser(mock_redis_service):
    """Создает мок парсера."""
    parser = MagicMock()
    parser.filter_service = MagicMock()
    parser.filter_service.matches_filters = AsyncMock(return_value=True)
    parser.get_stickers_prices = AsyncMock(return_value={})
    parser.redis_service = mock_redis_service
    return parser


@pytest.mark.asyncio
async def test_process_item_result_success(
    mock_parser,
    mock_task,
    mock_parsed_data,
    mock_filters,
    mock_db_session,
    mock_redis_service
):
    """Тест успешной обработки предмета: фильтры пройдены, предмет сохранен."""
    # Настраиваем моки
    mock_parser.filter_service.matches_filters.return_value = True
    
    # Мок для проверки дубликатов - предмета нет в БД
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result
    
    # Вызываем функцию
    result = await process_item_result(
        parser=mock_parser,
        task=mock_task,
        parsed_data=mock_parsed_data,
        filters=mock_filters,
        db_session=mock_db_session,
        redis_service=mock_redis_service,
        task_logger=None
    )
    
    # Проверяем результат
    assert result is True
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_called_once()
    mock_redis_service.publish.assert_called_once()
    assert mock_task.items_found == 1
    assert mock_task.total_checks == 1


@pytest.mark.asyncio
async def test_process_item_result_filters_not_passed(
    mock_parser,
    mock_task,
    mock_parsed_data,
    mock_filters,
    mock_db_session,
    mock_redis_service
):
    """Тест обработки предмета, который не прошел фильтры."""
    # Настраиваем моки - фильтры не пройдены
    mock_parser.filter_service.matches_filters.return_value = False
    
    # Вызываем функцию
    result = await process_item_result(
        parser=mock_parser,
        task=mock_task,
        parsed_data=mock_parsed_data,
        filters=mock_filters,
        db_session=mock_db_session,
        redis_service=mock_redis_service,
        task_logger=None
    )
    
    # Проверяем результат
    assert result is False
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()
    mock_redis_service.publish.assert_not_called()


@pytest.mark.asyncio
async def test_process_item_result_duplicate_listing_id(
    mock_parser,
    mock_task,
    mock_parsed_data,
    mock_filters,
    mock_db_session,
    mock_redis_service
):
    """Тест обработки предмета с дублирующимся listing_id."""
    # Настраиваем моки - фильтры пройдены
    mock_parser.filter_service.matches_filters.return_value = True
    
    # Мок для проверки дубликатов - предмет уже есть в БД
    existing_item = MagicMock()
    existing_item.id = 100
    existing_item.item_data_json = json.dumps({"listing_id": "765177620331184862"})
    
    mock_result_all = MagicMock()
    mock_result_all.scalars.return_value.all.return_value = [existing_item]
    mock_db_session.execute.return_value = mock_result_all
    
    # Вызываем функцию
    result = await process_item_result(
        parser=mock_parser,
        task=mock_task,
        parsed_data=mock_parsed_data,
        filters=mock_filters,
        db_session=mock_db_session,
        redis_service=mock_redis_service,
        task_logger=None
    )
    
    # Проверяем результат - предмет должен быть пропущен
    assert result is False
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_called()
    mock_redis_service.publish.assert_not_called()


@pytest.mark.asyncio
async def test_process_item_result_sticker_prices_requested(
    mock_parser,
    mock_task,
    mock_parsed_data,
    mock_filters,
    mock_db_session,
    mock_redis_service
):
    """Тест запроса цен наклеек, если они нужны для фильтрации."""
    # Добавляем наклейки без цен
    mock_parsed_data.stickers = [
        StickerInfo(name="Sticker 1", position=0, price=None),
        StickerInfo(name="Sticker 2", position=1, price=None)
    ]
    
    # Добавляем фильтр по наклейкам
    from core.models import StickersFilter
    mock_filters.stickers_filter = StickersFilter(
        min_stickers_price=10.0
    )
    
    # Настраиваем моки
    mock_parser.filter_service.matches_filters.return_value = True
    mock_parser.get_stickers_prices.return_value = {
        "Sticker 1": 5.0,
        "Sticker 2": 7.0
    }
    
    # Мок для проверки дубликатов - предмета нет в БД
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result
    
    # Вызываем функцию
    result = await process_item_result(
        parser=mock_parser,
        task=mock_task,
        parsed_data=mock_parsed_data,
        filters=mock_filters,
        db_session=mock_db_session,
        redis_service=mock_redis_service,
        task_logger=None
    )
    
    # Проверяем результат
    assert result is True
    mock_parser.get_stickers_prices.assert_called_once()
    # Проверяем, что цены наклеек обновлены
    assert mock_parsed_data.stickers[0].price == 5.0
    assert mock_parsed_data.stickers[1].price == 7.0
    assert mock_parsed_data.total_stickers_price == 12.0


@pytest.mark.asyncio
async def test_process_item_result_save_error(
    mock_parser,
    mock_task,
    mock_parsed_data,
    mock_filters,
    mock_db_session,
    mock_redis_service
):
    """Тест обработки ошибки при сохранении в БД."""
    # Настраиваем моки
    mock_parser.filter_service.matches_filters.return_value = True
    
    # Мок для проверки дубликатов - предмета нет в БД
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result
    
    # Ошибка при сохранении
    mock_db_session.commit.side_effect = Exception("Database error")
    
    # Вызываем функцию
    result = await process_item_result(
        parser=mock_parser,
        task=mock_task,
        parsed_data=mock_parsed_data,
        filters=mock_filters,
        db_session=mock_db_session,
        redis_service=mock_redis_service,
        task_logger=None
    )
    
    # Проверяем результат
    assert result is False
    mock_db_session.rollback.assert_called_once()
    mock_redis_service.publish.assert_not_called()


def test_serialize_for_json_pydantic_v2():
    """Тест сериализации Pydantic v2 модели."""
    from pydantic import BaseModel
    
    class TestModel(BaseModel):
        name: str
        value: int
    
    obj = TestModel(name="test", value=42)
    result = _serialize_for_json(obj)
    
    assert isinstance(result, dict)
    assert result["name"] == "test"
    assert result["value"] == 42


def test_serialize_for_json_dict():
    """Тест сериализации словаря."""
    obj = {"key": "value", "number": 123}
    result = _serialize_for_json(obj)
    
    assert result == obj


def test_serialize_for_json_list():
    """Тест сериализации списка."""
    obj = [1, 2, 3, {"nested": "value"}]
    result = _serialize_for_json(obj)
    
    assert result == obj


def test_serialize_for_json_primitive():
    """Тест сериализации примитивных типов."""
    assert _serialize_for_json("string") == "string"
    assert _serialize_for_json(42) == 42
    assert _serialize_for_json(3.14) == 3.14
    assert _serialize_for_json(True) is True
    assert _serialize_for_json(None) is None

