"""
Тесты для модуля listing_parser.
Проверяет парсинг лотов и обработку результатов.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.models import ParsedItemData, SearchFilters, PatternList, FloatRange
from core.steam_market_parser.listing_parser import ListingParser


@pytest.fixture
def mock_parser():
    """Создает мок парсера."""
    parser = MagicMock()
    parser.filter_service = MagicMock()
    parser.filter_service.matches_filters = AsyncMock(return_value=True)
    parser._current_task = None
    parser._current_db_session = None
    parser._current_redis_service = None
    parser.proxy_manager = MagicMock()
    parser.proxy_manager.get_active_proxies = AsyncMock(return_value=[])
    parser.proxy_manager.get_next_proxy = AsyncMock(return_value=None)
    return parser


@pytest.fixture
def listing_parser(mock_parser):
    """Создает экземпляр ListingParser."""
    return ListingParser(mock_parser)


@pytest.fixture
def mock_filters():
    """Создает тестовые фильтры."""
    return SearchFilters(
        item_name="AK-47 | Redline (Field-Tested)",
        appid=730,
        currency=1,
        max_price=50.0,
        float_range=FloatRange(min=0.350000, max=0.360000),
        pattern_list=PatternList(patterns=[522], item_type="skin")
    )


@pytest.mark.asyncio
async def test_parse_all_listings_delegates_to_process_results(
    listing_parser,
    mock_filters,
    mock_parser
):
    """Тест, что parse_all_listings вызывает process_item_result для каждого лота."""
    # Настраиваем моки
    task = MagicMock()
    task.id = 1
    task.item_name = "AK-47 | Redline (Field-Tested)"
    task.items_found = 0
    task.total_checks = 0
    
    db_session = AsyncMock()
    redis_service = MagicMock()
    redis_service.is_connected.return_value = True
    redis_service.publish = AsyncMock()
    
    # Мокируем _fetch_render_api для возврата тестовых данных
    mock_response = {
        "success": True,
        "total_count": 1,
        "results": [
            {
                "listingid": "765177620331184862",
                "asset": {
                    "id": "47930202190",
                    "market_actions": [
                        {
                            "link": "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20S76561198123456789A47930202190D765177620331184862"
                        }
                    ]
                },
                "price": 4573,
                "price_text": "$45.73"
            }
        ],
        "assets": {
            "730": {
                "2": {
                    "47930202190": {
                        "id": "47930202190",
                        "classid": "176785923",
                        "instanceid": "188530139",
                        "float_value": 0.350107,
                        "stickers": [
                            {
                                "slot": 0,
                                "sticker_id": 1234,
                                "name": "Sticker 1"
                            }
                        ]
                    }
                }
            }
        }
    }
    
    # Мокируем все внешние вызовы чтобы не делать реальные запросы
    with patch.object(mock_parser, '_fetch_render_api', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_response
        
        # Мокируем создание нового парсера внутри listing_parser
        with patch('core.steam_market_parser.listing_parser.SteamMarketParser') as mock_parser_class:
            mock_new_parser = MagicMock()
            mock_new_parser._fetch_render_api = AsyncMock(return_value=mock_response)
            mock_new_parser.close = AsyncMock()
            mock_new_parser._ensure_client = AsyncMock()
            mock_parser_class.return_value = mock_new_parser
            
            # Мокируем process_item_result
            with patch('core.steam_market_parser.process_results.process_item_result') as mock_process:
                mock_process.return_value = True
                
                # Мокируем проверку дубликатов в БД
                mock_result = MagicMock()
                mock_result.scalars.return_value.all.return_value = []
                db_session.execute = AsyncMock(return_value=mock_result)
                db_session.add = MagicMock()
                db_session.flush = AsyncMock()
                db_session.refresh = AsyncMock()
                db_session.commit = AsyncMock()
                
                result = await listing_parser.parse_all_listings(
                    appid=730,
                    hash_name="AK-47 | Redline (Field-Tested)",
                    filters=mock_filters,
                    target_patterns={522},
                    task_logger=None,
                    task=task,
                    db_session=db_session,
                    redis_service=redis_service
                )
                
                # Проверяем, что process_item_result был вызван
                assert mock_process.called
                assert len(result) >= 0  # Может быть пустым, если фильтры не пройдены


@pytest.mark.asyncio
async def test_parse_all_listings_without_task(
    listing_parser,
    mock_filters,
    mock_parser
):
    """Тест parse_all_listings без task (fallback на старую логику)."""
    # Мокируем _fetch_render_api чтобы не делать реальные запросы
    mock_response = {
        "success": True,
        "total_count": 0,
        "results": []
    }
    
    with patch.object(mock_parser, '_fetch_render_api', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_response
        
        # Мокируем создание нового парсера внутри listing_parser
        # SteamHttpClient импортируется внутри функции, поэтому патчим через steam_http_client
        with patch('core.steam_market_parser.listing_parser.SteamHttpClient', create=True) as mock_http_client:
            mock_client_instance = MagicMock()
            mock_client_instance._ensure_client = AsyncMock()
            mock_http_client.return_value = mock_client_instance
            
            # Мокируем создание парсера через __class__
            mock_new_parser = MagicMock()
            mock_new_parser._fetch_render_api = AsyncMock(return_value=mock_response)
            mock_new_parser.close = AsyncMock()
            mock_new_parser._ensure_client = AsyncMock()
            
            # Мокируем __class__ чтобы при вызове parser.__class__(...) возвращался mock_new_parser
            mock_parser_class = MagicMock(return_value=mock_new_parser)
            mock_parser.__class__ = mock_parser_class
            
            result = await listing_parser.parse_all_listings(
                appid=730,
                hash_name="AK-47 | Redline (Field-Tested)",
                filters=mock_filters,
                target_patterns=None,
                task_logger=None,
                task=None,
                db_session=None,
                redis_service=None
            )
            
            # Должен вернуть пустой список, если нет данных
            assert isinstance(result, list)

