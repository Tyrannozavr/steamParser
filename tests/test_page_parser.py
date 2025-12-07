"""
Тесты для модуля page_parser.
Проверяет делегирование методов парсинга страниц.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.models import SearchFilters
from core.steam_market_parser.page_parser import PageParser


@pytest.fixture
def mock_parser():
    """Создает мок парсера."""
    parser = MagicMock()
    parser._ensure_client = AsyncMock()
    return parser


@pytest.fixture
def mock_listing_parser():
    """Создает мок парсера лотов."""
    return MagicMock()


@pytest.fixture
def page_parser(mock_parser, mock_listing_parser):
    """Создает экземпляр PageParser."""
    return PageParser(mock_parser, mock_listing_parser)


@pytest.fixture
def mock_filters():
    """Создает тестовые фильтры."""
    return SearchFilters(
        item_name="AK-47 | Redline (Field-Tested)",
        appid=730,
        currency=1
    )


@pytest.mark.asyncio
async def test_build_url_pool(page_parser, mock_filters):
    """Тест делегирования build_url_pool."""
    with patch('core.steam_market_parser.page_parser.build_url_pool') as mock_build:
        mock_build.return_value = [{"type": "query", "url": "test"}]
        
        result = await page_parser.build_url_pool(mock_filters, "exact_name")
        
        assert result == [{"type": "query", "url": "test"}]
        mock_build.assert_called_once_with(page_parser.parser, mock_filters, "exact_name")


@pytest.mark.asyncio
async def test_process_url_pool(page_parser, mock_filters):
    """Тест делегирования process_url_pool."""
    url_pool = [{"type": "query", "url": "test"}]
    task = MagicMock()
    db_session = MagicMock()
    redis_service = MagicMock()
    
    with patch('core.steam_market_parser.page_parser.process_url_pool') as mock_process:
        mock_process.return_value = {"success": True, "results": []}
        
        result = await page_parser.process_url_pool(
            url_pool, mock_filters,
            task=task,
            db_session=db_session,
            redis_service=redis_service
        )
        
        assert result == {"success": True, "results": []}
        mock_process.assert_called_once_with(
            page_parser.parser,
            page_parser.listing_parser,
            url_pool,
            mock_filters,
            task=task,
            db_session=db_session,
            redis_service=redis_service
        )


@pytest.mark.asyncio
async def test_process_url_pool_creates_listing_parser(page_parser, mock_filters):
    """Тест создания listing_parser, если он не был передан."""
    page_parser.listing_parser = None
    url_pool = [{"type": "query", "url": "test"}]
    
    with patch('core.steam_market_parser.page_parser.process_url_pool') as mock_process:
        with patch('core.steam_market_parser.listing_parser.ListingParser') as mock_listing_class:
            mock_listing_instance = MagicMock()
            mock_listing_class.return_value = mock_listing_instance
            mock_process.return_value = {"success": True}
            
            await page_parser.process_url_pool(url_pool, mock_filters)
            
            mock_listing_class.assert_called_once_with(page_parser.parser)
            assert page_parser.listing_parser == mock_listing_instance


@pytest.mark.asyncio
async def test_parse_all_pages_parallel(page_parser, mock_filters):
    """Тест делегирования parse_all_pages_parallel."""
    params = {"start": 0, "count": 100}
    items = []
    task_logger = MagicMock()
    
    with patch('core.steam_market_parser.page_parser.parse_all_pages_parallel') as mock_parallel:
        await page_parser.parse_all_pages_parallel(
            mock_filters, params, items, 100, 0, 100, 1, 3, 5.0, task_logger, 1
        )
        
        mock_parallel.assert_called_once_with(
            page_parser.parser,
            mock_filters,
            params,
            items,
            100, 0, 100, 1, 3, 5.0, task_logger, 1
        )


@pytest.mark.asyncio
async def test_parse_item_page(page_parser):
    """Тест делегирования _parse_item_page."""
    with patch('core.steam_market_parser.item_page_parser.parse_item_page') as mock_parse:
        mock_parse.return_value = MagicMock()
        
        result = await page_parser._parse_item_page(730, "hash_name", "listing_id", {1, 2})
        
        mock_parse.assert_called_once_with(
            page_parser.parser,
            730,
            "hash_name",
            "listing_id",
            {1, 2}
        )

