"""
Модуль для парсинга страниц предметов.
Отвечает за парсинг страницы предмета и извлечение данных (float, pattern, наклейки).
"""
from typing import Optional
from loguru import logger

from ..models import ParsedItemData
from parsers import ItemPageParser
from parsers.inspect_parser import InspectLinkParser
from parsers.item_type_detector import detect_item_type


async def parse_item_page(
    parser,
    appid: int,
    hash_name: str,
    listing_id: Optional[str] = None,
    target_patterns: Optional[set] = None
) -> Optional[ParsedItemData]:
    """
    Парсит страницу предмета и извлекает детальные данные.
    Использует кэш Redis по listing_id для избежания повторных запросов.

    Args:
        parser: Экземпляр SteamMarketParser для использования его методов
        appid: ID приложения
        hash_name: Хэш-имя предмета
        listing_id: Опциональный ID конкретного лота (если известен)
        target_patterns: Опциональный set паттернов для фильтрации

    Returns:
        ParsedItemData или None при ошибке
    """
    try:
        cache_key = None
        if listing_id:
            cache_key = f"parsed_item:{appid}:{hash_name}:{listing_id}"
        elif parser.redis_service:
            html = await parser._fetch_item_page(appid, hash_name)
            if html:
                parser_temp = ItemPageParser(html)
                inspect_links = parser_temp.get_inspect_links()
                if inspect_links:
                    inspect_params = InspectLinkParser.parse_inspect_link(inspect_links[0])
                    if inspect_params and inspect_params.get('listingid'):
                        listing_id = inspect_params['listingid']
                        cache_key = f"parsed_item:{appid}:{hash_name}:{listing_id}"
                        logger.info(f"    🔑 Извлечен listing_id из inspect ссылки: {listing_id}")
        
        logger.info(f"    🔍 DEBUG parse_item_page: appid={appid}, hash_name={hash_name}, listing_id={listing_id}")
        logger.info(f"    🔍 DEBUG parse_item_page: target_patterns={target_patterns}")
        
        # Проверяем кэш
        if cache_key and parser.redis_service and parser.redis_service.is_connected():
            cached_data = await parser.redis_service.get_json(cache_key)
            if cached_data:
                cached_pattern = cached_data.get('pattern')
                if target_patterns and cached_pattern is not None:
                    if cached_pattern not in target_patterns:
                        logger.info(f"    🔄 Паттерн {cached_pattern} из кэша не совпадает с фильтром {target_patterns}, проверяем все inspect ссылки")
                        cached_data = None
                
                if cached_data:
                    logger.info(f"    📦 Использован кэш Redis для {hash_name} (listing_id: {listing_id or 'нет'})")
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
                        logger.warning(f"    ⚠️ Ошибка при восстановлении данных из кэша: {e}, парсим заново")
        
        # Кэша нет или ошибка - парсим страницу
        html = await parser._fetch_item_page(appid, hash_name)
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
        
        api_price = parsed.get('item_price_from_api')
        if item_price is None and api_price is not None:
            logger.info(f"    💰 Цена со страницы не найдена, используем цену из API: ${api_price:.2f}")
            item_price = api_price
        elif item_price is not None:
            logger.info(f"    💰 Используем цену со страницы конкретного предмета: ${item_price:.2f}")
        elif api_price is not None:
            logger.info(f"    💰 Используем цену из API (fallback): ${api_price:.2f}")
            item_price = api_price

        float_value = parsed.get('float_value')
        pattern = parsed.get('pattern')
        
        if not listing_id and inspect_links:
            inspect_params = InspectLinkParser.parse_inspect_link(inspect_links[0])
            if inspect_params and inspect_params.get('listingid'):
                listing_id = inspect_params['listingid']
                cache_key = f"parsed_item:{appid}:{hash_name}:{listing_id}"
                logger.info(f"    🔑 Извлечен listing_id из inspect ссылки: {listing_id}")
        
        # Если не нашли на странице, пробуем через inspect API
        should_check_inspect = (
            (float_value is None or pattern is None) or
            (target_patterns and (pattern is None or pattern not in target_patterns))
        )
        if should_check_inspect and inspect_links:
            logger.info(f"    🔍 Пытаемся получить float/pattern через inspect API (найдено {len(inspect_links)} ссылок)")
            if target_patterns:
                logger.info(f"    🎯 Ищем паттерн из списка: {target_patterns}")
                if pattern is not None and pattern not in target_patterns:
                    logger.info(f"    🔄 Паттерн {pattern} не совпадает с фильтром, сбрасываем и проверяем все inspect ссылки")
                    pattern = None
                    float_value = None
            
            for idx, inspect_link in enumerate(inspect_links):
                logger.info(f"    📎 Inspect ссылка [{idx + 1}/{len(inspect_links)}]: {inspect_link[:100]}...")
                
                inspect_params = InspectLinkParser.parse_inspect_link(inspect_link)
                link_listing_id = inspect_params.get('listingid') if inspect_params else None
                
                if link_listing_id and parser.redis_service and parser.redis_service.is_connected():
                    link_cache_key = f"parsed_item:{appid}:{hash_name}:{link_listing_id}"
                    cached_link_data = await parser.redis_service.get_json(link_cache_key)
                    if cached_link_data:
                        logger.info(f"    📦 Использован кэш для listing_id={link_listing_id} из inspect ссылки [{idx + 1}]")
                        cached_pattern = cached_link_data.get('pattern')
                        cached_float = cached_link_data.get('float_value')
                        
                        if target_patterns and cached_pattern is not None:
                            if cached_pattern in target_patterns:
                                logger.info(f"    ✅ Найден нужный паттерн {cached_pattern} в кэше для listing_id={link_listing_id}")
                                if float_value is None:
                                    float_value = cached_float
                                pattern = cached_pattern
                                break
                            else:
                                logger.debug(f"    ⏭️ Паттерн {cached_pattern} не совпадает с фильтром, продолжаем поиск")
                                continue
                        
                        if float_value is None:
                            float_value = cached_float
                        if pattern is None:
                            pattern = cached_pattern
                        if float_value is not None and pattern is not None:
                            logger.info(f"    ✅ Получены все данные из кэша для listing_id={link_listing_id}")
                            if not target_patterns:
                                break
                        continue
                
                inspect_data = await InspectLinkParser.get_float_from_multiple_sources(
                    inspect_link,
                    proxy=parser.proxy,
                    proxy_manager=parser.proxy_manager
                )
                if inspect_data:
                    link_pattern = inspect_data.get('pattern')
                    link_float = inspect_data.get('float_value')
                    
                    if target_patterns and link_pattern is not None:
                        if link_pattern in target_patterns:
                            logger.info(f"    ✅ Найден нужный паттерн {link_pattern} из inspect ссылки [{idx + 1}]")
                            float_value = link_float
                            pattern = link_pattern
                            break
                        else:
                            logger.error(f"    ⏭️ Паттерн {link_pattern} не совпадает с фильтром {target_patterns}, продолжаем поиск")
                            continue
                    
                    if float_value is None:
                        float_value = link_float
                        if float_value is not None:
                            logger.info(f"    ✅ Float получен через inspect API: {float_value}")
                    if pattern is None:
                        pattern = link_pattern
                        if pattern is not None:
                            logger.info(f"    ✅ Pattern получен через inspect API: {pattern}")
                    
                    if link_listing_id and parser.redis_service and parser.redis_service.is_connected():
                        is_stattrak = parser_obj.is_stattrak() if parser_obj else False
                        cache_data = {
                            'float_value': float_value,
                            'pattern': pattern,
                            'stickers': [],
                            'total_stickers_price': 0.0,
                            'item_name': item_name,
                            'item_price': item_price,
                            'inspect_links': [inspect_link],
                            'item_type': None,
                            'is_stattrak': is_stattrak
                        }
                        await parser.redis_service.set_json(link_cache_key, cache_data, ex=3600)
                        logger.info(f"    💾 Данные для listing_id={link_listing_id} сохранены в кэш")
                    
                    if float_value is not None and pattern is not None:
                        if target_patterns:
                            if pattern in target_patterns:
                                logger.info(f"    ✅ Найден нужный паттерн {pattern} из inspect ссылки [{idx + 1}], прекращаем проверку")
                                break
                            else:
                                logger.error(f"    ⏭️ Паттерн {pattern} не совпадает с фильтром {target_patterns}, продолжаем поиск")
                                continue
                        else:
                            logger.info(f"    ✅ Получены все данные из inspect ссылки [{idx + 1}], прекращаем проверку остальных")
                            break
                else:
                    logger.debug(f"    ⚠️ Не удалось получить данные из inspect ссылки [{idx + 1}]")
            
            if float_value is None and pattern is None:
                logger.warning(f"    ⚠️ Не удалось получить данные ни из одной inspect ссылки ({len(inspect_links)} проверено)")
            elif target_patterns and pattern not in target_patterns:
                logger.warning(f"    ⚠️ Не найден нужный паттерн из списка {target_patterns} ({len(inspect_links)} ссылок проверено)")
        elif not inspect_links:
            logger.warning(f"    ⚠️ Inspect ссылки не найдены на странице")

        item_type = detect_item_type(
            item_name or "",
            float_value is not None,
            len(parsed.get('stickers', [])) > 0
        )
        
        if pattern is not None and pattern > 999:
            item_type = "keychain"
            logger.debug(f"    🔍 parse_item_page: Определен тип по паттерну: keychain (паттерн={pattern} > 999)")
        
        is_stattrak = parser_obj.is_stattrak() if parser_obj else False

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
        
        if cache_key and parser.redis_service and parser.redis_service.is_connected():
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
                await parser.redis_service.set_json(cache_key, cache_data, ex=3600)
                logger.info(f"    💾 Данные для {hash_name} (listing_id: {listing_id or 'нет'}) сохранены в кэш")
            except Exception as e:
                logger.warning(f"    ⚠️ Ошибка при сохранении в кэш: {e}")

        return parsed_data
    except Exception as e:
        logger.error(f"Ошибка при парсинге страницы {hash_name}: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return None

