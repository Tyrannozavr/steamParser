"""
Модуль для формирования пула URL'ов.
Отвечает за создание списка URL'ов для парсинга (query страницы + прямая страница предмета).
"""
from typing import Optional, List, Dict, Any
from loguru import logger
from urllib.parse import quote

from ..models import SearchFilters


async def build_url_pool(
    parser,
    filters: SearchFilters,
    exact_hash_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Формирует пул URL'ов для задачи.
    Использует ТОЛЬКО прямую страницу предмета (как в браузере).
    Query API не используется - достаточно парсить только листинг конкретного предмета.
    
    Args:
        parser: Экземпляр SteamMarketParser для использования его методов
        filters: Параметры поиска
        exact_hash_name: Точное название предмета (обязательно)
        
    Returns:
        Список словарей с информацией о URL'ах для запроса (только direct)
    """
    url_pool = []
    
    logger.info(f"🔍 Формируем пул URL'ов для задачи '{filters.item_name}'...")
    
    # ВАЖНО: Используем ТОЛЬКО прямую страницу предмета (как в браузере)
    # Query API не нужен - мы уже знаем точное hash_name через searchsuggestionsresults
    if not exact_hash_name:
        logger.warning(f"⚠️ exact_hash_name не указан, используем filters.item_name: '{filters.item_name}'")
        exact_hash_name = filters.item_name
    
    if exact_hash_name:
        direct_url = f"https://steamcommunity.com/market/listings/{filters.appid}/{quote(exact_hash_name)}/render/"
        direct_params = {
            "query": "",
            "start": 0,
            "count": 20,  # ВАЖНО: Максимальное значение count=20
            "country": "BY",
            "language": "english",
            "currency": filters.currency
        }
        
        # ВАЖНО: Не делаем предварительный запрос для определения количества
        # Количество определится при обработке через parse_all_listings
        # Это экономит один запрос и работает так же, как браузер
        
        # Добавляем прямую страницу в пул (только один URL, parse_all_listings сам обработает все страницы)
        url_pool.append({
            "type": "direct",
            "url": direct_url,
            "params": {**direct_params, "start": 0, "count": 20},
            "page": 1,
            "total_pages": 1,  # Будет определено в parse_all_listings
            "hash_name": exact_hash_name,
            "total_count": None  # Будет определено при обработке
        })
        logger.info(f"✅ Добавлена прямая страница в пул для '{exact_hash_name}' (количество будет определено при обработке)")
    else:
        logger.error(f"❌ Не удалось определить exact_hash_name для '{filters.item_name}'")
    
    logger.info(f"📋 Итого в пуле: {len(url_pool)} URL'ов (только direct страницы)")
    return url_pool

