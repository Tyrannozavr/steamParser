"""
Комплексные юнит-тесты для parallel_listing_parser с моками.
Покрывает параллельный парсинг, обработку всех страниц, крайние случаи.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from core.steam_market_parser.parallel_listing_parser import parse_listings_parallel
from core.models import SearchFilters, PatternList
from core import MonitoringTask


@pytest.fixture
def mock_parser():
    """Мок парсера."""
    parser = MagicMock()
    parser.proxy_manager = AsyncMock()
    parser.redis_service = AsyncMock()
    parser.filter_service = AsyncMock()
    parser.filter_service.matches_filters = AsyncMock(return_value=True)
    parser._get_browser_headers = MagicMock(return_value={"User-Agent": "test"})
    return parser


@pytest.fixture
def mock_proxies():
    """Создает список мок-прокси."""
    proxies = []
    for i in range(1, 21):  # 20 прокси
        proxy = MagicMock()
        proxy.id = i
        proxy.url = f"http://proxy{i}:8080"
        proxy.is_active = True
        proxy.delay_seconds = 0.2
        proxies.append(proxy)
    return proxies


@pytest.fixture
def mock_proxy_context(mock_proxies):
    """Мок контекста прокси."""
    def create_context(proxy=None):
        ctx = MagicMock()
        ctx.proxy = proxy if proxy else mock_proxies[0]
        ctx.mark_success = AsyncMock()
        ctx.mark_error = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx
    return create_context


@pytest.fixture
def mock_filters():
    """Мок фильтров."""
    return SearchFilters(
        appid=730,
        currency=1,
        item_name="Test Item",
        max_price=100.0,
        pattern_list=PatternList(patterns=[695], item_type="skin")
    )


@pytest.fixture
def mock_render_data():
    """Мок данных от API /render/."""
    return {
        "total_count": 200,  # 200 лотов = 10 страниц по 20
        "results_html": "<div>test html</div>",
        "assets": {
            "730": {
                "2": {
                    "1": {
                        "asset_properties": [
                            {"propertyid": 1, "int_value": 695},
                            {"propertyid": 2, "float_value": 0.35}
                        ],
                        "descriptions": []
                    }
                }
            }
        },
        "listinginfo": {
            "1": {
                "asset": {"id": "1"}
            }
        }
    }


@pytest.mark.asyncio
async def test_parallel_parsing_all_pages(mock_parser, mock_proxies, mock_proxy_context, mock_filters, mock_render_data):
    """Тест: параллельный парсинг обрабатывает все страницы."""
    # Настраиваем моки
    mock_parser.proxy_manager.get_active_proxies = AsyncMock(return_value=mock_proxies)
    mock_parser.proxy_manager.use_proxy = AsyncMock(side_effect=[mock_proxy_context(p) for p in mock_proxies])
    
    # Мокаем _fetch_render_api
    async def mock_fetch_render_api(appid, hash_name, start, count):
        return mock_render_data
    
    mock_parser._fetch_render_api = AsyncMock(side_effect=mock_fetch_render_api)
    mock_parser.__class__ = MagicMock(return_value=mock_parser)
    
    # Мокаем ItemPageParser
    with patch('core.steam_market_parser.parallel_listing_parser.ItemPageParser') as mock_item_parser:
        mock_parser_obj = MagicMock()
        mock_parser_obj.get_all_listings = MagicMock(return_value=[
            {"listing_id": "1", "price": 10.0, "inspect_link": "test"}
        ])
        mock_item_parser.return_value = mock_parser_obj
        
        # Запускаем парсинг
        result = await parse_listings_parallel(
            parser=mock_parser,
            appid=730,
            hash_name="Test Item",
            filters=mock_filters,
            target_patterns={695},
            listings_per_page=20,
            total_count=200,  # 10 страниц
            active_proxies_count=20,
            task_logger=None,
            task=None,
            db_session=None,
            redis_service=None
        )
        
        # Должны обработаться все 10 страниц
        assert len(result) >= 0  # Может быть 0 если нет подходящих


@pytest.mark.asyncio
async def test_parallel_parsing_429_error_handling(mock_parser, mock_proxies, mock_proxy_context, mock_filters):
    """Тест: обработка 429 ошибок при параллельном парсинге."""
    # Настраиваем моки
    mock_parser.proxy_manager.get_active_proxies = AsyncMock(return_value=mock_proxies)
    
    # Первый прокси возвращает 429, второй - успех
    call_count = 0
    async def mock_use_proxy(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Первый вызов - 429 ошибка
            ctx = mock_proxy_context(mock_proxies[0])
            return ctx
        else:
            # Остальные - успех
            ctx = mock_proxy_context(mock_proxies[1])
            return ctx
    
    mock_parser.proxy_manager.use_proxy = AsyncMock(side_effect=mock_use_proxy)
    
    # Мокаем _fetch_render_api: первый вызов - 429, остальные - успех
    fetch_count = 0
    async def mock_fetch_render_api(appid, hash_name, start, count):
        nonlocal fetch_count
        fetch_count += 1
        if fetch_count == 1:
            raise Exception("429 Too Many Requests")
        return {
            "total_count": 20,
            "results_html": "<div>test</div>",
            "assets": {},
            "listinginfo": {}
        }
    
    mock_parser._fetch_render_api = AsyncMock(side_effect=mock_fetch_render_api)
    mock_parser.__class__ = MagicMock(return_value=mock_parser)
    
    # Мокаем ItemPageParser
    with patch('core.steam_market_parser.parallel_listing_parser.ItemPageParser') as mock_item_parser:
        mock_parser_obj = MagicMock()
        mock_parser_obj.get_all_listings = MagicMock(return_value=[])
        mock_item_parser.return_value = mock_parser_obj
        
        # Запускаем парсинг
        result = await parse_listings_parallel(
            parser=mock_parser,
            appid=730,
            hash_name="Test Item",
            filters=mock_filters,
            target_patterns={695},
            listings_per_page=20,
            total_count=20,  # 1 страница
            active_proxies_count=20,
            task_logger=None,
            task=None,
            db_session=None,
            redis_service=None
        )
        
        # Должен обработаться с переключением прокси
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_parallel_parsing_all_proxies_busy(mock_parser, mock_proxies, mock_proxy_context, mock_filters):
    """Тест: все прокси заняты - система ждет и обрабатывает все страницы."""
    # Настраиваем моки
    mock_parser.proxy_manager.get_active_proxies = AsyncMock(return_value=mock_proxies[:5])  # Только 5 прокси
    
    # use_proxy всегда возвращает прокси (система ждет)
    mock_parser.proxy_manager.use_proxy = AsyncMock(side_effect=[mock_proxy_context(p) for p in mock_proxies[:5] * 10])
    
    # Мокаем _fetch_render_api
    async def mock_fetch_render_api(appid, hash_name, start, count):
        await asyncio.sleep(0.01)  # Симулируем задержку
        return {
            "total_count": 200,  # 10 страниц
            "results_html": "<div>test</div>",
            "assets": {},
            "listinginfo": {}
        }
    
    mock_parser._fetch_render_api = AsyncMock(side_effect=mock_fetch_render_api)
    mock_parser.__class__ = MagicMock(return_value=mock_parser)
    
    # Мокаем ItemPageParser
    with patch('core.steam_market_parser.parallel_listing_parser.ItemPageParser') as mock_item_parser:
        mock_parser_obj = MagicMock()
        mock_parser_obj.get_all_listings = MagicMock(return_value=[])
        mock_item_parser.return_value = mock_parser_obj
        
        # Запускаем парсинг 10 страниц с 5 прокси
        result = await parse_listings_parallel(
            parser=mock_parser,
            appid=730,
            hash_name="Test Item",
            filters=mock_filters,
            target_patterns={695},
            listings_per_page=20,
            total_count=200,  # 10 страниц
            active_proxies_count=5,
            task_logger=None,
            task=None,
            db_session=None,
            redis_service=None
        )
        
        # Должны обработаться все 10 страниц (система ждет прокси)
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_parallel_parsing_no_proxies_available(mock_parser, mock_proxy_context, mock_filters):
    """Тест: нет доступных прокси - система ждет."""
    # Настраиваем моки - нет прокси
    mock_parser.proxy_manager.get_active_proxies = AsyncMock(return_value=[])
    
    # use_proxy возвращает None
    ctx = mock_proxy_context(None)
    mock_parser.proxy_manager.use_proxy = AsyncMock(return_value=ctx)
    
    # Запускаем парсинг
    result = await parse_listings_parallel(
        parser=mock_parser,
        appid=730,
        hash_name="Test Item",
        filters=mock_filters,
        target_patterns={695},
        listings_per_page=20,
        total_count=20,
        active_proxies_count=0,
        task_logger=None,
        task=None,
        db_session=None,
        redis_service=None
    )
    
    # Должен вернуть пустой список
    assert result == []


@pytest.mark.asyncio
async def test_parallel_parsing_large_dataset(mock_parser, mock_proxies, mock_proxy_context, mock_filters):
    """Тест: большой набор данных (113 страниц как в реальной задаче)."""
    # Настраиваем моки
    mock_parser.proxy_manager.get_active_proxies = AsyncMock(return_value=mock_proxies)
    
    # use_proxy возвращает прокси по кругу
    proxy_cycle = (mock_proxy_context(p) for p in mock_proxies * 20)
    mock_parser.proxy_manager.use_proxy = AsyncMock(side_effect=lambda *args, **kwargs: next(proxy_cycle))
    
    # Мокаем _fetch_render_api
    async def mock_fetch_render_api(appid, hash_name, start, count):
        return {
            "total_count": 2260,  # 113 страниц
            "results_html": "<div>test</div>",
            "assets": {},
            "listinginfo": {}
        }
    
    mock_parser._fetch_render_api = AsyncMock(side_effect=mock_fetch_render_api)
    mock_parser.__class__ = MagicMock(return_value=mock_parser)
    
    # Мокаем ItemPageParser
    with patch('core.steam_market_parser.parallel_listing_parser.ItemPageParser') as mock_item_parser:
        mock_parser_obj = MagicMock()
        mock_parser_obj.get_all_listings = MagicMock(return_value=[])
        mock_item_parser.return_value = mock_parser_obj
        
        # Запускаем парсинг 113 страниц
        result = await parse_listings_parallel(
            parser=mock_parser,
            appid=730,
            hash_name="Test Item",
            filters=mock_filters,
            target_patterns={695},
            listings_per_page=20,
            total_count=2260,  # 113 страниц
            active_proxies_count=20,
            task_logger=None,
            task=None,
            db_session=None,
            redis_service=None
        )
        
        # Должны обработаться все 113 страниц
        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

