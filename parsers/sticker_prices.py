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

    STEAM_MARKET_SEARCH_URL = "https://steamcommunity.com/market/search/render/"
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
        
        # Если не получилось, используем старый метод search/render
        # Получаем прокси через proxy_manager, если он доступен
        current_proxy = proxy
        current_proxy_obj = None
        if proxy_manager and not current_proxy:
            current_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=False)
            if current_proxy_obj:
                current_proxy = current_proxy_obj.url
                logger.debug(f"🌐 StickerPricesAPI: Используем прокси ID={current_proxy_obj.id} из proxy_manager")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Если это не первая попытка, получаем новый прокси
                if attempt > 0 and proxy_manager:
                    current_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=True)
                    if current_proxy_obj:
                        current_proxy = current_proxy_obj.url
                        logger.debug(f"🔄 StickerPricesAPI: Попытка {attempt + 1}/{max_retries}, переключились на прокси ID={current_proxy_obj.id}")
                    await asyncio.sleep(1.0 * attempt)  # Задержка перед повторной попыткой
                
                async with httpx.AsyncClient(proxy=current_proxy, timeout=timeout) as client:
                    # Нормализуем название наклейки для лучшего поиска
                    normalized_name = sticker_name.strip()
                    
                    # Пробуем разные варианты запроса (расширенный список)
                    queries = []
                    
                    # Вариант 1: С префиксом "Sticker |"
                    queries.append(f"Sticker | {normalized_name}")
                    
                    # Вариант 2: Прямое название
                    queries.append(normalized_name)
                    
                    # Вариант 3: С суффиксом "Sticker"
                    queries.append(f"{normalized_name} Sticker")
                    
                    # Вариант 4: Если название содержит "|", пробуем без части после "|"
                    if "|" in normalized_name:
                        name_part = normalized_name.split("|")[0].strip()
                        if name_part:
                            queries.append(f"Sticker | {name_part}")
                            queries.append(name_part)
                    
                    # Вариант 5: Если название содержит "(", пробуем без части в скобках
                    if "(" in normalized_name:
                        name_without_brackets = re.sub(r'\s*\([^)]+\)\s*', '', normalized_name).strip()
                        if name_without_brackets and name_without_brackets != normalized_name:
                            queries.append(f"Sticker | {name_without_brackets}")
                            queries.append(name_without_brackets)
                    
                    # Вариант 6: Убираем лишние пробелы и пробуем
                    name_cleaned = " ".join(normalized_name.split())
                    if name_cleaned != normalized_name:
                        queries.append(f"Sticker | {name_cleaned}")
                        queries.append(name_cleaned)
                    
                    # Убираем дубликаты, сохраняя порядок
                    seen = set()
                    unique_queries = []
                    for q in queries:
                        if q not in seen:
                            seen.add(q)
                            unique_queries.append(q)
                    queries = unique_queries
                    
                    logger.debug(f"🔍 StickerPricesAPI: Пробуем {len(queries)} вариантов запроса для '{sticker_name}': {queries[:3]}...")
                    
                    for query in queries:
                        params = {
                            "query": query,
                            "start": 0,
                            "count": 1,
                            "search_descriptions": 0,
                            "sort_column": "price",
                            "sort_dir": "asc",
                            "appid": appid,
                            "currency": currency,
                            "norender": 1
                        }

                        # Детальное логирование запроса
                        logger.info(f"🌐 StickerPricesAPI: Отправляем запрос для '{sticker_name}':")
                        logger.info(f"   📍 URL: {StickerPricesAPI.STEAM_MARKET_SEARCH_URL}")
                        logger.info(f"   🔍 Query: '{query}'")
                        logger.info(f"   📊 Параметры: {params}")
                        
                        response = await client.get(
                            StickerPricesAPI.STEAM_MARKET_SEARCH_URL,
                            params=params,
                            headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            }
                        )
                        
                        logger.info(f"   📥 Статус ответа: {response.status_code}")
                        
                        # Обрабатываем 429 ошибку с переключением прокси
                        if response.status_code == 429:
                            logger.warning(f"⚠️ StickerPricesAPI: 429 ошибка для наклейки '{sticker_name}' (попытка {attempt + 1}/{max_retries})")
                            if current_proxy_obj and proxy_manager:
                                # Помечаем прокси как заблокированный
                                await proxy_manager.mark_proxy_used(
                                    current_proxy_obj,
                                    success=False,
                                    error="429 Too Many Requests",
                                    is_429_error=True
                                )
                                logger.debug(f"🔄 StickerPricesAPI: Прокси ID={current_proxy_obj.id} помечен как заблокированный")
                            
                            # Пробуем следующий прокси
                            if attempt < max_retries - 1:
                                # Получаем новый прокси сразу, не ждем следующей итерации
                                if proxy_manager:
                                    new_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=True)
                                    if new_proxy_obj:
                                        current_proxy_obj = new_proxy_obj
                                        current_proxy = new_proxy_obj.url
                                        logger.info(f"🔄 StickerPricesAPI: Переключились на прокси ID={new_proxy_obj.id} после 429 ошибки")
                                    else:
                                        logger.warning(f"⚠️ StickerPricesAPI: Нет доступных прокси после 429 ошибки")
                                break  # Выходим из цикла queries и переходим к следующей попытке
                            else:
                                logger.error(f"❌ StickerPricesAPI: Превышено количество попыток для наклейки '{sticker_name}'")
                                return None
                        
                        response.raise_for_status()
                        data = response.json()
                        
                        # Детальное логирование ответа API
                        logger.info(f"📥 StickerPricesAPI: Ответ API для '{sticker_name}' (запрос: '{query}'):")
                        logger.info(f"   ✅ success: {data.get('success')}")
                        logger.info(f"   📊 total_count: {data.get('total_count', 0)}")
                        logger.info(f"   📋 results: {len(data.get('results', []))} результатов")
                        
                        # Если success=false или нет результатов
                        if not data.get("success"):
                            logger.warning(f"   ❌ API вернул success=false для '{sticker_name}'")
                            logger.warning(f"   📋 Полный ответ: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                            await asyncio.sleep(0.2)
                            continue
                        
                        if not data.get("results") or len(data["results"]) == 0:
                            logger.warning(f"   ❌ API вернул пустой список результатов для '{sticker_name}'")
                            logger.warning(f"   📋 Полный ответ: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
                            await asyncio.sleep(0.2)
                            continue
                        
                        if data.get("success") and data.get("results") and len(data["results"]) > 0:
                            # Логируем все найденные результаты
                            for idx, result in enumerate(data["results"][:3], 1):  # Показываем первые 3
                                result_name = result.get("asset_description", {}).get("market_hash_name", "") or result.get("name", "")
                                result_price = result.get("sell_price_text", "N/A")
                                logger.info(f"   📦 Результат {idx}: '{result_name}' - {result_price}")
                            
                            first_item = data["results"][0]
                            
                            # Проверяем, что это действительно наклейка
                            item_name = first_item.get("asset_description", {}).get("market_hash_name", "") or first_item.get("name", "")
                            
                            logger.info(f"   🔍 Проверяем первый результат: '{item_name}'")
                            logger.info(f"   🔍 Ищем наклейку: '{sticker_name}'")
                            
                            # Более гибкая проверка: наклейка должна содержать "Sticker" ИЛИ совпадать с запросом
                            is_sticker = "Sticker" in item_name or "sticker" in item_name.lower()
                            is_match = sticker_name.lower() in item_name.lower() or item_name.lower() in sticker_name.lower()
                            
                            logger.info(f"   ✅ is_sticker: {is_sticker} (содержит 'Sticker')")
                            logger.info(f"   ✅ is_match: {is_match} (совпадает с '{sticker_name}')")
                            
                            # Если это не наклейка и не совпадает с запросом, пробуем найти лучшее совпадение среди всех результатов
                            if not is_sticker and not is_match and query != sticker_name:
                                logger.info(f"   ⏭️ Первый результат '{item_name}' не подходит, ищем лучшее совпадение среди всех результатов...")
                                
                                # Ищем лучшее совпадение среди всех результатов
                                best_match = None
                                best_match_score = 0
                                
                                for idx, result in enumerate(data["results"]):
                                    result_name = result.get("asset_description", {}).get("market_hash_name", "") or result.get("name", "")
                                    result_is_sticker = "Sticker" in result_name or "sticker" in result_name.lower()
                                    
                                    # Вычисляем схожесть названий
                                    from core.utils.sticker_name_matcher import calculate_similarity
                                    similarity = calculate_similarity(sticker_name, result_name)
                                    
                                    logger.info(f"      Результат {idx+1}: '{result_name}' - is_sticker={result_is_sticker}, similarity={similarity:.2%}")
                                    
                                    # Если это наклейка и схожесть высокая, это может быть наш результат
                                    if result_is_sticker and similarity > best_match_score:
                                        best_match = result
                                        best_match_score = similarity
                                
                                # Если нашли хорошее совпадение (схожесть > 0.7), используем его
                                if best_match and best_match_score >= 0.7:
                                    first_item = best_match
                                    item_name = best_match.get("asset_description", {}).get("market_hash_name", "") or best_match.get("name", "")
                                    logger.info(f"   ✅ Найдено лучшее совпадение: '{item_name}' (схожесть {best_match_score:.2%})")
                                    is_sticker = True
                                    is_match = True
                                else:
                                    # Проверяем, есть ли другие результаты, которые могут подойти
                                    if len(data["results"]) > 1:
                                        logger.info(f"   🔍 Проверяем другие результаты ({len(data['results']) - 1} осталось)...")
                                    
                                    continue  # Пробуем следующий вариант запроса
                            
                            logger.info(f"   ✅ Результат подходит, извлекаем цену...")
                            
                            # Пробуем разные поля для цены
                            price = None
                            
                            # Детальное логирование всех полей с ценой
                            logger.info(f"   💰 Поля с ценой в ответе:")
                            logger.info(f"      - sell_price: {first_item.get('sell_price')} (тип: {type(first_item.get('sell_price')).__name__})")
                            logger.info(f"      - sell_price_text: {first_item.get('sell_price_text')}")
                            logger.info(f"      - price: {first_item.get('price')} (тип: {type(first_item.get('price')).__name__})")
                            logger.info(f"      - sale_price_text: {first_item.get('sale_price_text')}")
                            
                            # Вариант 1: price в центах (число)
                            if isinstance(first_item.get("sell_price"), (int, float)):
                                price = first_item.get("sell_price") / 100.0
                                logger.info(f"   ✅ Цена извлечена из sell_price (в центах): {first_item.get('sell_price')} -> ${price:.2f}")
                            # Вариант 2: price_text (строка)
                            elif first_item.get("sell_price_text"):
                                price_text = first_item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
                                try:
                                    price = float(price_text)
                                    logger.info(f"   ✅ Цена извлечена из sell_price_text: '{price_text}' -> ${price:.2f}")
                                except ValueError as e:
                                    logger.warning(f"   ❌ Ошибка парсинга sell_price_text '{price_text}': {e}")
                            # Вариант 3: price (число в центах)
                            elif isinstance(first_item.get("price"), (int, float)):
                                price = first_item.get("price") / 100.0
                                logger.info(f"   ✅ Цена извлечена из price (в центах): {first_item.get('price')} -> ${price:.2f}")
                            else:
                                logger.warning(f"   ❌ Не удалось извлечь цену из ответа. Доступные поля: {list(first_item.keys())}")
                            
                            if price is not None and price > 0:
                                # Помечаем прокси как успешный
                                if current_proxy_obj and proxy_manager:
                                    await proxy_manager.mark_proxy_used(
                                        current_proxy_obj,
                                        success=True
                                    )
                                
                                # Сохраняем в кэш Redis
                                if redis_service and redis_service.is_connected():
                                    try:
                                        cache_key = f"sticker_price:{sticker_name}:{appid}:{currency}"
                                        await redis_service.set_json(
                                            cache_key,
                                            {'price': price, 'sticker_name': sticker_name},
                                            ex=StickerPricesAPI.CACHE_TTL
                                        )
                                        logger.info(f"💾 StickerPricesAPI: Сохранена цена в кэш для '{sticker_name}': ${price:.2f} (TTL: {StickerPricesAPI.CACHE_TTL}с)")
                                    except Exception as e:
                                        logger.debug(f"⚠️ StickerPricesAPI: Ошибка при сохранении в кэш: {e}")
                                
                                logger.info(f"✅ StickerPricesAPI: Найдена цена для '{sticker_name}': ${price:.2f} (запрос: '{query}')")
                                return price
                            else:
                                # Если цена найдена, но равна 0 или отрицательна - это подозрительно
                                logger.warning(f"⚠️ StickerPricesAPI: Найден предмет '{item_name}', но цена некорректна: {price}")
                                logger.warning(f"   📋 Все поля первого результата: {json.dumps(first_item, indent=2, ensure_ascii=False)[:500]}")
                        
                        # Если не нашли с этим запросом, пробуем следующий
                        await asyncio.sleep(0.2)  # Небольшая задержка между попытками
                    
                    # Если все варианты запросов испробованы, но цена не найдена
                    logger.warning(f"❌ StickerPricesAPI: Все варианты запросов испробованы для '{sticker_name}', цена не найдена")
                    logger.warning(f"   📋 Испробованные запросы: {queries}")
                
                # Если дошли сюда, значит все запросы выполнены успешно, но цена не найдена
                if current_proxy_obj and proxy_manager:
                    await proxy_manager.mark_proxy_used(
                        current_proxy_obj,
                        success=True
                    )
                break  # Выходим из цикла retry, так как запросы успешны, но цена не найдена

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning(f"⚠️ StickerPricesAPI: 429 ошибка для наклейки '{sticker_name}' (попытка {attempt + 1}/{max_retries})")
                    if current_proxy_obj and proxy_manager:
                        # Помечаем прокси как заблокированный
                        await proxy_manager.mark_proxy_used(
                            current_proxy_obj,
                            success=False,
                            error="429 Too Many Requests",
                            is_429_error=True
                        )
                    # Пробуем следующий прокси
                    if attempt < max_retries - 1:
                        continue
                    else:
                        logger.error(f"❌ StickerPricesAPI: Превышено количество попыток для наклейки '{sticker_name}'")
                        return None
                else:
                    logger.debug(f"⚠️ StickerPricesAPI: HTTP {e.response.status_code} для наклейки '{sticker_name}'")
                    if attempt < max_retries - 1:
                        continue
                    return None
            except httpx.TimeoutException as e:
                logger.debug(f"⚠️ StickerPricesAPI: Timeout для наклейки '{sticker_name}': {e}")
                if attempt < max_retries - 1:
                    continue
                return None
            except Exception as e:
                logger.debug(f"⚠️ StickerPricesAPI: Ошибка для наклейки '{sticker_name}': {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    continue
                return None

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
                
                # URL-кодируем название для использования в URL
                encoded_hash_name = quote(sticker_name, safe='')
                
                # Формируем URL API
                params = {
                    'appid': appid,
                    'currency': currency,
                    'market_hash_name': sticker_name
                }
                
                logger.debug(f"🌐 StickerPricesAPI: Запрашиваем priceoverview для '{sticker_name}'")
                
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
                                    
                                    # Если нет lowest_price, пробуем price (но это цена конкретного листинга, не самая низкая)
                                    # Используем только если нет lowest_price
                                    if not price_str:
                                        price_value = value.get('price')
                                        if price_value:
                                            # Цена обычно в центах
                                            if isinstance(price_value, (int, float)):
                                                price_in_dollars = price_value / 100
                                                price_str = str(price_in_dollars)
                                                logger.debug(f"✅ StickerPricesAPI: Найдена цена в g_rgListingInfo[{key}].price: {price_value} центов = ${price_str}")
                                                # НЕ break здесь, продолжаем искать lowest_price в других элементах
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

