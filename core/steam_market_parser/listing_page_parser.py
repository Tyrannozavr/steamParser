"""
Модуль для парсинга страниц конкретных лотов.
Отвечает за парсинг страницы конкретного лота для получения данных (float, pattern, наклейки).
"""
from typing import Optional
from loguru import logger

from ..models import ParsedItemData
from parsers import ItemPageParser
from parsers.inspect_parser import InspectLinkParser
from parsers.item_type_detector import detect_item_type


async def parse_listing_page(
    parser,
    appid: int,
    hash_name: str,
    listing_id: str
) -> Optional[ParsedItemData]:
    """
    Парсит страницу конкретного лота для получения данных (float, pattern, наклейки).
    Использует кэш Redis для избежания повторных запросов.
    
    Args:
        parser: Экземпляр SteamMarketParser для использования его методов
        appid: ID приложения
        hash_name: Хэш-имя предмета
        listing_id: ID лота
        
    Returns:
        ParsedItemData или None
    """
    try:
        # Проверяем кэш
        if parser.redis_service and parser.redis_service.is_connected():
            cached_data = await parser.redis_service.get_cached_parsed_item(listing_id)
            if cached_data:
                logger.info(f"💾 Используем закэшированные данные для listing_id={listing_id}")
                try:
                    from ..models import StickerInfo
                    stickers = []
                    if cached_data.get('stickers'):
                        stickers = [StickerInfo(**s) if isinstance(s, dict) else s for s in cached_data['stickers']]
                    
                    return ParsedItemData(
                        float_value=cached_data.get('float_value'),
                        pattern=cached_data.get('pattern'),
                        stickers=stickers,
                        total_stickers_price=cached_data.get('total_stickers_price', 0.0),
                        item_name=cached_data.get('item_name'),
                        item_price=cached_data.get('item_price'),
                        inspect_links=cached_data.get('inspect_links', []),
                        item_type=cached_data.get('item_type'),
                        is_stattrak=cached_data.get('is_stattrak', False)
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка при восстановлении данных из кэша для listing_id={listing_id}: {e}, парсим заново")
        
        # Кэша нет - парсим страницу
        logger.info(f"🔍 Парсим страницу лота listing_id={listing_id} (кэш не найден)")
        html = await parser._fetch_listing_page(appid, hash_name, listing_id)
        if html is None:
            return None
        
        parser_obj = ItemPageParser(html)
        parsed = await parser_obj.parse_all(
            fetch_sticker_prices=False,
            fetch_item_price=True,
            proxy=parser.proxy,
            redis_service=parser.redis_service,
            proxy_manager=parser.proxy_manager
        )
        
        item_name = hash_name
        parsed_item_name = parser_obj.get_item_name()
        if parsed_item_name:
            logger.debug(f"    🔍 Локализованное название со страницы: '{parsed_item_name}', используем английское: '{item_name}'")
        item_price = parser_obj.get_item_price()
        inspect_links = parser_obj.get_inspect_links()
        
        float_value = parsed.get('float_value')
        pattern = parsed.get('pattern')
        
        if (float_value is None or pattern is None) and inspect_links:
            logger.info(f"    🔍 Пытаемся получить float/pattern через inspect API (найдено {len(inspect_links)} ссылок)")
            for idx, inspect_link in enumerate(inspect_links):
                logger.info(f"    📎 Inspect ссылка [{idx + 1}/{len(inspect_links)}]: {inspect_link[:100]}...")
                inspect_data = await InspectLinkParser.get_float_from_multiple_sources(
                    inspect_link,
                    proxy=parser.proxy,
                    proxy_manager=parser.proxy_manager
                )
                if inspect_data:
                    if float_value is None:
                        float_value = inspect_data.get('float_value')
                        if float_value is not None:
                            logger.info(f"    ✅ Float получен через inspect API: {float_value}")
                    if pattern is None:
                        pattern = inspect_data.get('pattern')
                        if pattern is not None:
                            logger.info(f"    ✅ Pattern получен через inspect API: {pattern}")
                    if float_value is not None and pattern is not None:
                        logger.info(f"    ✅ Получены все данные из inspect ссылки [{idx + 1}], прекращаем проверку остальных")
                        break
                else:
                    logger.debug(f"    ⚠️ Не удалось получить данные из inspect ссылки [{idx + 1}]")
            if float_value is None and pattern is None:
                logger.warning(f"    ⚠️ Не удалось получить данные ни из одной inspect ссылки ({len(inspect_links)} проверено)")
        
        item_type = detect_item_type(
            item_name or "",
            float_value is not None,
            len(parsed.get('stickers', [])) > 0
        )
        
        if pattern is not None and pattern > 999:
            item_type = "keychain"
            logger.debug(f"    🔍 parse_listing_page: Определен тип по паттерну: keychain (паттерн={pattern} > 999)")
        
        is_stattrak = parser_obj.is_stattrak()

        parsed_data = ParsedItemData(
            float_value=float_value,
            pattern=pattern,
            stickers=parsed.get('stickers', []),
            total_stickers_price=parsed.get('total_stickers_price', 0.0),
            item_name=item_name,
            item_price=item_price,
            inspect_links=inspect_links,
            item_type=item_type,
            is_stattrak=is_stattrak
        )
        
        # Сохраняем в кэш
        if parser.redis_service and parser.redis_service.is_connected():
            try:
                cache_data = {
                    'float_value': float_value,
                    'pattern': pattern,
                    'stickers': [s.model_dump() if hasattr(s, 'model_dump') else s for s in parsed.get('stickers', [])],
                    'total_stickers_price': parsed.get('total_stickers_price', 0.0),
                    'item_name': item_name,
                    'item_price': item_price,
                    'inspect_links': inspect_links,
                    'item_type': item_type,
                    'is_stattrak': is_stattrak
                }
                await parser.redis_service.cache_parsed_item(listing_id, cache_data, ttl=86400)
                logger.info(f"💾 Данные парсинга для listing_id={listing_id} сохранены в кэш")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при сохранении в кэш для listing_id={listing_id}: {e}")
        
        return parsed_data
    except Exception as e:
        logger.error(f"Ошибка при парсинге лота {listing_id}: {e}")
        return None

