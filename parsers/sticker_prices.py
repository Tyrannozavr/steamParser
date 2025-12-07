"""
Модуль для получения цен наклеек через Steam Market API.
"""
import httpx
from typing import Optional, Dict, List
import asyncio
import json
import re
from urllib.parse import quote
from loguru import logger
from bs4 import BeautifulSoup


class StickerPricesAPI:
    """API для получения цен наклеек."""

    STEAM_MARKET_SUGGESTIONS_URL = "https://steamcommunity.com/market/searchsuggestionsresults"
    STEAM_MARKET_LISTING_URL = "https://steamcommunity.com/market/listings/{appid}/{hash_name}"
    STEAM_MARKET_PRICE_OVERVIEW_URL = "https://steamcommunity.com/market/priceoverview/"
    CACHE_TTL = 3600  # 1 час

    @staticmethod
    async def get_sticker_price(
        sticker_name: str,
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        timeout: int = 10,
        redis_service=None,
        proxy_manager=None
    ) -> Optional[float]:
        """
        Получает цену наклейки через Steam Market API.

        Args:
            sticker_name: Название наклейки (например, "MOUZ | Stockholm 2021")
            appid: ID приложения (730 для CS:GO/CS2)
            currency: Валюта (1 = USD)
            proxy: Опциональный прокси
            timeout: Таймаут запроса
            redis_service: Сервис Redis для кэширования (опционально)

        Returns:
            Цена наклейки в USD или None
        """
        # Проверяем кэш Redis
        if redis_service and redis_service.is_connected():
            try:
                cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                cached_price = await redis_service.get_json(cache_key)
                if cached_price is not None and 'price' in cached_price:
                    logger.info(f"📦 StickerPricesAPI: Использован кэш для наклейки '{sticker_name}': ${cached_price['price']:.2f} (TTL: {StickerPricesAPI.CACHE_TTL}с)")
                    return cached_price['price']
            except Exception as e:
                logger.debug(f"⚠️ StickerPricesAPI: Ошибка при чтении кэша: {e}")
        
        # Сначала пробуем получить цену через priceoverview API (самый точный метод для lowest_price)
        price = await StickerPricesAPI._get_price_from_priceoverview(
            sticker_name, appid, currency, proxy, timeout, redis_service, proxy_manager
        )
        if price is not None:
            return price
        
        # Затем пробуем получить цену напрямую со страницы товара
        price = await StickerPricesAPI._get_price_from_item_page(
            sticker_name, appid, currency, proxy, timeout, redis_service, proxy_manager
        )
        if price is not None:
            return price
        
        # Затем пробуем searchsuggestionsresults API (более точный)
        price = await StickerPricesAPI._get_price_from_suggestions(
            sticker_name, appid, currency, proxy, timeout, redis_service, proxy_manager
        )
        if price is not None:
            return price
        
        # Если все методы не сработали, возвращаем None
        logger.warning(f"❌ StickerPricesAPI: Не удалось получить цену для '{sticker_name}' ни одним из методов")
        return None
    
    @staticmethod
    async def _get_price_from_priceoverview(
        sticker_name: str,
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        timeout: int = 10,
        redis_service=None,
        proxy_manager=None
    ) -> Optional[float]:
        """
        Получает цену через Steam Market priceoverview API.
        Это самый точный метод для получения lowest_price.
        """
        max_retries = 3
        current_proxy_obj = None
        
        for attempt in range(max_retries):
            try:
                # Получаем прокси через proxy_manager, если он доступен
                if proxy_manager and not proxy:
                    current_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=(attempt > 0))
                    if current_proxy_obj:
                        proxy = current_proxy_obj.url
                        logger.debug(f"🌐 StickerPricesAPI: Используем прокси ID={current_proxy_obj.id} из proxy_manager для priceoverview")
                
                # ВАЖНО: Добавляем префикс "Sticker |" если его нет
                # Это нужно для правильного поиска цены наклейки
                query_name = sticker_name
                if not sticker_name.startswith("Sticker"):
                    query_name = f"Sticker | {sticker_name}"
                    logger.debug(f"🔧 StickerPricesAPI: Добавлен префикс 'Sticker |' к названию '{sticker_name}' -> '{query_name}'")
                
                # URL-кодируем название для использования в URL
                encoded_hash_name = quote(query_name, safe='')
                
                # Формируем URL API
                params = {
                    'appid': appid,
                    'currency': currency,
                    'market_hash_name': query_name
                }
                
                logger.debug(f"🌐 StickerPricesAPI: Запрашиваем priceoverview для '{query_name}' (исходное: '{sticker_name}')")
                
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout) as client:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json",
                        "Referer": "https://steamcommunity.com/market/",
                    }
                    
                    response = await client.get(StickerPricesAPI.STEAM_MARKET_PRICE_OVERVIEW_URL, params=params, headers=headers)
                    
                    if response.status_code == 429:
                        logger.warning(f"⚠️ StickerPricesAPI: 429 ошибка при запросе priceoverview для '{sticker_name}'")
                        if current_proxy_obj and proxy_manager:
                            await proxy_manager.mark_proxy_used(
                                current_proxy_obj,
                                success=False,
                                error="429 Too Many Requests",
                                is_429_error=True
                            )
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    if response.status_code != 200:
                        logger.debug(f"⚠️ StickerPricesAPI: priceoverview вернул статус {response.status_code} для '{sticker_name}'")
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    try:
                        data = response.json()
                        lowest_price = data.get('lowest_price')
                        
                        if lowest_price:
                            # Формат: "$5.14 USD" или "$5.14"
                            # Извлекаем число
                            price_match = re.search(r'([\d,]+\.?\d*)', lowest_price.replace(',', ''))
                            if price_match:
                                price_str = price_match.group(1)
                                price = float(price_str)
                                
                                # Помечаем прокси как успешный
                                if current_proxy_obj and proxy_manager:
                                    await proxy_manager.mark_proxy_used(current_proxy_obj, success=True)
                                
                                # Сохраняем в кэш
                                if redis_service and redis_service.is_connected():
                                    try:
                                        cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                                        await redis_service.set_json(
                                            cache_key,
                                            {'price': price, 'sticker_name': sticker_name},
                                            ex=StickerPricesAPI.CACHE_TTL
                                        )
                                        logger.info(f"💾 StickerPricesAPI: Сохранена цена в кэш (priceoverview) для '{sticker_name}': ${price:.2f}")
                                    except Exception as e:
                                        logger.debug(f"⚠️ StickerPricesAPI: Ошибка при сохранении в кэш: {e}")
                                
                                logger.info(f"✅ StickerPricesAPI: Найдена цена через priceoverview API для '{sticker_name}': ${price:.2f}")
                                return price
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"⚠️ StickerPricesAPI: Ошибка при парсинге ответа priceoverview: {e}")
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
            except httpx.TimeoutException:
                logger.debug(f"⚠️ StickerPricesAPI: Timeout при запросе priceoverview для '{sticker_name}'")
                if attempt < max_retries - 1:
                    continue
                return None
            except Exception as e:
                logger.debug(f"⚠️ StickerPricesAPI: Ошибка при запросе priceoverview для '{sticker_name}': {type(e).__name__}: {e}")
                if current_proxy_obj and proxy_manager:
                    await proxy_manager.mark_proxy_used(current_proxy_obj, success=False)
                if attempt < max_retries - 1:
                    continue
                return None
        
        return None
    
    @staticmethod
    async def _get_price_from_item_page(
        sticker_name: str,
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        timeout: int = 10,
        redis_service=None,
        proxy_manager=None
    ) -> Optional[float]:
        """
        Получает цену наклейки напрямую со страницы товара на Steam Market.
        Извлекает цену из элемента market_commodity_order_summary.
        
        Args:
            sticker_name: Название наклейки (например, "HellRaisers (Holo) | Katowice 2015")
            appid: ID приложения (730 для CS:GO/CS2)
            currency: Валюта (1 = USD)
            proxy: Опциональный прокси
            timeout: Таймаут запроса
            redis_service: Сервис Redis для кэширования (опционально)
            proxy_manager: Менеджер прокси (опционально)
        
        Returns:
            Цена наклейки в USD или None
        """
        current_proxy_obj = None
        max_retries = 2  # Меньше попыток, так как это прямой запрос
        
        for attempt in range(max_retries):
            try:
                # Получаем прокси
                if proxy_manager and not proxy:
                    current_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=(attempt > 0))
                    proxy = current_proxy_obj.url if current_proxy_obj else None
                
                # Формируем название наклейки для URL
                # Если название не начинается с "Sticker |", добавляем префикс
                if not sticker_name.startswith("Sticker"):
                    hash_name = f"Sticker | {sticker_name}"
                else:
                    hash_name = sticker_name
                
                # URL-кодируем название для использования в URL
                encoded_hash_name = quote(hash_name, safe='')
                
                # Формируем URL страницы товара
                item_url = StickerPricesAPI.STEAM_MARKET_LISTING_URL.format(
                    appid=appid,
                    hash_name=encoded_hash_name
                )
                
                logger.debug(f"🌐 StickerPricesAPI: Загружаем страницу товара для '{sticker_name}': {item_url}")
                
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout) as client:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Referer": "https://steamcommunity.com/market/",
                    }
                    
                    response = await client.get(item_url, headers=headers)
                    
                    if response.status_code == 429:
                        logger.warning(f"⚠️ StickerPricesAPI: 429 ошибка при загрузке страницы для '{sticker_name}'")
                        if current_proxy_obj and proxy_manager:
                            await proxy_manager.mark_proxy_used(
                                current_proxy_obj,
                                success=False,
                                error="429 Too Many Requests",
                                is_429_error=True
                            )
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    if response.status_code != 200:
                        logger.debug(f"⚠️ StickerPricesAPI: Страница товара вернула статус {response.status_code} для '{sticker_name}'")
                        if attempt < max_retries - 1:
                            continue
                        return None
                    
                    # Парсим HTML
                    html = response.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Детальное логирование для отладки
                    logger.debug(f"📄 StickerPricesAPI: Размер HTML страницы: {len(html)} символов")
                    
                    # Проверяем, есть ли на странице признак товара
                    page_title = soup.find('title')
                    if page_title:
                        logger.debug(f"📄 StickerPricesAPI: Заголовок страницы: {page_title.get_text()[:100]}")
                    
                    # СНАЧАЛА пробуем найти цену в JSON данных (g_rgListingInfo)
                    # Это самый надежный способ, так как данные всегда есть в HTML
                    price_str = None
                    price = None
                    
                    # Вариант 0: Ищем в JSON данных g_rgListingInfo
                    listing_info_match = re.search(r'g_rgListingInfo\s*=\s*({.*?});', html, re.DOTALL)
                    if listing_info_match:
                        try:
                            import json
                            json_str = listing_info_match.group(1)
                            listing_data = json.loads(json_str)
                            logger.debug(f"📊 StickerPricesAPI: Найден g_rgListingInfo с {len(listing_data)} элементами")
                            
                            # Ищем lowest_price или price в данных
                            for key, value in listing_data.items():
                                if isinstance(value, dict):
                                    # Сначала пробуем lowest_price
                                    lowest_price = value.get('lowest_price')
                                    if lowest_price:
                                        # Формат: "$5.14 USD" или "514" (в центах)
                                        if isinstance(lowest_price, str):
                                            # Извлекаем число из строки "$5.14 USD"
                                            price_match = re.search(r'([\d,]+\.?\d*)', lowest_price.replace(',', ''))
                                            if price_match:
                                                price_str = price_match.group(1)
                                                logger.debug(f"✅ StickerPricesAPI: Найдена цена в g_rgListingInfo[{key}].lowest_price: ${price_str}")
                                                break
                                        elif isinstance(lowest_price, (int, float)):
                                            # Если цена в центах, делим на 100
                                            if lowest_price > 1000:  # Вероятно в центах
                                                price_str = str(lowest_price / 100)
                                            else:
                                                price_str = str(lowest_price)
                                            logger.debug(f"✅ StickerPricesAPI: Найдена цена в g_rgListingInfo[{key}].lowest_price (число): ${price_str}")
                                            break
                                    
                                    # ВАЖНО: НЕ используем price из g_rgListingInfo, так как это цена конкретного листинга,
                                    # а не самая низкая цена (lowest_price). Это может привести к неправильным ценам.
                                    # Например, для "Battle Scarred" без префикса может найтись другой предмет с ценой $695.66
                                    # вместо правильной цены $5.15 для "Sticker | Battle Scarred"
                                    # Поэтому пропускаем price и ищем только lowest_price
                        except Exception as e:
                            logger.debug(f"⚠️ StickerPricesAPI: Ошибка при парсинге g_rgListingInfo: {e}")
                    
                    # Вариант 1: Ищем все span с классом market_commodity_orders_header_promote и берем последний (там обычно цена)
                    # Это самый надежный способ, так как цена всегда в последнем span с этим классом
                    if not price_str:
                        all_price_matches = re.findall(
                            r'<span[^>]*class=["\']market_commodity_orders_header_promote["\'][^>]*>\$?([\d,]+\.?\d*)</span>',
                            html,
                            re.IGNORECASE
                        )
                        if all_price_matches:
                            # Берем последний match (там обычно цена, первый - количество)
                            price_str = all_price_matches[-1].replace(',', '')
                            logger.debug(f"✅ StickerPricesAPI: Найдена цена в HTML через regex (вариант 1, найдено {len(all_price_matches)} совпадений): ${price_str}")
                    
                    # Вариант 2: Ищем паттерн с "for sale starting at" и span с классом market_commodity_orders_header_promote
                    if not price_str:
                        price_match_in_html = re.search(
                            r'for sale starting at[^<]*<span[^>]*class=["\']market_commodity_orders_header_promote["\'][^>]*>\$?([\d,]+\.?\d*)</span>',
                            html,
                            re.IGNORECASE | re.DOTALL
                        )
                        if price_match_in_html:
                            price_str = price_match_in_html.group(1).replace(',', '')
                            logger.debug(f"✅ StickerPricesAPI: Найдена цена в HTML через regex (вариант 2): ${price_str}")
                        else:
                            # Вариант 3: Ищем span с классом внутри div с id="market_commodity_forsale"
                            price_match_div = re.search(
                                r'<div[^>]*id=["\']market_commodity_forsale["\'][^>]*>.*?<span[^>]*class=["\']market_commodity_orders_header_promote["\'][^>]*>\$?([\d,]+\.?\d*)</span>',
                                html,
                                re.IGNORECASE | re.DOTALL
                            )
                            if price_match_div:
                                price_str = price_match_div.group(1).replace(',', '')
                                logger.debug(f"✅ StickerPricesAPI: Найдена цена в HTML через regex (вариант 3): ${price_str}")
                            else:
                                # Вариант 4: Ищем просто "starting at" и цену после него
                                price_match_simple = re.search(
                                    r'starting at[^$]*?\$([\d,]+\.?\d*)',
                                    html,
                                    re.IGNORECASE | re.DOTALL
                                )
                                if price_match_simple:
                                    price_str = price_match_simple.group(1).replace(',', '')
                                    logger.debug(f"✅ StickerPricesAPI: Найдена цена в HTML через regex (вариант 4): ${price_str}")
                    
                    # Если нашли цену в HTML, используем её
                    if price_str:
                        try:
                            price = float(price_str)
                            
                            # Помечаем прокси как успешный
                            if current_proxy_obj and proxy_manager:
                                await proxy_manager.mark_proxy_used(current_proxy_obj, success=True)
                            
                            # Сохраняем в кэш
                            if redis_service and redis_service.is_connected():
                                try:
                                    cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                                    await redis_service.set_json(
                                        cache_key,
                                        {'price': price, 'sticker_name': sticker_name},
                                        ex=StickerPricesAPI.CACHE_TTL
                                    )
                                    logger.info(f"💾 StickerPricesAPI: Сохранена цена в кэш (item_page HTML) для '{sticker_name}': ${price:.2f}")
                                except Exception as e:
                                    logger.debug(f"⚠️ StickerPricesAPI: Ошибка при сохранении в кэш: {e}")
                            
                            logger.info(f"✅ StickerPricesAPI: Найдена цена через HTML страницы товара для '{sticker_name}': ${price:.2f}")
                            return price
                        except ValueError as e:
                            logger.debug(f"⚠️ StickerPricesAPI: Ошибка парсинга цены из HTML '{price_str}': {e}")
                    
                    # Ищем элемент с ценой: <div class="market_commodity_order_summary" id="market_commodity_forsale">
                    price_element = soup.find('div', {'id': 'market_commodity_forsale', 'class': 'market_commodity_order_summary'})
                    
                    if not price_element:
                        logger.debug(f"🔍 StickerPricesAPI: Элемент market_commodity_forsale не найден для '{sticker_name}'")
                        # Пробуем альтернативный селектор
                        price_element = soup.find('div', class_='market_commodity_order_summary')
                        if price_element:
                            logger.debug(f"✅ StickerPricesAPI: Найден элемент через альтернативный селектор")
                    
                    # Если не нашли, пробуем найти по id без класса
                    if not price_element:
                        price_element = soup.find('div', id='market_commodity_forsale')
                        if price_element:
                            logger.debug(f"✅ StickerPricesAPI: Найден элемент по id без класса")
                    
                    # Если все еще не нашли, ищем любой элемент с классом market_commodity_order_summary
                    if not price_element:
                        all_summary_elements = soup.find_all('div', class_='market_commodity_order_summary')
                        logger.debug(f"🔍 StickerPricesAPI: Найдено элементов с классом market_commodity_order_summary: {len(all_summary_elements)}")
                        if all_summary_elements:
                            price_element = all_summary_elements[0]
                            logger.debug(f"✅ StickerPricesAPI: Используем первый найденный элемент")
                    
                    # Если все еще не нашли, ищем по тексту "for sale starting at"
                    if not price_element:
                        all_divs = soup.find_all('div')
                        for div in all_divs:
                            text = div.get_text()
                            if 'for sale starting at' in text or 'starting at' in text:
                                price_element = div
                                logger.debug(f"✅ StickerPricesAPI: Найден элемент по тексту 'for sale starting at'")
                                break
                    
                    if price_element:
                        # Сначала пробуем найти цену внутри span с классом market_commodity_orders_header_promote
                        # Это более точный способ, так как цена находится в отдельном span
                        price_str = None
                        
                        # Ищем все span с классом market_commodity_orders_header_promote внутри элемента
                        all_price_spans = price_element.find_all('span', class_='market_commodity_orders_header_promote')
                        logger.debug(f"📄 StickerPricesAPI: Найдено span с классом market_commodity_orders_header_promote: {len(all_price_spans)}")
                        
                        if all_price_spans:
                            # Берем последний span (там обычно цена, первый - количество)
                            price_span = all_price_spans[-1]
                            price_text = price_span.get_text(strip=True)
                            logger.debug(f"📄 StickerPricesAPI: Текст из последнего span: '{price_text}'")
                            
                            # Ищем цену в формате $XXX.XX или просто XXX.XX
                            price_match = re.search(r'\$?([\d,]+\.?\d*)', price_text)
                            if price_match:
                                price_str = price_match.group(1).replace(',', '')
                                logger.debug(f"✅ StickerPricesAPI: Найдена цена в span: ${price_str}")
                        
                        # Если не нашли в span, пробуем извлечь из всего текста элемента
                        if not price_str:
                            # Извлекаем текст, например: "6 for sale starting at $323.33"
                            price_text = price_element.get_text(strip=True)
                            logger.debug(f"📄 StickerPricesAPI: Текст всего элемента: '{price_text}'")
                            
                            # Ищем цену в формате $XXX.XX
                            # Паттерн: $ за которым следуют цифры, точка и еще цифры
                            price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
                            
                            if price_match:
                                price_str = price_match.group(1).replace(',', '')
                                logger.debug(f"✅ StickerPricesAPI: Найдена цена в тексте элемента: ${price_str}")
                        
                        # Если все еще не нашли, ищем во всем HTML страницы
                        if not price_str:
                            # Ищем все span с классом market_commodity_orders_header_promote на всей странице
                            all_spans_on_page = soup.find_all('span', class_='market_commodity_orders_header_promote')
                            logger.debug(f"📄 StickerPricesAPI: Найдено span с классом market_commodity_orders_header_promote на странице: {len(all_spans_on_page)}")
                            
                            for span in reversed(all_spans_on_page):  # Идем с конца (цена обычно последняя)
                                span_text = span.get_text(strip=True)
                                # Проверяем, содержит ли span цену (начинается с $ или только цифры с точкой)
                                if re.match(r'^\$?[\d,]+\.\d+$', span_text):
                                    price_match = re.search(r'\$?([\d,]+\.?\d*)', span_text)
                                    if price_match:
                                        price_str = price_match.group(1).replace(',', '')
                                        logger.debug(f"✅ StickerPricesAPI: Найдена цена в span на странице: ${price_str}")
                                        break
                        
                        if price_str:
                            try:
                                price = float(price_str)
                                
                                # Помечаем прокси как успешный
                                if current_proxy_obj and proxy_manager:
                                    await proxy_manager.mark_proxy_used(current_proxy_obj, success=True)
                                
                                # Сохраняем в кэш
                                if redis_service and redis_service.is_connected():
                                    try:
                                        cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                                        await redis_service.set_json(
                                            cache_key,
                                            {'price': price, 'sticker_name': sticker_name},
                                            ex=StickerPricesAPI.CACHE_TTL
                                        )
                                        logger.info(f"💾 StickerPricesAPI: Сохранена цена в кэш (item_page) для '{sticker_name}': ${price:.2f}")
                                    except Exception as e:
                                        logger.debug(f"⚠️ StickerPricesAPI: Ошибка при сохранении в кэш: {e}")
                                
                                logger.info(f"✅ StickerPricesAPI: Найдена цена через страницу товара для '{sticker_name}': ${price:.2f}")
                                return price
                            except ValueError as e:
                                logger.debug(f"⚠️ StickerPricesAPI: Ошибка парсинга цены '{price_str}': {e}")
                        else:
                            # Логируем содержимое элемента для отладки
                            logger.debug(f"⚠️ StickerPricesAPI: Не удалось найти цену. Содержимое элемента:")
                            logger.debug(f"   HTML: {str(price_element)[:200]}")
                            logger.debug(f"   Текст: '{price_element.get_text(strip=True)[:100]}'")
                    else:
                        logger.debug(f"🔍 StickerPricesAPI: Элемент с ценой не найден на странице для '{sticker_name}'")
                    
                    # Если не нашли цену, пробуем еще раз с другим вариантом названия
                    if attempt == 0 and not sticker_name.startswith("Sticker"):
                        # Пробуем без префикса "Sticker |"
                        continue
                    
                    return None
                    
            except httpx.TimeoutException:
                logger.debug(f"⚠️ StickerPricesAPI: Timeout при загрузке страницы для '{sticker_name}'")
                if attempt < max_retries - 1:
                    continue
                return None
            except Exception as e:
                logger.debug(f"⚠️ StickerPricesAPI: Ошибка при загрузке страницы для '{sticker_name}': {type(e).__name__}: {e}")
                if current_proxy_obj and proxy_manager:
                    await proxy_manager.mark_proxy_used(current_proxy_obj, success=False)
                if attempt < max_retries - 1:
                    continue
                return None
        
        return None
    
    @staticmethod
    async def _get_price_from_suggestions(
        sticker_name: str,
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        timeout: int = 10,
        redis_service=None,
        proxy_manager=None
    ) -> Optional[float]:
        """
        Получает цену через searchsuggestionsresults API (более точный метод).
        
        Returns:
            Цена наклейки в USD или None
        """
        current_proxy_obj = None
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Получаем прокси
                if proxy_manager and not proxy:
                    current_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=(attempt > 0))
                    proxy = current_proxy_obj.url if current_proxy_obj else None
                
                # Формируем запрос
                query = f"Sticker | {sticker_name}" if not sticker_name.startswith("Sticker") else sticker_name
                
                async with httpx.AsyncClient(proxy=proxy, timeout=timeout) as client:
                    params = {'q': query}
                    response = await client.get(StickerPricesAPI.STEAM_MARKET_SUGGESTIONS_URL, params=params)
                    
                    if response.status_code != 200:
                        logger.debug(f"⚠️ StickerPricesAPI: searchsuggestionsresults вернул статус {response.status_code}")
                        if proxy_manager and current_proxy_obj:
                            await proxy_manager.mark_proxy_used(current_proxy_obj, success=False)
                        await asyncio.sleep(0.2)
                        continue
                    
                    data = response.json()
                    
                    if not data.get('results'):
                        logger.debug(f"🔍 StickerPricesAPI: searchsuggestionsresults не вернул результатов для '{sticker_name}'")
                        await asyncio.sleep(0.2)
                        continue
                    
                    # Ищем точное совпадение
                    for result in data.get('results', []):
                        market_hash_name = result.get('market_hash_name', '')
                        # Проверяем точное совпадение (без учета регистра)
                        if market_hash_name.lower() == sticker_name.lower() or \
                           market_hash_name.lower() == f"sticker | {sticker_name.lower()}":
                            min_price = result.get('min_price', 0)
                            if min_price and min_price > 0:
                                price = min_price / 100.0  # min_price в центах
                                
                                # Помечаем прокси как успешный
                                if current_proxy_obj and proxy_manager:
                                    await proxy_manager.mark_proxy_used(current_proxy_obj, success=True)
                                
                                # Сохраняем в кэш
                                if redis_service and redis_service.is_connected():
                                    try:
                                        cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                                        await redis_service.set_json(
                                            cache_key,
                                            {'price': price, 'sticker_name': sticker_name},
                                            ex=StickerPricesAPI.CACHE_TTL
                                        )
                                        logger.info(f"💾 StickerPricesAPI: Сохранена цена в кэш (searchsuggestionsresults) для '{sticker_name}': ${price:.2f}")
                                    except Exception as e:
                                        logger.debug(f"⚠️ StickerPricesAPI: Ошибка при сохранении в кэш: {e}")
                                
                                logger.info(f"✅ StickerPricesAPI: Найдена цена через searchsuggestionsresults для '{sticker_name}': ${price:.2f}")
                                return price
                    
                    # Если точного совпадения нет, пробуем найти похожее
                    logger.debug(f"🔍 StickerPricesAPI: Точное совпадение не найдено для '{sticker_name}', пробуем похожие...")
                    await asyncio.sleep(0.2)
                    
            except Exception as e:
                logger.debug(f"⚠️ StickerPricesAPI: Ошибка при запросе searchsuggestionsresults для '{sticker_name}': {e}")
                if proxy_manager and current_proxy_obj:
                    await proxy_manager.mark_proxy_used(current_proxy_obj, success=False)
                await asyncio.sleep(0.2)
        
        return None

    @staticmethod
    async def get_stickers_prices_batch(
        sticker_names: List[str],
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        delay: float = 0.5,
        redis_service=None,
        proxy_manager=None
    ) -> Dict[str, Optional[float]]:
        """
        Получает цены для нескольких наклеек с задержкой между запросами.
        Использует кэширование для одинаковых наклеек.

        Args:
            sticker_names: Список названий наклеек
            appid: ID приложения
            currency: Валюта
            proxy: Опциональный прокси
            delay: Задержка между запросами в секундах
            redis_service: Сервис Redis для кэширования (опционально)

        Returns:
            Словарь {название_наклейки: цена}
        """
        results = {}
        # Убираем дубликаты, чтобы не делать лишние запросы
        unique_stickers = list(dict.fromkeys(sticker_names))  # Сохраняет порядок
        
        logger.info(f"📋 StickerPricesAPI: Запрос цен для {len(unique_stickers)} уникальных наклеек (из {len(sticker_names)} всего, дубликаты исключены)")
        
        # Сначала проверяем кэш для всех наклеек
        cached_prices = {}
        if redis_service and redis_service.is_connected():
            for sticker_name in unique_stickers:
                try:
                    cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                    cached_data = await redis_service.get_json(cache_key)
                    if cached_data is not None and 'price' in cached_data:
                        cached_prices[sticker_name] = cached_data['price']
                except Exception:
                    pass
        
        if cached_prices:
            logger.info(f"📦 StickerPricesAPI: Найдено {len(cached_prices)} цен в кэше из {len(unique_stickers)} наклеек")
        
        # Запрашиваем цены для наклеек, которых нет в кэше
        failed_stickers = []
        for sticker_name in unique_stickers:
            # Если цена уже в кэше, используем её
            if sticker_name in cached_prices:
                results[sticker_name] = cached_prices[sticker_name]
                logger.debug(f"📦 StickerPricesAPI: Использована цена из кэша для '{sticker_name}': ${cached_prices[sticker_name]:.2f}")
                continue
            
            # Запрашиваем цену через API
            price = await StickerPricesAPI.get_sticker_price(
                sticker_name, appid, currency, proxy, timeout=10, redis_service=redis_service, proxy_manager=proxy_manager
            )
            results[sticker_name] = price
            
            if price is None:
                failed_stickers.append(sticker_name)
            
            # Задержка между запросами, чтобы не получить бан
            if delay > 0:
                await asyncio.sleep(delay)
        
        # Если есть неудачные запросы, выводим информацию
        if failed_stickers:
            # Проверяем, есть ли доступные прокси
            all_proxies_blocked = False
            if proxy_manager:
                try:
                    active_proxies = await proxy_manager.get_active_proxies()
                    if not active_proxies or len(active_proxies) == 0:
                        all_proxies_blocked = True
                except Exception:
                    pass
            
            if all_proxies_blocked:
                logger.warning(f"⚠️ StickerPricesAPI: Все прокси заблокированы, не удалось получить цены для {len(failed_stickers)} наклеек:")
                for sticker_name in failed_stickers:
                    logger.warning(f"   ❌ {sticker_name}: цена не найдена (прокси заблокированы)")
                
                # Выводим цены для известных наклеек (из кэша)
                known_prices = {name: price for name, price in results.items() if price is not None}
                if known_prices:
                    logger.info(f"✅ StickerPricesAPI: Цены для известных наклеек (из кэша):")
                    for sticker_name, price in known_prices.items():
                        logger.info(f"   💰 {sticker_name}: ${price:.2f}")
            else:
                logger.warning(f"⚠️ StickerPricesAPI: Не удалось получить цены для {len(failed_stickers)} наклеек:")
                for sticker_name in failed_stickers:
                    logger.warning(f"   ❌ {sticker_name}: цена не найдена")
                    logger.warning(f"      💡 Возможные причины:")
                    logger.warning(f"         - Наклейка не существует в Steam Market")
                    logger.warning(f"         - Неправильное название наклейки")
                    logger.warning(f"         - Наклейка слишком редкая или не продается")
                    logger.warning(f"      💡 Рекомендуется проверить название наклейки вручную")
        
        # Заполняем результаты для всех наклеек (включая дубликаты)
        final_results = {}
        for sticker_name in sticker_names:
            final_results[sticker_name] = results.get(sticker_name)
        
        return final_results


async def test_sticker_prices():
    """Тестовая функция."""
    sticker_name = "MOUZ | Stockholm 2021"
    price = await StickerPricesAPI.get_sticker_price(sticker_name)
    print(f"Цена наклейки '{sticker_name}': ${price if price else 'не найдена'}")


if __name__ == "__main__":
    asyncio.run(test_sticker_prices())

