"""
Модуль для парсинга предметов с торговой площадки Steam Market.
"""
import asyncio
import json
import random
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
from loguru import logger

import httpx

from .models import SearchFilters, ParsedItemData
from .steam_parser_constants import _get_base_price_manager, _get_config
from .steam_http_client import SteamHttpClient
from .steam_filter_matcher import SteamFilterMatcher
from .steam_api_methods import SteamAPIMethods
from .steam_helper_methods import SteamHelperMethods
from .logger import get_task_logger
from services.filter_service import FilterService
from parsers import ItemPageParser
from parsers.inspect_parser import InspectLinkParser
from parsers.item_prices import ItemPricesAPI
from parsers.item_type_detector import detect_item_type


class SteamMarketParser(SteamAPIMethods, SteamHelperMethods):
    """Парсер для работы с Steam Market API."""

    BASE_URL = "https://steamcommunity.com/market/search/render/"
    SEARCH_SUGGESTIONS_URL = "https://steamcommunity.com/market/searchsuggestionsresults"
    LISTINGS_URL = "https://steamcommunity.com/market/listings/{appid}/{hash_name}/render/"
    ITEM_DETAILS_URL = "https://steamcommunity.com/market/listings/{appid}/{hash_name}"

    def __init__(self, proxy: Optional[str] = None, timeout: int = 30, redis_service=None, proxy_manager=None):
        """
        Инициализация парсера.

        Args:
            proxy: Прокси-сервер в формате "http://user:pass@host:port" или None
            timeout: Таймаут запроса в секундах
            redis_service: Сервис Redis для кэширования данных парсинга (опционально)
            proxy_manager: Менеджер прокси для ротации при параллельном парсинге (опционально)
        """
        self.proxy = proxy
        self.timeout = timeout
        self.redis_service = redis_service
        self.proxy_manager = proxy_manager
        # Используем HTTP клиент из отдельного модуля
        self._http_client = SteamHttpClient(proxy=proxy, timeout=timeout, proxy_manager=proxy_manager)
        # Ленивая инициализация для избежания циклических импортов
        self._base_price_manager = None
        # Текущий User-Agent (выбирается случайно при создании клиента)
        self._current_user_agent: Optional[str] = None
        # HTTP клиент (используем напрямую, не через _http_client пока)
        self._client: Optional[httpx.AsyncClient] = None
        # Инициализация сервиса фильтрации
        self._filter_service = None
        # Ленивая инициализация модулей парсинга
        self._listing_parser = None
        self._page_parser = None
    
    @property
    def base_price_manager(self):
        """Ленивая инициализация BasePriceManager."""
        if self._base_price_manager is None:
            BasePriceManager = _get_base_price_manager()
            self._base_price_manager = BasePriceManager()
        return self._base_price_manager
    
    @property
    def filter_service(self) -> FilterService:
        """Ленивая инициализация FilterService."""
        if self._filter_service is None:
            self._filter_service = FilterService(
                base_price_manager=self.base_price_manager,
                proxy_manager=self.proxy_manager,
                parser=self  # Передаем сам парсер для получения цен наклеек
            )
        return self._filter_service
    
    @property
    def listing_parser(self):
        """Ленивая инициализация ListingParser."""
        if self._listing_parser is None:
            from .steam_market_parser.listing_parser import ListingParser
            self._listing_parser = ListingParser(self)
        return self._listing_parser
    
    @property
    def page_parser(self):
        """Ленивая инициализация PageParser."""
        if self._page_parser is None:
            from .steam_market_parser.page_parser import PageParser
            self._page_parser = PageParser(self, self.listing_parser)
        return self._page_parser

    async def __aenter__(self):
        """Асинхронный контекстный менеджер - вход."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер - выход."""
        await self.close()
    
    async def close(self):
        """Закрывает HTTP клиент."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def search_items(
        self,
        filters: SearchFilters,
        start: int = 0,
        count: int = 20,
        parse_all_pages: bool = True,
        task = None,
        db_session = None,
        redis_service = None
    ) -> Dict[str, Any]:
        """
        Поиск предметов на Steam Market.
        Использует пул URL'ов: все страницы query запроса + прямая страница предмета.

        Args:
            filters: Параметры поиска
            start: Начальная позиция результатов (не используется, т.к. используем пул)
            count: Количество результатов (не используется, т.к. используем пул)
            parse_all_pages: Если True, парсит все страницы до получения всех предметов

        Returns:
            Словарь с результатами поиска
        """
        await self._ensure_client()
        
        # Получаем логгер для задачи (если task_id установлен в контексте)
        task_logger = get_task_logger()

        try:
            # ВАЖНО: Сначала получаем точный market_hash_name через searchsuggestionsresults
            # Это гарантирует, что мы получим точное название предмета, а не похожие
            logger.info(f"🔍 Получаем точный market_hash_name для '{filters.item_name}' через searchsuggestionsresults...")
            variants = await self.get_item_variants(filters.item_name)
            
            # Ищем точное совпадение по названию (с учетом качества, если указано)
            exact_hash_name = None
            if variants:
                # Нормализуем название задачи для сравнения
                task_name_normalized = filters.item_name.lower().strip()
                
                logger.info(f"🔍 Ищем точное совпадение для '{filters.item_name}' среди {len(variants)} вариантов...")
                
                for variant in variants:
                    variant_name = variant.get('market_hash_name', '')
                    variant_name_normalized = variant_name.lower().strip()
                    
                    logger.debug(f"   Сравниваем: '{task_name_normalized}' == '{variant_name_normalized}'")
                    
                    # Проверяем точное совпадение
                    if variant_name_normalized == task_name_normalized:
                        exact_hash_name = variant_name
                        logger.info(f"✅ Найден точный market_hash_name: '{exact_hash_name}'")
                        break
                
                # Если точного совпадения нет, используем filters.item_name напрямую (он уже точный)
                if not exact_hash_name:
                    # ВАЖНО: Если задача создана с точным hash_name (например, "StatTrak™ AK-47 | Redline (Minimal Wear)"),
                    # то filters.item_name уже содержит точное название, используем его
                    exact_hash_name = filters.item_name
                    logger.info(f"✅ Используем filters.item_name как exact_hash_name: '{exact_hash_name}'")
            
            # ВАЖНО: Используем ТОЛЬКО прямую страницу предмета (как в браузере)
            # Query API не используется - достаточно парсить только листинг конкретного предмета
            if not exact_hash_name:
                logger.error(f"❌ Не удалось определить exact_hash_name для '{filters.item_name}'")
                return {
                    "success": False,
                    "error": f"Не удалось определить точное название предмета для '{filters.item_name}'",
                    "total_count": 0,
                    "filtered_count": 0,
                    "items": []
                }
            
            logger.info(f"🔍 Формируем пул URL'ов для задачи '{filters.item_name}' (только direct страница)...")
            url_pool = await self.page_parser.build_url_pool(filters, exact_hash_name)
            
            data = None
            items = []
            total_count = 0
            
            if url_pool:
                # Обрабатываем все URL'ы из пула (только direct страницы)
                logger.info(f"🔄 Обрабатываем пул из {len(url_pool)} URL'ов (только direct страницы)...")
                data = await self.page_parser.process_url_pool(url_pool, filters, task=task, db_session=db_session, redis_service=redis_service)
                
                if data and data.get("success"):
                    items = data.get("results", [])
                    total_count = data.get("total_count", 0)
                    logger.info(f"✅ Пул обработан: получено {len(items)} уникальных предметов из {total_count} всего")
                    # ВАЖНО: Даже если items пустой (0 подходящих лотов), это успешный результат парсинга
                    # Парсинг завершился, просто не нашлось подходящих лотов
                else:
                    logger.warning(f"⚠️ Пул не дал результатов (success={data.get('success') if data else None}, results={len(data.get('results', [])) if data else 0})")
                    # Не используем fallback на Query API - он не нужен, т.к. мы уже знаем exact_hash_name
                    # Если пул не дал результатов, значит либо нет лотов, либо все прокси заблокированы
                    return {
                        "success": False,
                        "error": "Не удалось получить данные через direct API. Возможно, все прокси заблокированы или лотов нет.",
                        "total_count": 0,
                        "filtered_count": 0,
                        "items": []
                    }
            
            # ВАЖНО: Если пул был обработан успешно, но items пустой (0 подходящих лотов) - это нормально
            # Не переходим к fallback на Query API, возвращаем успешный результат с пустым items
            pool_processed_successfully = url_pool is not None and len(url_pool) > 0 and data and data.get("success")
            
            # Если пул был обработан успешно, но items пустой - это нормально (0 подходящих лотов)
            # Возвращаем успешный результат сразу, не переходя к fallback на Query API
            if pool_processed_successfully and not items:
                logger.info(f"✅ Пул обработан успешно, но подходящих лотов не найдено (0 из {total_count})")
                return {
                    "success": True,
                    "total_count": total_count,
                    "filtered_count": 0,
                    "items": []
                }
            
            # Если пул пуст или не дал результатов - возвращаем ошибку
            if not items:
                params = {
                    "query": filters.item_name,
                    "start": start,
                    "count": min(count, 100),
                    "search_descriptions": 0,
                    "sort_column": "price",
                    "sort_dir": "asc",
                    "appid": filters.appid,
                    "currency": filters.currency,
                    "norender": 1,
                    "language": "english"  # Используем английский язык для получения английских названий
                }

                # Формируем полный URL для логирования
                full_url = f"{self.BASE_URL}?{urlencode(params)}"
                logger.info(f"🔍 API запрос для '{filters.item_name}': query='{params['query']}', appid={params['appid']}")
                logger.info(f"🌐 Полный URL запроса: {full_url}")
                
                # Динамическая задержка перед API запросом в зависимости от количества прокси
                # При большем количестве прокси задержка меньше (нагрузка распределяется)
                # Но все равно должна быть разумной, чтобы не получить 429
                active_proxies_count = 0
                if self.proxy_manager:
                    active_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
                    active_proxies_count = len(active_proxies)
                elif self.proxy:
                    active_proxies_count = 1
                
                if active_proxies_count == 0:
                    # Нет прокси - стандартная задержка
                    await self._random_delay(min_seconds=2.0, max_seconds=4.0)
                elif active_proxies_count == 1:
                    # Один прокси - большая задержка для избежания 429
                    await self._random_delay(min_seconds=5.0, max_seconds=8.0)
                else:
                    # Несколько прокси - задержка уменьшается пропорционально количеству прокси
                    # Но минимум 2 сек, чтобы не получить 429
                    min_delay = max(8.0 / active_proxies_count, 2.0)
                    max_delay = max(12.0 / active_proxies_count, 3.0)
                    await self._random_delay(min_seconds=min_delay, max_seconds=max_delay)
                    logger.debug(f"    ⏳ Задержка перед API запросом: {min_delay:.1f}-{max_delay:.1f} сек (прокси: {active_proxies_count})")
                
                # Максимальное количество попыток для одного прокси
                max_retries_per_proxy = 3
                retry_delay = 5  # Начальная задержка в секундах
                max_proxy_switches = 10  # Максимальное количество переключений прокси при 429
                
                proxy_switches = 0
                attempt = 0  # Счетчик попыток для текущего прокси
                data = None  # Инициализируем data перед циклом
                
                # Используем while цикл вместо for, чтобы можно было сбрасывать счетчик попыток при переключении прокси
                while True:
                    try:
                        # Обновляем заголовки перед каждым запросом (ротация User-Agent и всех заголовков)
                        # Это помогает обойти блокировки, так как каждый запрос выглядит как с нового устройства
                        headers = self._get_browser_headers()
                        self._client.headers.update(headers)
                        if attempt > 0:
                            logger.info(f"🔄 Попытка {attempt + 1}/{max_retries_per_proxy}: Обновлены заголовки (User-Agent и др.) для '{filters.item_name}'")
                        else:
                            logger.debug(f"📋 Используем реалистичные заголовки для обхода блокировок")
                        
                        proxy_info = f" (через прокси: {self.proxy[:50]}...)" if self.proxy else " (прямое подключение)"
                        # Логируем полный URL запроса
                        request_url = f"{self.BASE_URL}?{urlencode(params)}"
                        logger.info(f"📡 Попытка {attempt + 1}/{max_retries_per_proxy}: Отправка запроса к Steam API для '{filters.item_name}'{proxy_info}")
                        logger.info(f"🌐 URL запроса: {request_url}")
                        response = await self._client.get(self.BASE_URL, params=params)
                        
                        logger.debug(f"📥 Попытка {attempt + 1}/{max_retries_per_proxy}: Получен ответ от Steam API: status_code={response.status_code}{proxy_info}")
                        
                        # Обработка 429 Too Many Requests - сразу блокируем прокси и переключаемся
                        if response.status_code == 429:
                            # Получаем текущий прокси и блокируем его
                            current_proxy = await self._get_current_proxy()
                            await self._handle_429_fast(current_proxy, f"'{filters.item_name}'")
                            
                            # Переключаемся на другой прокси и сбрасываем счетчик попыток
                            if proxy_switches < max_proxy_switches:
                                proxy_switches += 1
                                logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за 429, продолжаем с новым прокси")
                                # Сбрасываем счетчик попыток для нового прокси
                                attempt = 0
                                continue
                            else:
                                logger.error(f"❌ Превышено количество переключений прокси ({max_proxy_switches}) для '{filters.item_name}'")
                                return {
                                    "success": False,
                                    "error": "Too Many Requests (429). Все прокси заблокированы Steam.",
                                    "items": []
                                }
                        
                        response.raise_for_status()
                        try:
                            data = response.json()
                            break  # Успешный запрос, выходим из цикла
                        except (json.JSONDecodeError, ValueError) as json_error:
                            logger.error(f"❌ Ошибка парсинга JSON для '{filters.item_name}' на попытке {attempt + 1}/{max_retries_per_proxy}: {json_error}")
                            attempt += 1
                            if attempt < max_retries_per_proxy:
                                await asyncio.sleep(retry_delay * attempt)
                                continue
                            else:
                                # Превышено количество попыток для текущего прокси - переключаемся на другой
                                if proxy_switches < max_proxy_switches:
                                    proxy_switches += 1
                                    logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за ошибки парсинга JSON, продолжаем с новым прокси")
                                    attempt = 0
                                    continue
                                else:
                                    # Последняя попытка - возвращаем ошибку
                                    return {
                                        "success": False,
                                        "error": f"Ошибка парсинга JSON: {str(json_error)}",
                                        "total_count": 0,
                                        "filtered_count": 0,
                                        "items": []
                                    }
                    
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:
                            # Получаем текущий прокси и блокируем его
                            current_proxy = await self._get_current_proxy()
                            await self._handle_429_fast(current_proxy, f"'{filters.item_name}' (HTTPStatusError)")
                            
                            # Переключаемся на другой прокси и сбрасываем счетчик попыток
                            if proxy_switches < max_proxy_switches:
                                proxy_switches += 1
                                logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за 429, продолжаем с новым прокси")
                                # Сбрасываем счетчик попыток для нового прокси
                                attempt = 0
                                continue
                            else:
                                logger.error(f"❌ Превышено количество переключений прокси ({max_proxy_switches}) для '{filters.item_name}'")
                                return {
                                    "success": False,
                                    "error": "Too Many Requests (429). Все прокси заблокированы Steam.",
                                    "items": []
                                }
                        else:
                            # Другие HTTP ошибки
                            logger.error(f"❌ HTTP ошибка {e.response.status_code} для '{filters.item_name}': {e}")
                            attempt += 1
                            if attempt < max_retries_per_proxy:
                                await asyncio.sleep(retry_delay * attempt)
                                continue
                            else:
                                # Превышено количество попыток для текущего прокси - переключаемся на другой
                                if proxy_switches < max_proxy_switches:
                                    proxy_switches += 1
                                    logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за HTTP ошибки, продолжаем с новым прокси")
                                    attempt = 0
                                    continue
                                else:
                                    raise
                    except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as network_error:
                        logger.error(f"❌ Сетевая ошибка для '{filters.item_name}' на попытке {attempt + 1}/{max_retries_per_proxy}: {network_error}")
                        attempt += 1
                        if attempt < max_retries_per_proxy:
                            await asyncio.sleep(retry_delay * attempt)
                            continue
                        else:
                            # Превышено количество попыток для текущего прокси - переключаемся на другой
                            if proxy_switches < max_proxy_switches:
                                proxy_switches += 1
                                logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за сетевой ошибки, продолжаем с новым прокси")
                                attempt = 0
                                continue
                            else:
                                return {
                                    "success": False,
                                    "error": f"Сетевая ошибка: {str(network_error)}",
                                    "total_count": 0,
                                    "filtered_count": 0,
                                    "items": []
                                }
                    except Exception as e:
                        logger.error(f"❌ Неожиданная ошибка для '{filters.item_name}' на попытке {attempt + 1}/{max_retries_per_proxy}: {e}", exc_info=True)
                        attempt += 1
                        if attempt < max_retries_per_proxy:
                            await asyncio.sleep(retry_delay * attempt)
                            continue
                        else:
                            # Превышено количество попыток для текущего прокси - переключаемся на другой
                            if proxy_switches < max_proxy_switches:
                                proxy_switches += 1
                                logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за неожиданной ошибки, продолжаем с новым прокси")
                                attempt = 0
                                continue
                            else:
                                return {
                                    "success": False,
                                    "error": f"Unexpected error: {str(e)}",
                                    "total_count": 0,
                                    "filtered_count": 0,
                                    "items": []
                                }

            # Проверяем, что data была успешно получена
            if data is None:
                logger.error(f"❌ Не удалось получить данные для '{filters.item_name}'")
                return {
                    "success": False,
                    "error": f"Не удалось получить данные",
                    "total_count": 0,
                    "filtered_count": 0,
                    "items": []
                }

            logger.info(f"📥 API ответ: success={data.get('success')}, total_count={data.get('total_count', 0)}, results={len(data.get('results', []))}")

            if not data.get("success"):
                error_msg = data.get("error", "Unknown error")
                logger.warning(f"⚠️ API вернул ошибку: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "items": []
                }

            items = data.get("results", [])
            total_count = data.get("total_count", 0)
            
            # Получаем логгер для задачи (если task_id установлен в контексте)
            task_logger = get_task_logger()
            max_per_request = 100
            total_pages = (total_count + max_per_request - 1) // max_per_request if total_count > 0 else 1
            
            logger.info(f"📊 API нашел {total_count} предметов, получено {len(items)} в ответе")
            logger.info(f"🔍 Параметры парсинга: parse_all_pages={parse_all_pages}, total_count={total_count}, items_count={len(items)}")
            
            # Логируем информацию о страницах в лог задачи
            if task_logger.task_id:
                if total_count > 0:
                    task_logger.info(f"📊 API нашел {total_count} предметов, всего страниц: {total_pages}")
                    if total_count <= max_per_request:
                        task_logger.info(f"📄 Проверяем страницу 1 из {total_pages} (все предметы на одной странице)")
                    else:
                        task_logger.info(f"📄 Проверяем страницу 1 из {total_pages}, будет запрошено еще {total_pages - 1} страниц")
                else:
                    task_logger.info(f"📊 API не нашел предметов")
            
            # ВАЖНО: Если пул был обработан, все страницы уже получены, пропускаем пагинацию
            pool_processed = url_pool is not None and len(url_pool) > 0
            
            # Парсим все страницы, если предметов больше, чем получено в первом запросе
            # Steam API возвращает максимум 100 предметов за запрос, нужно делать несколько запросов
            # Если parse_all_pages=False, парсим только первую страницу
            # НО: если пул был обработан, все страницы уже получены, пропускаем пагинацию
            if not pool_processed and parse_all_pages and total_count > len(items):
                current_page = 1  # Первая страница уже получена
                
                logger.info(f"📄 Найдено {total_count} предметов, но получено только {len(items)}. Парсим все страницы...")
                logger.info(f"📄 Будет запрошено примерно {(total_count - len(items) + 99) // 100} дополнительных страниц")
                if task_logger.task_id:
                    task_logger.info(f"📄 Всего страниц: {total_pages}, проверено: {current_page} из {total_pages}")
                
                current_start = len(items)
                
                # Определяем параметры для пагинации
                max_retries = 3
                retry_delay = 5
                
                # ВАЖНО: Если есть proxy_manager и несколько прокси, используем параллельный парсинг страниц
                # Задержки применяются для каждого прокси отдельно через get_next_proxy
                if self.proxy_manager and active_proxies_count > 1:
                    logger.debug(f"🔄 Параллельный парсинг страниц: используем {active_proxies_count} прокси")
                    if task_logger.task_id:
                        task_logger.info(f"🔄 Параллельный парсинг страниц: используем {active_proxies_count} прокси")
                    # Параллельный парсинг страниц с распределением между прокси
                    await self.page_parser.parse_all_pages_parallel(
                        filters, params, items, total_count, current_start, max_per_request, 
                        active_proxies_count, max_retries, retry_delay, task_logger, total_pages
                    )
                else:
                    # Последовательный парсинг страниц (для одного прокси или без прокси)
                    logger.debug(f"📄 Последовательный парсинг страниц (прокси: {active_proxies_count})")
                    while current_start < total_count:
                        # Задержка между запросами страниц с одного прокси
                        if active_proxies_count == 0:
                            await self._random_delay(min_seconds=3.0, max_seconds=5.0)
                        elif active_proxies_count == 1:
                            await self._random_delay(min_seconds=4.0, max_seconds=6.0)
                        elif active_proxies_count <= 5:
                            min_delay = max(4.0 / active_proxies_count, 2.0)
                            max_delay = max(6.0 / active_proxies_count, 3.0)
                            await self._random_delay(min_seconds=min_delay, max_seconds=max_delay)
                            logger.debug(f"   ⏳ Задержка между страницами: {min_delay:.1f}-{max_delay:.1f} сек (прокси: {active_proxies_count})")
                        else:
                            min_delay = max(3.0 / active_proxies_count, 1.0)
                            max_delay = max(5.0 / active_proxies_count, 2.0)
                            await self._random_delay(min_seconds=min_delay, max_seconds=max_delay)
                            logger.debug(f"   ⏳ Задержка между страницами: {min_delay:.1f}-{max_delay:.1f} сек (прокси: {active_proxies_count}, нагрузка распределена)")
                        
                        # Вычисляем сколько еще нужно получить
                        remaining = total_count - current_start
                        request_count = min(max_per_request, remaining)
                        current_page = (current_start // max_per_request) + 1
                        
                        logger.info(f"📄 Запрашиваем страницу: start={current_start}, count={request_count} (осталось {remaining} предметов)")
                        if task_logger.task_id:
                            task_logger.info(f"📄 Проверяем страницу {current_page} из {total_pages}")
                        
                        # Обновляем параметры для следующего запроса
                        params["start"] = current_start
                        params["count"] = request_count
                        
                        # Делаем запрос для следующей страницы
                        page_success = False
                        data_page = None
                        for page_attempt in range(max_retries):
                            try:
                                # Обновляем заголовки перед запросом
                                headers = self._get_browser_headers()
                                self._client.headers.update(headers)
                                
                                proxy_info = f" (через прокси: {self.proxy[:50]}...)" if self.proxy else " (прямое подключение)"
                                logger.debug(f"📡 Страница {current_start // max_per_request + 2}: Запрос к Steam API{proxy_info}")
                                response_page = await self._client.get(self.BASE_URL, params=params)
                                
                                logger.info(f"📥 Страница {current_start // max_per_request + 2}: Получен ответ: status_code={response_page.status_code}")
                                
                                # Обработка 429
                                if response_page.status_code == 429:
                                    should_retry = await self._handle_429_error(
                                        response=response_page,
                                        attempt=page_attempt,
                                        max_retries=max_retries,
                                        base_delay=retry_delay,
                                        context=f"страница {current_start // max_per_request + 2} для '{filters.item_name}'"
                                    )
                                    if should_retry:
                                        continue
                                    else:
                                        logger.warning(f"⚠️ Не удалось получить страницу {current_start // max_per_request + 2} после {max_retries} попыток. Продолжаем с уже полученными данными.")
                                        break
                                
                                response_page.raise_for_status()
                                data_page = response_page.json()
                                
                                if data_page.get("success"):
                                    page_items = data_page.get("results", [])
                                    if page_items:
                                        items.extend(page_items)
                                        current_page = (current_start // max_per_request) + 1
                                        logger.info(f"✅ Страница {current_page}: Получено {len(page_items)} предметов (всего: {len(items)}/{total_count})")
                                        if task_logger.task_id:
                                            task_logger.info(f"✅ Страница {current_page} из {total_pages}: Получено {len(page_items)} предметов (всего: {len(items)}/{total_count})")
                                        current_start += len(page_items)
                                        page_success = True
                                        break
                                    else:
                                        logger.warning(f"⚠️ Страница {current_start // max_per_request + 2}: Пустой ответ, прекращаем парсинг")
                                        break
                                else:
                                    logger.warning(f"⚠️ Страница {current_start // max_per_request + 2}: API вернул ошибку: {data_page.get('error', 'Unknown')}")
                                    break
                                    
                            except httpx.HTTPStatusError as e:
                                if e.response.status_code == 429:
                                    should_retry = await self._handle_429_error(
                                        response=e.response,
                                        attempt=page_attempt,
                                        max_retries=max_retries,
                                        base_delay=retry_delay,
                                        context=f"страница {current_start // max_per_request + 2} для '{filters.item_name}' (HTTPStatusError)"
                                    )
                                    if should_retry:
                                        continue
                                    else:
                                        logger.warning(f"⚠️ Не удалось получить страницу {current_start // max_per_request + 2} после {max_retries} попыток.")
                                        break
                                else:
                                    logger.error(f"❌ HTTP ошибка {e.response.status_code} при запросе страницы {current_start // max_per_request + 2}: {e}")
                                    break
                            except Exception as e:
                                logger.error(f"❌ Ошибка при запросе страницы {current_start // max_per_request + 2}: {e}")
                                break
                        
                        # Если не удалось получить страницу, прекращаем парсинг
                        if not page_success:
                            logger.warning(f"⚠️ Прекращаем парсинг страниц. Получено {len(items)} из {total_count} предметов.")
                            break
                        
                        # Если получили меньше предметов, чем запрашивали, значит это последняя страница
                        if data_page and len(data_page.get("results", [])) < request_count:
                            logger.info(f"✅ Получена последняя страница. Всего получено {len(items)} предметов.")
                            break
                    
                    logger.info(f"📊 Парсинг всех страниц завершен: получено {len(items)} из {total_count} предметов")
                    if task_logger.task_id:
                        task_logger.info(f"✅ Парсинг всех страниц завершен: получено {len(items)} из {total_count} предметов (проверено {total_pages} из {total_pages} страниц)")
            
            # Если ничего не найдено, пробуем поиск с включенным search_descriptions
            if total_count == 0 and len(items) == 0:
                logger.info(f"🔄 Пробуем поиск с search_descriptions=1 для '{filters.item_name}'")
                params["search_descriptions"] = 1
                
                # Случайная задержка перед вторым запросом
                await self._random_delay(min_seconds=1.0, max_seconds=2.5)
                
                # Определяем параметры для повторных попыток
                max_retries = 3
                retry_delay = 5
                
                # Обработка 429 для второго запроса
                for attempt2 in range(max_retries):
                    try:
                        # Обновляем заголовки перед запросом
                        if attempt2 > 0:
                            headers = self._get_browser_headers()
                            self._client.headers.update(headers)
                            logger.info(f"🔄 Попытка {attempt2 + 1}/{max_retries} (search_descriptions): Обновлен User-Agent")
                        
                        logger.info(f"📡 Попытка {attempt2 + 1}/{max_retries} (search_descriptions): Отправка запроса с search_descriptions=1")
                        response2 = await self._client.get(self.BASE_URL, params=params)
                        logger.info(f"📥 Попытка {attempt2 + 1}/{max_retries} (search_descriptions): Получен ответ: status_code={response2.status_code}")
                        
                        if response2.status_code == 429:
                            should_retry = await self._handle_429_error(
                                response=response2,
                                attempt=attempt2,
                                max_retries=max_retries,
                                base_delay=retry_delay,
                                context=f"поиск с search_descriptions для '{filters.item_name}'"
                            )
                            if should_retry:
                                # Обновляем заголовки перед повторной попыткой
                                headers = self._get_browser_headers()
                                self._client.headers.update(headers)
                                continue
                            else:
                                logger.error(f"❌ Превышено количество попыток ({max_retries}) для search_descriptions")
                                logger.error(f"   Steam блокирует запросы даже с search_descriptions=1")
                                logger.error(f"   Рекомендации:")
                                logger.error(f"   1. Добавьте прокси через команду /add_proxy")
                                logger.error(f"   2. Увеличьте задержки между запросами")
                                break
                        
                        response2.raise_for_status()
                        data2 = response2.json()
                        logger.info(f"📥 API ответ (search_descriptions=1): success={data2.get('success')}, total_count={data2.get('total_count', 0)}")
                        if data2.get("success") and data2.get("total_count", 0) > 0:
                            logger.info(f"✅ С search_descriptions=1 найдено {data2.get('total_count', 0)} предметов")
                            items = data2.get("results", [])
                            total_count = data2.get("total_count", 0)
                            
                            # Парсим все страницы для search_descriptions=1 тоже
                            if total_count > len(items):
                                logger.info(f"📄 (search_descriptions=1) Найдено {total_count} предметов, но получено только {len(items)}. Парсим все страницы...")
                                
                                max_per_request = 100
                                current_start = len(items)
                                
                                # ВАЖНО: Если есть proxy_manager и несколько прокси, используем параллельный парсинг страниц
                                if self.proxy_manager and active_proxies_count > 1:
                                    logger.debug(f"🔄 (search_descriptions=1) Параллельный парсинг страниц: используем {active_proxies_count} прокси")
                                    # Параллельный парсинг страниц с распределением между прокси
                                    await self.page_parser.parse_all_pages_parallel(
                                        filters, params, items, total_count, current_start, max_per_request, 
                                        active_proxies_count, max_retries, retry_delay
                                    )
                                else:
                                    # Последовательный парсинг страниц (для одного прокси или без прокси)
                                    logger.debug(f"📄 (search_descriptions=1) Последовательный парсинг страниц (прокси: {active_proxies_count})")
                                    
                                    while current_start < total_count:
                                        # Задержка между запросами страниц с одного прокси
                                        # Если прокси много, задержки могут быть меньше, так как нагрузка распределяется между прокси
                                        if active_proxies_count == 0:
                                            await self._random_delay(min_seconds=3.0, max_seconds=5.0)
                                        elif active_proxies_count == 1:
                                            await self._random_delay(min_seconds=4.0, max_seconds=6.0)
                                        elif active_proxies_count <= 5:
                                            # Несколько прокси - средняя задержка
                                            min_delay = max(4.0 / active_proxies_count, 2.0)
                                            max_delay = max(6.0 / active_proxies_count, 3.0)
                                            await self._random_delay(min_seconds=min_delay, max_seconds=max_delay)
                                            logger.debug(f"   ⏳ (search_descriptions=1) Задержка между страницами: {min_delay:.1f}-{max_delay:.1f} сек (прокси: {active_proxies_count})")
                                        else:
                                            # Много прокси (10+) - задержка все равно нужна, но меньше
                                            # ВАЖНО: Даже при большом количестве прокси нужна задержка между запросами с одного прокси
                                            min_delay = max(3.0 / active_proxies_count, 1.0)
                                            max_delay = max(5.0 / active_proxies_count, 2.0)
                                            await self._random_delay(min_seconds=min_delay, max_seconds=max_delay)
                                            logger.debug(f"   ⏳ (search_descriptions=1) Задержка между страницами: {min_delay:.1f}-{max_delay:.1f} сек (прокси: {active_proxies_count}, нагрузка распределена)")
                                        
                                        remaining = total_count - current_start
                                        request_count = min(max_per_request, remaining)
                                        
                                        logger.info(f"📄 (search_descriptions=1) Запрашиваем страницу: start={current_start}, count={request_count} (осталось {remaining} предметов)")
                                        
                                        params["start"] = current_start
                                        params["count"] = request_count
                                        
                                        # Определяем параметры для повторных попыток
                                        max_retries = 3
                                        retry_delay = 5
                                        
                                        page_success_sd = False
                                        data_page_sd = None
                                        for page_attempt_sd in range(max_retries):
                                            try:
                                                headers = self._get_browser_headers()
                                                self._client.headers.update(headers)
                                                
                                                proxy_info = f" (через прокси: {self.proxy[:50]}...)" if self.proxy else " (прямое подключение)"
                                                logger.debug(f"📡 (search_descriptions=1) Страница {current_start // max_per_request + 2}: Запрос к Steam API{proxy_info}")
                                                response_page_sd = await self._client.get(self.BASE_URL, params=params)
                                                
                                                logger.info(f"📥 (search_descriptions=1) Страница {current_start // max_per_request + 2}: Получен ответ: status_code={response_page_sd.status_code}")
                                                
                                                if response_page_sd.status_code == 429:
                                                    should_retry = await self._handle_429_error(
                                                        response=response_page_sd,
                                                        attempt=page_attempt_sd,
                                                        max_retries=max_retries,
                                                        base_delay=retry_delay,
                                                        context=f"(search_descriptions=1) страница {current_start // max_per_request + 2} для '{filters.item_name}'"
                                                    )
                                                    if should_retry:
                                                        continue
                                                    else:
                                                        logger.warning(f"⚠️ Не удалось получить страницу {current_start // max_per_request + 2} после {max_retries} попыток.")
                                                        break
                                                
                                                response_page_sd.raise_for_status()
                                                data_page_sd = response_page_sd.json()
                                                
                                                if data_page_sd.get("success"):
                                                    page_items_sd = data_page_sd.get("results", [])
                                                    if page_items_sd:
                                                        items.extend(page_items_sd)
                                                        logger.info(f"✅ (search_descriptions=1) Страница {current_start // max_per_request + 2}: Получено {len(page_items_sd)} предметов (всего: {len(items)}/{total_count})")
                                                        current_start += len(page_items_sd)
                                                        page_success_sd = True
                                                        break
                                                    else:
                                                        logger.warning(f"⚠️ (search_descriptions=1) Страница {current_start // max_per_request + 2}: Пустой ответ")
                                                        break
                                                else:
                                                    logger.warning(f"⚠️ (search_descriptions=1) Страница {current_start // max_per_request + 2}: API вернул ошибку")
                                                    break
                                                    
                                            except httpx.HTTPStatusError as e:
                                                if e.response.status_code == 429:
                                                    should_retry = await self._handle_429_error(
                                                        response=e.response,
                                                        attempt=page_attempt_sd,
                                                        max_retries=max_retries,
                                                        base_delay=retry_delay,
                                                        context=f"(search_descriptions=1) страница {current_start // max_per_request + 2} для '{filters.item_name}'"
                                                    )
                                                    if should_retry:
                                                        continue
                                                    else:
                                                        break
                                                else:
                                                    logger.error(f"❌ HTTP ошибка при запросе страницы {current_start // max_per_request + 2}: {e}")
                                                    break
                                            except Exception as e:
                                                logger.error(f"❌ Ошибка при запросе страницы {current_start // max_per_request + 2}: {e}")
                                                break
                                        
                                        if not page_success_sd:
                                            logger.warning(f"⚠️ Прекращаем парсинг страниц (search_descriptions=1). Получено {len(items)} из {total_count} предметов.")
                                            break
                                        
                                        if data_page_sd and len(data_page_sd.get("results", [])) < request_count:
                                            logger.info(f"✅ (search_descriptions=1) Получена последняя страница. Всего получено {len(items)} предметов.")
                                            break
                                    
                                    logger.info(f"📊 (search_descriptions=1) Парсинг всех страниц завершен: получено {len(items)} из {total_count} предметов")
                        else:
                            # Если и с search_descriptions ничего не найдено
                            logger.warning(f"⚠️ Предмет '{filters.item_name}' не найден. Возможно, нужно использовать английское название.")
                            logger.warning(f"💡 Подсказка: Steam Market API требует точное совпадение названия. Попробуйте использовать английское название предмета.")
                        break
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:
                            should_retry = await self._handle_429_error(
                                response=e.response,
                                attempt=attempt2,
                                max_retries=max_retries,
                                base_delay=retry_delay,
                                context=f"поиск с search_descriptions для '{filters.item_name}' (HTTPStatusError)"
                            )
                            if should_retry:
                                # Обновляем заголовки перед повторной попыткой
                                headers = self._get_browser_headers()
                                self._client.headers.update(headers)
                                continue
                            else:
                                logger.error(f"❌ Превышено количество попыток ({max_retries}) для search_descriptions")
                                break
                        else:
                            logger.error(f"❌ HTTP ошибка {e.response.status_code} при поиске с search_descriptions: {e}")
                            raise

            # Фильтрация результатов по заданным критериям
            # ВСЕГДА парсим страницы предметов, чтобы получить float, pattern и наклейки
            # (даже если фильтры не заданы, данные нужны для уведомлений)
            needs_detailed_parsing = (
                filters.float_range is not None or
                filters.pattern_range is not None or
                filters.pattern_list is not None or
                filters.stickers_filter is not None
            )
            
            # ВСЕГДА парсим для получения данных (даже без фильтров)
            always_parse = True

            filtered_items = []
            logger.info(f"📦 Начинаем обработку {len(items)} предметов из API")
            
            # Получаем логгер для задачи (если task_id установлен в контексте)
            task_logger = get_task_logger()
            
            # Логируем информацию о первой странице в лог задачи
            try:
                if task_logger and task_logger.task_id:
                    task_logger.info(f"📦 Начинаем обработку {len(items)} предметов из API (страница 1 из {total_pages})")
            except Exception:
                pass  # Игнорируем ошибки с task_logger
            
            # Определяем количество активных прокси для расчета задержек и параллельности
            active_proxies_count = 0
            if self.proxy_manager:
                active_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
                active_proxies_count = len(active_proxies)
            elif self.proxy:
                active_proxies_count = 1  # Есть один прокси, но не через proxy_manager
            
            # Проверяем настройку параллельного парсинга
            Config = _get_config()
            use_parallel = Config.PARALLEL_PARSING
            
            # Автоматически включаем параллельный парсинг, если есть 2+ прокси
            # Чем больше прокси, тем быстрее парсинг (нагрузка распределяется)
            if not use_parallel and active_proxies_count >= 2:
                use_parallel = True
                logger.debug(f"🔄 Автоматически включен параллельный парсинг (найдено {active_proxies_count} прокси)")
            
            if use_parallel:
                # Параллельный парсинг с ограничением по количеству прокси
                max_concurrent = 1  # По умолчанию последовательно
                if self.proxy_manager:
                    active_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
                    max_concurrent = max(len(active_proxies), 1)  # Минимум 1, максимум = количество прокси
                    logger.debug(f"🔄 Параллельный парсинг: максимум {max_concurrent} одновременных запросов (по количеству прокси)")
                else:
                    logger.debug(f"🔄 Параллельный парсинг: 1 одновременный запрос (прокси не используются)")
                
                # Создаем семафор для ограничения параллельных запросов
                semaphore = asyncio.Semaphore(max_concurrent)
                
                async def process_item(item: Dict[str, Any], idx: int) -> list[Dict[str, Any]]:
                    """Обрабатывает один предмет с использованием отдельного прокси."""
                    async with semaphore:
                        # Получаем task_logger в начале функции
                        item_task_logger = get_task_logger()
                        
                        item_name = item.get('name', item.get('asset_description', {}).get('market_hash_name', 'Unknown'))
                        logger.info(f"  [{idx + 1}/{len(items)}] Обрабатываем: {item_name}")
                        # Логируем прогресс в лог задачи
                        try:
                            if item_task_logger and item_task_logger.task_id:
                                item_task_logger.info(f"📦 Обрабатываем предмет {idx + 1} из {len(items)}: {item_name}")
                        except Exception:
                            pass  # Игнорируем ошибки с task_logger
                        
                        # ВАЖНО: Проверяем точное совпадение названия предмета с задачей
                        # Это предотвращает парсинг других вариантов (например, других износов)
                        task_item_name = filters.item_name.strip()
                        item_name_normalized = item_name.strip()
                        if task_item_name.lower() != item_name_normalized.lower():
                            logger.info(f"    ⏭️ Пропускаем '{item_name}' - не соответствует задаче '{task_item_name}'")
                            return None
                        logger.info(f"    ✅ Название совпадает с задачей: '{item_name}'")
                        
                        # Предварительная проверка по цене (быстрая проверка без парсинга)
                        if not self.filter_service.check_price(item, filters):
                            logger.info(f"    ❌ Не прошел фильтр по цене")
                            return None
                        logger.info(f"    ✅ Прошел фильтр по цене")

                        # Получаем отдельный прокси для этого запроса (если есть proxy_manager)
                        item_proxy = None
                        item_proxy_url = None
                        if self.proxy_manager:
                            item_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False)
                            if item_proxy:
                                item_proxy_url = item_proxy.url
                                logger.debug(f"    🌐 Используем прокси ID={item_proxy.id} для предмета {idx + 1}")
                        
                        # Если нет отдельного прокси, используем основной
                        if not item_proxy_url:
                            item_proxy_url = self.proxy

                        # Проверяем, нужны ли детальные данные (float, pattern, stickers)
                        hash_name = item.get("asset_description", {}).get("market_hash_name")
                        listing_id = item.get("listingid")  # ID конкретного лота из API
                        
                        # Определяем, нужен ли парсинг страницы (только если есть фильтры по float/pattern/stickers)
                        needs_parsing = needs_detailed_parsing or always_parse
                        parsed_data = None
                        
                        # Определяем, есть ли фильтр по паттерну (нужно проверять все inspect ссылки)
                        # Детальное логирование фильтров для отладки
                        logger.info(f"    🔍 DEBUG (parallel): filters.pattern_list = {filters.pattern_list}")
                        logger.info(f"    🔍 DEBUG (parallel): filters.pattern_range = {filters.pattern_range}")
                        
                        has_pattern_filter = filters.pattern_list is not None or filters.pattern_range is not None
                        logger.info(f"    🔍 DEBUG (parallel): has_pattern_filter = {has_pattern_filter}")
                        
                        target_patterns = None
                        if filters.pattern_list:
                            target_patterns = set(filters.pattern_list.patterns)
                            logger.info(f"    🎯 Фильтр по паттерну (parallel): ищем паттерны {target_patterns}")
                            logger.info(f"    🔍 DEBUG (parallel): pattern_list.patterns = {filters.pattern_list.patterns}")
                            logger.info(f"    🔍 DEBUG (parallel): pattern_list.item_type = {filters.pattern_list.item_type}")
                        elif filters.pattern_range:
                            # Для pattern_range создаем set всех паттернов в диапазоне
                            target_patterns = set(range(filters.pattern_range.min, filters.pattern_range.max + 1))
                            logger.info(f"    🎯 Фильтр по паттерну (parallel): ищем паттерны в диапазоне {filters.pattern_range.min}-{filters.pattern_range.max}")
                            logger.info(f"    🔍 DEBUG (parallel): pattern_range.min = {filters.pattern_range.min}, max = {filters.pattern_range.max}")
                        else:
                            logger.info(f"    🔍 DEBUG (parallel): Нет фильтра по паттерну (pattern_list=None, pattern_range=None)")
                        
                        logger.info(f"    🔍 DEBUG (parallel): target_patterns = {target_patterns}")
                        
                        if hash_name and needs_parsing:
                            logger.info(f"    📄 [{idx + 1}/{len(items)}] Начинаем парсинг ВСЕХ лотов на странице предмета: {hash_name}")
                            
                            # Динамическая задержка перед запросом к странице предмета
                            # При параллельном парсинге задержка уменьшается с количеством прокси
                            # Чем больше прокси, тем меньше задержка (нагрузка распределяется)
                            # ИСПОЛЬЗУЕМ ФИКСИРОВАННЫЕ ЗНАЧЕНИЯ, не зависящие от ITEM_PAGE_DELAY
                            # УВЕЛИЧЕНЫ ЗАДЕРЖКИ для избежания 429 ошибок
                            if active_proxies_count == 0:
                                # Нет прокси - большая задержка для избежания 429
                                base_delay = 10.0  # Увеличено до 10 сек
                            elif active_proxies_count == 1:
                                # Один прокси - увеличенная задержка для избежания 429
                                base_delay = 10.0  # Увеличено до 10 сек
                            elif active_proxies_count == 2:
                                # Два прокси - увеличенная задержка
                                base_delay = 5.0  # Увеличено до 5 сек
                            elif active_proxies_count >= 3:
                                # Три и более прокси - задержка уменьшается, но минимум 3 сек
                                base_delay = max(5.0 / active_proxies_count, 3.0)  # При 3 прокси: ~1.67 -> 3 сек, при 4: 1.25 -> 3 сек
                            else:
                                # Fallback
                                base_delay = 5.0
                            
                            # Прогрессивная задержка: немного увеличивается с индексом предмета
                            # Но только при малом количестве прокси
                            if active_proxies_count <= 1:
                                progressive_delay = base_delay + (idx * 0.3)
                            else:
                                progressive_delay = base_delay + (idx * 0.1)
                            
                            random_part = random.uniform(0.2, 0.8)  # Случайная часть (меньше для параллельного парсинга)
                            delay = progressive_delay + random_part
                            logger.debug(f"    ⏳ Задержка {delay:.1f} сек перед парсингом (прокси: {active_proxies_count}, базовая: {base_delay:.1f}с, прогрессивная: {progressive_delay:.1f}с)")
                            await asyncio.sleep(delay)
                            
                            # Создаем отдельный парсер для этого предмета с отдельным прокси
                            item_parser = self.__class__(proxy=item_proxy_url, timeout=30, redis_service=self.redis_service, proxy_manager=self.proxy_manager)
                            await item_parser._ensure_client()
                            
                            try:
                                logger.info(f"    🔍 Парсим ВСЕ лоты на странице предмета: {hash_name}")
                                # Парсим ВСЕ лоты на странице и проверяем каждый по цене и паттерну
                                # Используем уже полученный task_logger
                                all_parsed_listings = await item_parser.listing_parser.parse_all_listings(
                                    filters.appid,
                                    hash_name,
                                    filters,
                                    target_patterns=target_patterns,
                                    task_logger=item_task_logger,
                                    task=task,
                                    db_session=db_session,
                                    redis_service=redis_service
                                )
                                
                                if all_parsed_listings:
                                    logger.info(f"    ✅ Найдено {len(all_parsed_listings)} подходящих лотов из всех на странице")
                                    # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: проверяем, есть ли паттерн 896 в списке
                                    patterns_in_listings = [ld.pattern for ld in all_parsed_listings if ld.pattern is not None]
                                    logger.info(f"    📊 Паттерны в all_parsed_listings: {patterns_in_listings[:20]}... (всего: {len(patterns_in_listings)})")
                                    patterns_896 = [ld for ld in all_parsed_listings if ld.pattern == 896]
                                    if patterns_896:
                                        logger.info(f"    🎯🎯🎯 НАЙДЕНО {len(patterns_896)} лотов с паттерном 896 в all_parsed_listings!")
                                        for ld in patterns_896:
                                            logger.info(f"       - listing_id={ld.listing_id}, pattern={ld.pattern}, price=${ld.item_price:.2f}")
                                    
                                    # Возвращаем список всех подходящих лотов
                                    # Каждый лот будет обработан отдельно
                                    results = []
                                    for listing_data in all_parsed_listings:
                                        # Проверяем все фильтры для каждого лота
                                        item_name_display = item.get('name', hash_name or 'Unknown')
                                        
                                        # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для паттерна 896
                                        if listing_data.pattern == 896:
                                            logger.info(f"    🎯🎯🎯 ПРОВЕРКА ФИЛЬТРОВ для паттерна 896:")
                                            logger.info(f"       listing_data.pattern={listing_data.pattern} (тип: {type(listing_data.pattern).__name__})")
                                            logger.info(f"       filters.pattern_list={filters.pattern_list}")
                                            if filters.pattern_list:
                                                logger.info(f"       filters.pattern_list.patterns={filters.pattern_list.patterns} (типы: {[type(p).__name__ for p in filters.pattern_list.patterns]})")
                                        
                                        # ВАЖНО: Логируем перед проверкой фильтров для всех предметов с нужными паттернами/float
                                        should_log = False
                                        log_reason = ""
                                        if listing_data.pattern == 142:
                                            should_log = True
                                            log_reason = "паттерн 142"
                                        if listing_data.float_value and 0.22 <= listing_data.float_value <= 0.26:
                                            should_log = True
                                            log_reason += f", float {listing_data.float_value:.6f}" if log_reason else f"float {listing_data.float_value:.6f}"
                                        
                                        if should_log:
                                            logger.info(f"    🎯🎯🎯 ПРОВЕРКА ФИЛЬТРОВ для предмета с {log_reason}:")
                                            logger.info(f"       listing_id: {listing_data.listing_id}")
                                            logger.info(f"       pattern: {listing_data.pattern} (тип: {type(listing_data.pattern).__name__})")
                                            logger.info(f"       float_value: {listing_data.float_value} (тип: {type(listing_data.float_value).__name__})")
                                            logger.info(f"       item_name: {listing_data.item_name}")
                                            logger.info(f"       item_price: {listing_data.item_price}")
                                        
                                        matches = await self.filter_service.matches_filters(item, filters, listing_data)
                                        
                                        # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ результата для паттерна 896
                                        if listing_data.pattern == 896:
                                            logger.info(f"    🎯🎯🎯 РЕЗУЛЬТАТ ПРОВЕРКИ ФИЛЬТРОВ для паттерна 896: matches={matches}")
                                        
                                        # ВАЖНО: Логируем результат для всех предметов с нужными паттернами/float
                                        if should_log:
                                            logger.info(f"    🎯🎯🎯 РЕЗУЛЬТАТ ПРОВЕРКИ ФИЛЬТРОВ для предмета с {log_reason}: matches={matches}")
                                        
                                        if matches:
                                            float_info = f", float={listing_data.float_value:.6f}" if listing_data.float_value is not None else ""
                                            logger.info(f"    ✅ Лот прошел все фильтры: паттерн={listing_data.pattern}, цена=${listing_data.item_price:.2f}{float_info}")
                                            
                                            # ВАЖНО: Если предмет прошел фильтры и есть наклейки, но цены еще не запрошены,
                                            # запрашиваем цены для отображения в уведомлении (ВСЕГДА, независимо от наличия фильтра)
                                            if listing_data.stickers and len(listing_data.stickers) > 0:
                                                logger.info(f"    ✅ НАЙДЕНЫ НАКЛЕЙКИ В listing_data: {len(listing_data.stickers)} штук")
                                                # Проверяем, есть ли цены на наклейках
                                                has_prices = any(s.price and s.price > 0 for s in listing_data.stickers if hasattr(s, 'price'))
                                                if not has_prices:
                                                    logger.info(f"    🏷️ Предмет прошел фильтры, запрашиваем цены на наклейки для уведомления...")
                                                    from parsers.sticker_prices import StickerPricesAPI
                                                    # Извлекаем названия наклеек: используем name, если есть, иначе wear
                                                    sticker_names = []
                                                    for s in listing_data.stickers:
                                                        sticker_name = s.name if s.name else (s.wear if s.wear else None)
                                                        if sticker_name:
                                                            sticker_names.append(sticker_name)
                                                    
                                                    logger.info(f"    🏷️ Извлечено {len(sticker_names)} названий наклеек: {sticker_names}")
                                                    
                                                    if sticker_names:
                                                        prices = await StickerPricesAPI.get_stickers_prices_batch(
                                                            sticker_names, proxy=self.proxy, delay=0.3, redis_service=self.redis_service, proxy_manager=self.proxy_manager
                                                        )
                                                        logger.info(f"    🏷️ Получено цен из API: {len(prices)} записей")
                                                        
                                                        # Обновляем цены наклеек
                                                        updated_count = 0
                                                        for sticker in listing_data.stickers:
                                                            sticker_name = sticker.name if sticker.name else (sticker.wear if sticker.wear else None)
                                                            if sticker_name and sticker_name in prices and prices[sticker_name] is not None:
                                                                sticker.price = prices[sticker_name]
                                                                updated_count += 1
                                                                logger.info(f"    💰 Наклейка '{sticker_name}': ${prices[sticker_name]:.2f}")
                                                        
                                                        listing_data.total_stickers_price = sum(s.price for s in listing_data.stickers if hasattr(s, 'price') and s.price and s.price > 0)
                                                        logger.info(f"    🏷️ Обновлены цены для {updated_count} из {len(listing_data.stickers)} наклеек, общая цена: ${listing_data.total_stickers_price:.2f}")
                                            
                                            item_result = item.copy()
                                            item_result["parsed_data"] = listing_data.model_dump()
                                            # Добавляем listingid в item_result для проверки дубликатов в parsing_worker
                                            if listing_data.listing_id:
                                                item_result["listingid"] = listing_data.listing_id
                                            results.append(item_result)
                                            logger.info(f"    📤 Добавлен item_result в results (всего: {len(results)})")
                                        else:
                                            # Логируем, почему лот не прошел фильтры
                                            float_info = f", float={listing_data.float_value:.6f}" if listing_data.float_value is not None else ", float=None"
                                            logger.debug(f"    ❌ Лот не прошел фильтры: паттерн={listing_data.pattern}, цена=${listing_data.item_price:.2f}{float_info}")
                                    
                                    logger.info(f"    📊 Итого добавлено {len(results)} результатов в results для предмета {hash_name}")
                                    
                                    # Отмечаем прокси как использованный
                                    if item_proxy and self.proxy_manager:
                                        is_success = len(results) > 0
                                        await self.proxy_manager.mark_proxy_used(
                                            item_proxy,
                                            success=is_success,
                                            error=None if is_success else "Не найдено подходящих лотов"
                                        )
                                    
                                    # Возвращаем все подходящие лоты
                                    # Каждый лот будет обработан отдельно и отправлено уведомление
                                    if results:
                                        if len(results) > 1:
                                            logger.info(f"    📊 Найдено {len(results)} подходящих лотов, обрабатываем все")
                                        return results  # Возвращаем все подходящие лоты
                                else:
                                    logger.error(f"    ⚠️ Не найдено подходящих лотов на странице: {hash_name}")
                            except Exception as e:
                                logger.error(f"    ❌ Ошибка при парсинге всех лотов на странице предмета '{hash_name}': {e}")
                                import traceback
                                logger.debug(f"Traceback: {traceback.format_exc()}")
                                return []
                            finally:
                                # ВАЖНО: Закрываем временный парсер для освобождения ресурсов
                                try:
                                    await item_parser.close()
                                except Exception as close_error:
                                    logger.warning(f"    ⚠️ Ошибка при закрытии временного парсера: {close_error}")
                                
                            # Отмечаем прокси как использованный (если был отдельный прокси)
                            if item_proxy and self.proxy_manager:
                                await self.proxy_manager.mark_proxy_used(
                                    item_proxy,
                                    success=False,
                                    error="Не найдено подходящих лотов"
                                )

                        # Если парсинг не нужен или не удался, проверяем фильтры без распарсенных данных
                        item_name_display = item.get('name', hash_name or 'Unknown')
                        logger.info(f"    🔎 Проверяем фильтры для: {item_name_display} (без парсинга)")
                        matches = await self.filter_service.matches_filters(item, filters, None)
                        if matches:
                            logger.info(f"    ✅ Предмет прошел все фильтры: {item_name_display}")
                            item_result = item.copy()
                            return [item_result]  # Возвращаем список с одним элементом
                        else:
                            logger.error(f"    ❌ Предмет не прошел фильтры: {item_name_display}")
                            return []
                
                # Запускаем параллельную обработку всех предметов
                tasks = [process_item(item, idx) for idx, item in enumerate(items)]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Собираем результаты (может быть список результатов для каждого предмета)
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"❌ Ошибка при обработке предмета: {result}")
                    elif result is not None:
                        # result может быть списком лотов или одним результатом
                        if isinstance(result, list):
                            # Добавляем все лоты из списка
                            for lot_result in result:
                                filtered_items.append(lot_result)
                        else:
                            # Один результат
                            filtered_items.append(result)
            else:
                # Последовательный парсинг (старая логика)
                logger.info(f"🔄 Последовательный парсинг (PARALLEL_PARSING=false)")
                for idx, item in enumerate(items):
                    item_name = item.get('name', item.get('asset_description', {}).get('market_hash_name', 'Unknown'))
                    
                    # ВАЖНО: Проверяем точное совпадение названия предмета с задачей
                    # Это предотвращает парсинг других вариантов (например, других износов)
                    task_item_name = filters.item_name.strip()
                    item_name_normalized = item_name.strip()
                    if task_item_name.lower() != item_name_normalized.lower():
                        logger.info(f"  [{idx + 1}/{len(items)}] Пропускаем: {item_name} - не соответствует задаче '{task_item_name}'")
                        continue
                    logger.info(f"  [{idx + 1}/{len(items)}] Обрабатываем: {item_name} - ✅ Название совпадает с задачей")
                    
                    # Предварительная проверка по цене (быстрая проверка без парсинга)
                    if not self.filter_service.check_price(item, filters):
                        logger.info(f"  [{idx + 1}/{len(items)}] Обрабатываем: {item_name} - ❌ Не прошел фильтр по цене")
                        continue
                    logger.info(f"  [{idx + 1}/{len(items)}] Обрабатываем: {item_name} - ✅ Прошел фильтр по цене")

                    # Проверяем, нужны ли детальные данные (float, pattern, stickers)
                    hash_name = item.get("asset_description", {}).get("market_hash_name")
                    listing_id = item.get("listingid")  # ID конкретного лота из API
                    
                    # Определяем, нужен ли парсинг страницы (только если есть фильтры по float/pattern/stickers)
                    needs_parsing = needs_detailed_parsing or always_parse
                    parsed_data = None
                    
                    # Определяем, есть ли фильтр по паттерну (нужно проверять все inspect ссылки)
                    # Детальное логирование фильтров для отладки
                    logger.info(f"    🔍 DEBUG: filters.pattern_list = {filters.pattern_list}")
                    logger.info(f"    🔍 DEBUG: filters.pattern_range = {filters.pattern_range}")
                    
                    has_pattern_filter = filters.pattern_list is not None or filters.pattern_range is not None
                    logger.info(f"    🔍 DEBUG: has_pattern_filter = {has_pattern_filter}")
                    
                    target_patterns = None
                    if filters.pattern_list:
                        target_patterns = set(filters.pattern_list.patterns)
                        logger.info(f"    🎯 Фильтр по паттерну: ищем паттерны {target_patterns}")
                        logger.info(f"    🔍 DEBUG: pattern_list.patterns = {filters.pattern_list.patterns}")
                        logger.info(f"    🔍 DEBUG: pattern_list.item_type = {filters.pattern_list.item_type}")
                    elif filters.pattern_range:
                        # Для pattern_range создаем set всех паттернов в диапазоне
                        target_patterns = set(range(filters.pattern_range.min, filters.pattern_range.max + 1))
                        logger.info(f"    🎯 Фильтр по паттерну: ищем паттерны в диапазоне {filters.pattern_range.min}-{filters.pattern_range.max}")
                        logger.info(f"    🔍 DEBUG: pattern_range.min = {filters.pattern_range.min}, max = {filters.pattern_range.max}")
                    else:
                        logger.info(f"    🔍 DEBUG: Нет фильтра по паттерну (pattern_list=None, pattern_range=None)")
                    
                    logger.info(f"    🔍 DEBUG: target_patterns = {target_patterns}")
                    
                    if hash_name and needs_parsing:
                        logger.info(f"    📄 Начинаем парсинг страницы предмета: {hash_name}")
                        # Логируем прогресс в лог задачи (только один раз, без дублирования)
                        if task_logger.task_id:
                            task_logger.info(f"📦 Обрабатываем предмет {idx + 1} из {len(items)}: {hash_name}")
                        
                        # Динамическая задержка между запросами к страницам предметов для избежания 429
                        # Задержка зависит от количества прокси:
                        # - 0 прокси: большая задержка
                        # - 1 прокси: средняя задержка
                        # - 2+ прокси: задержка уменьшается пропорционально
                        if idx > 0:  # Не ждем перед первым запросом
                            # ИСПОЛЬЗУЕМ ФИКСИРОВАННЫЕ ЗНАЧЕНИЯ, не зависящие от ITEM_PAGE_DELAY
                            # УВЕЛИЧЕНЫ ЗАДЕРЖКИ для избежания 429 ошибок
                            if active_proxies_count == 0:
                                # Нет прокси - большая задержка
                                base_delay = 10.0  # Увеличено до 10 сек
                                progressive_delay = base_delay + (idx * 1.0)  # +1.0 сек за каждый предмет
                            elif active_proxies_count == 1:
                                # Один прокси - увеличенная задержка для избежания 429
                                base_delay = 10.0  # Увеличено до 10 сек
                                progressive_delay = base_delay + (idx * 1.0)  # +1.0 сек за каждый предмет
                            elif active_proxies_count == 2:
                                # Два прокси - увеличенная задержка
                                base_delay = 5.0  # Увеличено до 5 сек
                                progressive_delay = base_delay + (idx * 0.5)  # +0.5 сек за каждый предмет
                            elif active_proxies_count >= 3:
                                # Три и более прокси - задержка уменьшается, но минимум 3 сек
                                base_delay = max(5.0 / active_proxies_count, 3.0)  # При 3 прокси: ~1.67 -> 3 сек, при 4: 1.25 -> 3 сек
                                progressive_delay = base_delay + (idx * 0.3)  # +0.3 сек за каждый предмет
                            else:
                                # Fallback
                                base_delay = 5.0
                                progressive_delay = base_delay + (idx * 0.5)
                            
                            random_part = random.uniform(0.3, 0.8)  # Случайная часть
                            delay = progressive_delay + random_part
                            logger.debug(f"    ⏳ Задержка {delay:.1f} сек перед парсингом предмета {idx + 1}/{len(items)} (прокси: {active_proxies_count}, базовая: {base_delay:.1f}с)")
                            await asyncio.sleep(delay)
                        
                        # Обновляем заголовки перед каждым запросом к странице предмета
                        headers = self._get_browser_headers()
                        self._client.headers.update(headers)
                        
                        logger.info(f"    🔍 Парсим ВСЕ лоты на странице предмета: {hash_name}")
                        # Парсим ВСЕ лоты на странице и проверяем каждый по цене и паттерну
                        # Получаем task_logger для передачи в _parse_all_listings
                        task_logger = get_task_logger()
                        all_parsed_listings = await self.listing_parser.parse_all_listings(
                            filters.appid,
                            hash_name,
                            filters,
                            target_patterns=target_patterns,
                            task_logger=task_logger,
                            task=task,
                            db_session=db_session,
                            redis_service=redis_service
                        )
                        
                        if all_parsed_listings:
                            logger.info(f"    ✅ Найдено {len(all_parsed_listings)} подходящих лотов из всех на странице")
                            
                            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: проверяем паттерн 896
                            patterns_896_in_listings = [ld for ld in all_parsed_listings if ld.pattern == 896]
                            if patterns_896_in_listings:
                                logger.info(f"    🎯🎯🎯 НАЙДЕНО {len(patterns_896_in_listings)} лотов с паттерном 896 перед проверкой фильтров!")
                                for ld in patterns_896_in_listings:
                                    logger.info(f"       - listing_id={ld.listing_id}, pattern={ld.pattern}, price=${ld.item_price:.2f}")
                            
                            # Обрабатываем каждый подходящий лот
                            for listing_data in all_parsed_listings:
                                # Проверяем все фильтры для каждого лота
                                item_name_display = item.get('name', hash_name or 'Unknown')
                                
                                # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для паттерна 896
                                if listing_data.pattern == 896:
                                    logger.info(f"    🎯🎯🎯 ПРОВЕРКА ФИЛЬТРОВ для паттерна 896 (второй путь):")
                                    logger.info(f"       listing_data.pattern={listing_data.pattern} (тип: {type(listing_data.pattern).__name__})")
                                    logger.info(f"       filters.pattern_list={filters.pattern_list}")
                                    if filters.pattern_list:
                                        logger.info(f"       filters.pattern_list.patterns={filters.pattern_list.patterns} (типы: {[type(p).__name__ for p in filters.pattern_list.patterns]})")
                                
                                matches = await self.filter_service.matches_filters(item, filters, listing_data)
                                
                                # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ результата для паттерна 896
                                if listing_data.pattern == 896:
                                    logger.info(f"    🎯🎯🎯 РЕЗУЛЬТАТ ПРОВЕРКИ ФИЛЬТРОВ для паттерна 896 (второй путь): matches={matches}")
                                if matches:
                                    logger.info(f"    ✅ Лот прошел все фильтры: паттерн={listing_data.pattern}, цена=${listing_data.item_price:.2f}")
                                    
                                    # ВАЖНО: Если предмет прошел фильтры и есть наклейки, но цены еще не запрошены,
                                    # запрашиваем цены для отображения в уведомлении (ВСЕГДА, независимо от наличия фильтра)
                                    logger.info(f"    🔍 ПРОВЕРКА НАКЛЕЕК: listing_data.stickers={listing_data.stickers}, len={len(listing_data.stickers) if listing_data.stickers else 0}, type={type(listing_data.stickers)}")
                                    logger.info(f"    🔍 DEBUG: listing_data type={type(listing_data)}, hasattr stickers={hasattr(listing_data, 'stickers')}")
                                    if hasattr(listing_data, 'stickers'):
                                        logger.info(f"    🔍 DEBUG: listing_data.stickers value={listing_data.stickers}")
                                    if listing_data.stickers and len(listing_data.stickers) > 0:
                                        logger.info(f"    ✅ НАЙДЕНЫ НАКЛЕЙКИ В listing_data: {len(listing_data.stickers)} штук")
                                        # Проверяем, есть ли цены на наклейках
                                        has_prices = any(s.price and s.price > 0 for s in listing_data.stickers if hasattr(s, 'price'))
                                        # ВАЖНО: Запрашиваем цены на наклейки для уведомления ВСЕГДА, если:
                                        # 1. Предмет прошел все фильтры (matches == True) ✓
                                        # 2. Есть наклейки ✓ (уже проверено выше)
                                        # 3. Цены еще не запрошены (нет цен)
                                        if not has_prices:
                                            logger.info(f"    🏷️ Предмет прошел фильтры, запрашиваем цены на наклейки для уведомления...")
                                            from parsers.sticker_prices import StickerPricesAPI
                                            # Извлекаем названия наклеек: используем name, если есть, иначе wear
                                            sticker_names = []
                                            for s in listing_data.stickers:
                                                sticker_name = s.name if s.name else (s.wear if s.wear else None)
                                                if sticker_name:
                                                    sticker_names.append(sticker_name)
                                                else:
                                                    logger.warning(f"    ⚠️ Наклейка без названия: name={s.name}, wear={s.wear}, position={s.position}")
                                            
                                            logger.info(f"    🏷️ Извлечено {len(sticker_names)} названий наклеек: {sticker_names}")
                                            
                                            if sticker_names:
                                                prices = await StickerPricesAPI.get_stickers_prices_batch(
                                                    sticker_names, proxy=self.proxy, delay=0.3, redis_service=self.redis_service, proxy_manager=self.proxy_manager
                                                )
                                                logger.info(f"    🏷️ Получено цен из API: {len(prices)} записей, примеры: {dict(list(prices.items())[:3]) if prices else 'нет'}")
                                                
                                                # Обновляем цены наклеек
                                                updated_count = 0
                                                for sticker in listing_data.stickers:
                                                    sticker_name = sticker.name if sticker.name else (sticker.wear if sticker.wear else None)
                                                    if sticker_name and sticker_name in prices and prices[sticker_name] is not None:
                                                        sticker.price = prices[sticker_name]
                                                        updated_count += 1
                                                        logger.info(f"    💰 Наклейка '{sticker_name}': ${prices[sticker_name]:.2f}")
                                                    elif sticker_name:
                                                        logger.warning(f"    ⚠️ Цена не найдена для наклейки '{sticker_name}'")
                                                
                                                listing_data.total_stickers_price = sum(s.price for s in listing_data.stickers if hasattr(s, 'price') and s.price and s.price > 0)
                                                logger.info(f"    🏷️ Обновлены цены для {updated_count} из {len(listing_data.stickers)} наклеек, общая цена: ${listing_data.total_stickers_price:.2f}")
                                            else:
                                                logger.warning(f"    ⚠️ Не удалось извлечь названия наклеек для запроса цен")
                                    
                                    item_result = item.copy()
                                    item_result["parsed_data"] = listing_data.model_dump()
                                    # Добавляем listingid в item_result для проверки дубликатов в parsing_worker
                                    if listing_data.listing_id:
                                        item_result["listingid"] = listing_data.listing_id
                                    filtered_items.append(item_result)
                        else:
                            logger.warning(f"    ⚠️ Не найдено подходящих лотов на странице: {hash_name}")
                            # ВАЖНО: Если парсинг не удался, но фильтры не требуют парсинга (нет фильтров по паттерну/float/наклейкам),
                            # проверяем предмет без распарсенных данных
                            if not needs_detailed_parsing:
                                item_name_display = item.get('name', hash_name or 'Unknown')
                                logger.info(f"    🔎 Парсинг не удался, но фильтры не требуют детальных данных. Проверяем фильтры для: {item_name_display} (без парсинга)")
                                matches = await self.filter_service.matches_filters(item, filters, None)
                                if matches:
                                    logger.info(f"    ✅ Предмет прошел все фильтры: {item_name_display}")
                                    item_result = item.copy()
                                    item_result["parsed_data"] = {}  # Пустые данные, т.к. парсинг не удался
                                    filtered_items.append(item_result)
                                else:
                                    logger.error(f"    ❌ Предмет не прошел фильтры: {item_name_display}")

                    # Если парсинг не нужен, проверяем фильтры без распарсенных данных
                    if not needs_parsing:
                        item_name_display = item.get('name', hash_name or 'Unknown')
                        logger.info(f"    🔎 Проверяем фильтры для: {item_name_display} (без парсинга)")
                        matches = await self.filter_service.matches_filters(item, filters, None)
                        if matches:
                            logger.info(f"    ✅ Предмет прошел все фильтры: {item_name_display}")
                            item_result = item.copy()
                            item_result["parsed_data"] = {}  # Пустые данные, т.к. парсинг не нужен
                            filtered_items.append(item_result)
                        else:
                            logger.error(f"    ❌ Предмет не прошел фильтры: {item_name_display}")
            
            logger.info(f"📊 Итоги парсинга: всего={total_count}, после фильтрации={len(filtered_items)}")
            try:
                task_logger = get_task_logger()
                if task_logger and task_logger.task_id:
                    task_logger.info(f"📊 Итоги парсинга: всего={total_count}, после фильтрации={len(filtered_items)} (проверено {total_pages} страниц)")
            except Exception:
                pass  # Игнорируем ошибки с task_logger
            return {
                "success": True,
                "total_count": total_count,
                "filtered_count": len(filtered_items),
                "items": filtered_items
            }
        except httpx.HTTPStatusError as e:
            # Обработка 429 уже сделана выше, здесь обрабатываем другие HTTP ошибки
            if e.response.status_code == 429:
                return {
                    "success": False,
                    "error": "Too Many Requests (429). Steam временно блокирует запросы. Попробуйте позже или используйте прокси.",
                    "items": []
                }
            return {
                "success": False,
                "error": f"HTTP error {e.response.status_code}: {str(e)}",
                "items": []
            }
        except httpx.HTTPError as e:
            return {
                "success": False,
                "error": f"HTTP error: {str(e)}",
                "items": []
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"JSON decode error: {str(e)}",
                "items": []
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "items": []
            }

    async def get_stickers_prices(
        self,
        appid: int,
        hash_name: str,
        filters: SearchFilters,
        target_patterns: Optional[set] = None,
        task_logger = None
    ) -> list[ParsedItemData]:
        """
        Парсит ВСЕ лоты на ВСЕХ страницах предмета и возвращает список всех подходящих лотов.
        Каждый лот проверяется по цене и паттерну.
        Поддерживает пагинацию - парсит все страницы, если их несколько.

        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            filters: Фильтры для проверки лотов
            target_patterns: Опциональный set паттернов для фильтрации

        Returns:
            Список ParsedItemData для всех подходящих лотов
        """
        from parsers.inspect_parser import InspectLinkParser
        
        # Вспомогательная функция для логирования в оба логгера
        def log_both(level: str, message: str):
            """Логирует сообщение в обычный logger и task_logger."""
            try:
                # Логируем в основной logger
                if level == "info":
                    logger.info(message)
                elif level == "warning":
                    logger.warning(message)
                elif level == "error":
                    logger.error(message)
                elif level == "debug":
                    logger.debug(message)
                else:
                    logger.info(message)
                
                # Также логируем в task_logger, если он доступен
                if task_logger:
                    try:
                        if level == "info":
                            task_logger.info(message)
                        elif level == "warning":
                            task_logger.warning(message)
                        elif level == "error":
                            task_logger.error(message)
                        elif level == "debug":
                            task_logger.debug(message)
                    except Exception:
                        pass  # Игнорируем ошибки с task_logger
            except Exception:
                pass  # Игнорируем ошибки логирования
        
        log_both("info", f"    🚀 _parse_all_listings: hash_name={hash_name}, target_patterns={target_patterns}")
        
        matching_listings = []
        all_listings = []
        
        # Используем API /render/ для получения паттерна и float напрямую из JSON
        # Это быстрее, чем парсить HTML и делать дополнительные запросы к Inspect API
        log_both("info", f"    🚀 Используем API /render/ для быстрого получения паттерна и float из JSON")
        
        # ВАЖНО: Максимальное значение count для render endpoint = 20
        # Если count > 20, API не возвращает данные
        listings_per_page = 20
        # Увеличиваем лимит страниц для поиска редких паттернов
        # С count=20 для 1535 предметов нужно 77 страниц
        MAX_PAGES_TO_PARSE = 100  # С count=20 этого достаточно для большинства случаев
        start = 0
        page_num = 1
        total_count = None
        
        # Словарь для хранения данных из assets (listing_id -> {pattern, float, asset_id, contextid})
        assets_data_map = {}
        
        # Парсим страницы через API /render/
        while page_num <= MAX_PAGES_TO_PARSE:
            # Проверяем, активна ли задача (для немедленной остановки)
            if self._current_task:
                # Обновляем задачу из БД для проверки актуального статуса
                try:
                    from sqlalchemy import select
                    from core import MonitoringTask
                    if self._current_db_session:
                        result = await self._current_db_session.execute(
                            select(MonitoringTask).where(MonitoringTask.id == self._current_task.id)
                        )
                        db_task = result.scalar_one_or_none()
                        if db_task and not db_task.is_active:
                            log_both("info", f"🛑 Задача {self._current_task.id} деактивирована, останавливаем парсинг")
                            break
                except Exception as e:
                    log_both("warning", f"⚠️ Ошибка при проверке статуса задачи: {e}")
            
            # Логируем прогресс страниц в обычный logger и task_logger
            # ВАЖНО: Логируем всегда, даже если total_count еще не определен
            if total_count is not None:
                total_pages = (total_count + listings_per_page - 1) // listings_per_page
                log_both("info", f"📋 Страница {page_num} из {total_pages}: Обрабатываем лоты...")
            else:
                log_both("info", f"📋 Страница {page_num}: Обрабатываем лоты... (всего лотов пока неизвестно)")
            
            # ВАЖНО: Пробуем получить рабочий прокси, проверяя все доступные прокси по очереди
            # Не останавливаемся, пока не найдем рабочий прокси или не проверим все
            page_proxy = None
            render_data = None
            
            log_both("info", f"    🔍 Страница {page_num}: Начинаем поиск рабочего прокси...")
            
            if self.proxy_manager:
                # Получаем список всех доступных прокси
                available_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
                
                if not available_proxies:
                    log_both("warning", f"    ⚠️ Страница {page_num}: Нет доступных прокси, пробуем обновить список")
                    available_proxies = await self.proxy_manager.get_active_proxies(force_refresh=True)
                
                # Максимум попыток = количество доступных прокси (проверяем все)
                max_proxy_attempts = len(available_proxies) if available_proxies else 20
                log_both("info", f"    📊 Страница {page_num}: Доступно {len(available_proxies) if available_proxies else 0} прокси, максимум попыток: {max_proxy_attempts}")
                
                # Пробуем каждый прокси по очереди, пока не найдем рабочий
                # ВАЖНО: Не останавливаемся, пока не проверим все прокси или не получим результат
                for attempt in range(max_proxy_attempts):
                    log_both("info", f"    🔄 Страница {page_num}: Попытка {attempt + 1}/{max_proxy_attempts} получить рабочий прокси...")
                    
                    if available_proxies and len(available_proxies) > 0:
                        # Берем следующий прокси из списка (по кругу)
                        page_proxy = available_proxies[attempt % len(available_proxies)]
                        log_both("info", f"    🔄 Страница {page_num}: Попытка {attempt + 1}/{max_proxy_attempts}, пробуем прокси ID={page_proxy.id}")
                    else:
                        # Если нет доступных прокси, пробуем получить через get_next_proxy с предварительной проверкой
                        log_both("info", f"    🔄 Страница {page_num}: Попытка {attempt + 1} - получаем прокси через get_next_proxy (precheck={attempt == 0})...")
                        page_proxy = await self.proxy_manager.get_next_proxy(force_refresh=(attempt == 0), precheck=(attempt == 0))
                        if not page_proxy:
                            log_both("warning", f"    ⚠️ Страница {page_num}: Попытка {attempt + 1} - не удалось получить прокси")
                            if attempt < max_proxy_attempts - 1:
                                log_both("info", f"    ⏳ Страница {page_num}: Ожидаем 2 секунды перед следующей попыткой...")
                                await asyncio.sleep(2)  # Небольшая задержка перед следующей попыткой
                            continue
                    
                    # Задержка между запросами страниц (важно для избежания блокировок)
                    log_both("debug", f"    ⏳ Страница {page_num}: Задержка перед запросом...")
                    await self._random_delay(min_seconds=1.0, max_seconds=2.0)
                    
                    # Пробуем загрузить данные через этот прокси
                    log_both("info", f"    🚀 Страница {page_num}: Пробуем загрузить данные через прокси ID={page_proxy.id}...")
                    try:
                        from .steam_http_client import SteamHttpClient
                        temp_client = SteamHttpClient(proxy=page_proxy.url, timeout=30, proxy_manager=self.proxy_manager)
                        await temp_client._ensure_client()
                        try:
                            temp_parser = SteamMarketParser(proxy=page_proxy.url, timeout=30, redis_service=self.redis_service, proxy_manager=self.proxy_manager)
                            await temp_parser._ensure_client()
                            render_data = await temp_parser._fetch_render_api(appid, hash_name, start=start, count=listings_per_page)
                            await temp_parser.close()
                            
                            if render_data is not None:
                                # Успешно загрузили данные
                                log_both("info", f"    ✅ Страница {page_num}: Успешно загружена через прокси ID={page_proxy.id} (попытка {attempt + 1})")
                                if self.proxy_manager:
                                    await self.proxy_manager.mark_proxy_used(page_proxy, success=True)
                                break  # Выходим из цикла попыток
                            else:
                                # Данные не загрузились, пробуем следующий прокси
                                log_both("warning", f"    ⚠️ Страница {page_num}: Прокси ID={page_proxy.id} не вернул данные, пробуем следующий")
                                if self.proxy_manager:
                                    await self.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Не удалось загрузить данные")
                        finally:
                            await temp_client.close()
                    except Exception as e:
                        # Ошибка при использовании прокси, пробуем следующий
                        log_both("warning", f"    ⚠️ Страница {page_num}: Ошибка с прокси ID={page_proxy.id}: {type(e).__name__}, пробуем следующий")
                        if self.proxy_manager:
                            await self.proxy_manager.mark_proxy_used(page_proxy, success=False, error=str(e))
                        continue
                
                # Если после всех попыток не получили данные
                if render_data is None:
                    log_both("error", f"    ❌ Страница {page_num}: Не удалось загрузить через все доступные прокси ({max_proxy_attempts} попыток)")
                    # Не прерываем парсинг, просто пропускаем эту страницу и продолжаем
                    log_both("warning", f"    ⏭️ Пропускаем страницу {page_num} и продолжаем парсинг следующих страниц")
                    start += listings_per_page
                    page_num += 1
                    continue
            else:
                # Нет proxy_manager, используем основной парсер
                log_both("warning", f"    ⚠️ Страница {page_num}: Нет proxy_manager, используем основной парсер")
                await self._random_delay(min_seconds=1.0, max_seconds=2.0)
                render_data = await self._fetch_render_api(appid, hash_name, start=start, count=listings_per_page)
                
                if render_data is None:
                    log_both("warning", f"    ⚠️ Не удалось загрузить страницу {page_num} через основной парсер")
                    start += listings_per_page
                    page_num += 1
                    continue
            
            # Обновляем total_count из первой страницы
            if total_count is None:
                total_count = render_data.get('total_count')
                if total_count:
                    log_both("info", f"    📊 Всего лотов: {total_count}")
                    # ВАЖНО: Логируем для отладки
                    log_both("info", f"    🔍 DEBUG: total_count установлен в {total_count} на странице {page_num}")
            else:
                # ВАЖНО: Проверяем, что total_count не потерялся
                current_total = render_data.get('total_count')
                if current_total and current_total != total_count:
                    log_both("warning", f"    ⚠️ total_count изменился: было {total_count}, стало {current_total}, обновляем")
                    total_count = current_total
            
            # Извлекаем данные из assets для быстрого доступа к паттерну, float и наклейкам
            log_both("info", f"    🚀 НАЧИНАЕМ ПАРСИНГ ASSETS")
            
            if 'assets' in render_data and '730' in render_data['assets']:
                app_assets = render_data['assets']['730']
                log_both("info", f"    📊 Найдено {len(app_assets)} контекстов в assets")
                for contextid, items in app_assets.items():
                    for itemid, item in items.items():
                        # ВАЖНО: Преобразуем itemid в строку для единообразия
                        itemid = str(itemid)
                        pattern = None
                        float_value = None
                        stickers = []
                        
                        # Парсим asset_properties для паттерна и float
                        if 'asset_properties' in item:
                            props = item['asset_properties']
                            log_both("info", f"    🔍 Asset {itemid}: Найдено {len(props)} свойств в asset_properties")
                            
                            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Выводим RAW данные для всех assets на первой странице
                            if page_num == 1:
                                log_both("info", f"    📋 ДЕТАЛЬНАЯ ИНФОРМАЦИЯ для asset {itemid} (страница 1):")
                                log_both("info", f"       asset_properties (RAW): {props}")
                                for idx, prop in enumerate(props):
                                    log_both("info", f"       [{idx}] propertyid={prop.get('propertyid')}, keys={list(prop.keys())}, values={prop}")
                            
                            for prop in props:
                                prop_id = prop.get('propertyid')
                                # propertyid=1 для скинов, propertyid=3 для брелков
                                # Проверяем оба, но не перезаписываем, если паттерн уже найден
                                if (prop_id == 1 or prop_id == 3) and pattern is None:
                                    pattern = prop.get('int_value')
                                    log_both("info", f"    ✅ Asset {itemid}: Найден паттерн (propertyid={prop_id}): {pattern} (тип: {type(pattern).__name__})")
                                    log_both("info", f"       RAW prop: {prop}")
                                    # ВАЖНО: Специальное логирование для паттерна 896 (сравниваем как int и str)
                                    if pattern == 896 or pattern == "896" or str(pattern) == "896":
                                        log_both("info", f"    🔥 НАЙДЕН ПАТТЕРН 896 в asset {itemid} на странице {page_num} (start={start})!")
                                    # ВАЖНО: Специальное логирование для паттерна 142
                                    if pattern == 142 or pattern == "142" or str(pattern) == "142":
                                        log_both("info", f"    🔥🔥🔥 НАЙДЕН ПАТТЕРН 142 в asset {itemid} на странице {page_num} (start={start})!")
                                        log_both("info", f"       RAW prop для паттерна 142: {prop}")
                                        log_both("info", f"       float_value в этом asset: {float_value}")
                                elif prop_id == 2:
                                    float_value_raw = prop.get('float_value')
                                    # ВАЖНО: Нормализуем float_value к float для корректного сравнения
                                    try:
                                        float_value = float(float_value_raw) if float_value_raw is not None else None
                                    except (ValueError, TypeError):
                                        float_value = float_value_raw
                                        log_both("warning", f"    ⚠️ Asset {itemid}: Не удалось преобразовать float_value {float_value_raw} к float")
                                    log_both("info", f"    ✅ Asset {itemid}: Найден float (propertyid=2): {float_value_raw} -> {float_value} (тип: {type(float_value).__name__})")
                                    
                                    # Специальное логирование для float в диапазоне 0.22-0.26
                                    if float_value and 0.22 <= float_value <= 0.26:
                                        log_both("info", f"    🎯🎯🎯 НАЙДЕН FLOAT в диапазоне 0.22-0.26: {float_value} (тип: {type(float_value).__name__})")
                        else:
                            log_both("warning", f"    ⚠️ Asset {itemid}: Нет asset_properties")
                            if page_num == 1:
                                log_both("warning", f"    📋 ДЕТАЛЬНАЯ ИНФОРМАЦИЯ для asset {itemid} (страница 1, нет asset_properties): keys={list(item.keys())}")
                                log_both("warning", f"       Полный item (первые 500 символов): {str(item)[:500]}")
                        
                        # Парсим descriptions для наклеек
                        if 'descriptions' in item:
                            log_both("info", f"    🔍 ПАРСИНГ DESCRIPTIONS: Найдено {len(item['descriptions'])} descriptions для item {itemid}")
                            for desc in item['descriptions']:
                                desc_name = desc.get('name', '')
                                log_both("info", f"    📝 Description: name='{desc_name}', value_length={len(desc.get('value', ''))}")
                                if desc_name == 'sticker_info':
                                    sticker_html = desc.get('value', '')
                                    log_both("info", f"    🎯 Найден sticker_info для item {itemid}, HTML длина: {len(sticker_html)}")
                                    if sticker_html:
                                        from bs4 import BeautifulSoup
                                        from core.models import StickerInfo
                                        sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                        images = sticker_soup.find_all('img')
                                        log_both("info", f"    🖼️ Найдено {len(images)} изображений наклеек")
                                        
                                        # Парсим наклейки из title атрибутов изображений
                                        # ВАЖНО: Максимум 5 наклеек (позиции 0-4)
                                        for idx, img in enumerate(images):
                                            if idx >= 5:  # Пропускаем, если уже 5 наклеек
                                                log_both("warning", f"    ⚠️ Пропускаем изображение {idx}: достигнут лимит наклеек (максимум 5)")
                                                break
                                            
                                            title = img.get('title', '')
                                            log_both("debug", f"    🏷️ Изображение {idx}: title='{title}'")
                                            if title and 'Sticker:' in title:
                                                sticker_name = title.replace('Sticker: ', '').strip()
                                                if sticker_name and len(sticker_name) > 3:
                                                    # Проверяем, нет ли уже такой наклейки
                                                    if not any(s.name == sticker_name for s in stickers):
                                                        log_both("info", f"    ✅ Найдена наклейка из title: {sticker_name} (позиция {len(stickers)})")
                                                        stickers.append(StickerInfo(
                                                            position=len(stickers),  # Используем текущую длину списка для позиции
                                                            name=sticker_name,
                                                            wear=sticker_name,
                                                            price=None
                                                        ))
                                                    else:
                                                        log_both("debug", f"    ⏭️ Наклейка {sticker_name} уже есть в списке, пропускаем")
                                        
                                        # ВАЖНО: Также парсим из текста после изображений (на случай если title отсутствует)
                                        # Формат: "Sticker: War, FaZe Clan | Paris 2023, ..."
                                        text_content = sticker_soup.get_text()
                                        if 'Sticker:' in text_content:
                                            # Извлекаем список наклеек из текста
                                            import re
                                            # Ищем паттерн "Sticker: название1, название2, ..."
                                            sticker_text_match = re.search(r'Sticker:\s*([^<]+)', text_content, re.IGNORECASE)
                                            if sticker_text_match:
                                                sticker_text = sticker_text_match.group(1).strip()
                                                log_both("debug", f"    📝 Текст наклеек: '{sticker_text}'")
                                                # Разбиваем по запятым
                                                sticker_names_from_text = [s.strip() for s in sticker_text.split(',') if s.strip()]
                                                log_both("info", f"    📋 Найдено {len(sticker_names_from_text)} наклеек в тексте")
                                                
                                                # Добавляем наклейки, которых еще нет в списке
                                                # ВАЖНО: Максимум 5 наклеек (позиции 0-4)
                                                for idx, sticker_name in enumerate(sticker_names_from_text):
                                                    # Проверяем лимит ПЕРЕД добавлением
                                                    if len(stickers) >= 5:
                                                        log_both("warning", f"    ⚠️ Достигнут лимит наклеек (5), пропускаем: {sticker_name}")
                                                        break
                                                    
                                                    if sticker_name and len(sticker_name) > 3:
                                                        # Проверяем, нет ли уже такой наклейки
                                                        if not any(s.name == sticker_name for s in stickers):
                                                            position = len(stickers)  # Позиция будет 0-4 (максимум 5 наклеек)
                                                            if position > 4:
                                                                log_both("warning", f"    ⚠️ Пропускаем наклейку {sticker_name}: достигнут лимит позиций (максимум 5 наклеек)")
                                                                break
                                                            log_both("info", f"    ✅ Добавлена наклейка из текста: {sticker_name} (позиция {position})")
                                                            stickers.append(StickerInfo(
                                                                position=position,
                                                                name=sticker_name,
                                                                wear=sticker_name,
                                                                price=None
                                                            ))
                                        
                                        log_both("info", f"    📊 Итого найдено {len(stickers)} наклеек для item {itemid}")
                                        break
                        else:
                            log_both("debug", f"    ❌ Нет descriptions для item {itemid}")
                        
                        # Сохраняем данные только если есть что-то полезное
                        if pattern is not None or float_value is not None or stickers:
                            # ВАЖНО: Преобразуем паттерн в int (может быть строкой из JSON)
                            if pattern is not None:
                                pattern_original = pattern
                                try:
                                    pattern = int(pattern)
                                    if pattern_original != pattern:
                                        log_both("info", f"    🔄 Паттерн преобразован: {pattern_original} (тип: {type(pattern_original).__name__}) -> {pattern} (тип: {type(pattern).__name__})")
                                except (ValueError, TypeError):
                                    log_both("warning", f"    ⚠️ Не удалось преобразовать паттерн в int: {pattern} (тип: {type(pattern).__name__})")
                                    pattern = None
                            
                            # ВАЖНО: Преобразуем float_value в float (может быть строкой из JSON)
                            if float_value is not None:
                                float_original = float_value
                                try:
                                    float_value = float(float_value)
                                    if float_original != float_value:
                                        log_both("info", f"    🔄 Float преобразован: {float_original} (тип: {type(float_original).__name__}) -> {float_value} (тип: {type(float_value).__name__})")
                                except (ValueError, TypeError):
                                    log_both("warning", f"    ⚠️ Не удалось преобразовать float_value в float: {float_value} (тип: {type(float_value).__name__})")
                                    float_value = None
                            
                            assets_data_map[itemid] = {
                                'pattern': pattern,
                                'float_value': float_value,
                                'stickers': stickers,
                                'contextid': contextid
                            }
                            
                            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ СОХРАНЕНИЯ
                            log_both("info", f"    💾 СОХРАНЕНО В assets_data_map[{itemid}]:")
                            log_both("info", f"       - pattern: {pattern} (тип: {type(pattern).__name__})")
                            log_both("info", f"       - float_value: {float_value}")
                            log_both("info", f"       - stickers: {len(stickers)} штук")
                            log_both("info", f"       - contextid: {contextid}")
                            
                            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для первой страницы - ВСЕ assets
                            if page_num == 1:
                                log_both("info", f"    🔥 КРИТИЧЕСКОЕ: Сохранен asset_id={itemid} с pattern={pattern} (тип: {type(pattern).__name__})")
                                log_both("info", f"       Полный объект: pattern={pattern}, float={float_value}, stickers={len(stickers)}, contextid={contextid}")
                                
                                # Специально для asset_id=48106224934
                                if itemid == "48106224934":
                                    log_both("info", f"    🎯🎯🎯 ОБНАРУЖЕН asset_id=48106224934! pattern={pattern}, тип={type(pattern).__name__}")
                                    if pattern == 896:
                                        log_both("info", f"    🎯🎯🎯 ПАТТЕРН 896 ПОДТВЕРЖДЕН для asset_id=48106224934!")
                            
                            # ВАЖНО: Логируем паттерны из фильтра специально для диагностики (сравниваем как int и str)
                            if pattern in [63, 575, 896, 142] or str(pattern) in ["63", "575", "896", "142"]:
                                log_both("info", f"    🎯 ОБНАРУЖЕН ПАТТЕРН {pattern} (из фильтра) в asset {itemid}!")
                            
                            # Специальное логирование для паттерна 142
                            if pattern == 142 or str(pattern) == "142":
                                log_both("info", f"    🔥🔥🔥 НАЙДЕН ПАТТЕРН 142 в asset {itemid} на странице {page_num}!")
                                log_both("info", f"       float_value: {float_value}")
                                log_both("info", f"       contextid: {contextid}")
                            
                            # Специальное логирование для float в диапазоне 0.22-0.26
                            if float_value and 0.22 <= float_value <= 0.26:
                                log_both("info", f"    🎯🎯🎯 НАЙДЕН FLOAT в диапазоне 0.22-0.26: {float_value} в asset {itemid} на странице {page_num}!")
                                log_both("info", f"       pattern: {pattern}")
                                log_both("info", f"       contextid: {contextid}")
                            
                            if stickers:
                                log_both("info", f"       🏷️ СПИСОК НАКЛЕЕК В assets_data_map:")
                                for i, sticker in enumerate(stickers):
                                    sticker_name = sticker.name if hasattr(sticker, 'name') else str(sticker)
                                    log_both("info", f"          [{i}] {sticker_name} (тип: {type(sticker)})")
                        else:
                            log_both("info", f"    ❌ НЕ СОХРАНЕНО для item {itemid}: pattern={pattern}, float={float_value}, stickers={len(stickers)}")
            
            # Парсим HTML из results_html для получения listing_id, цен и inspect ссылок
            results_html = render_data.get('results_html', '')
            if results_html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(results_html, 'html.parser')
                parser = ItemPageParser(results_html)
                page_listings = parser.get_all_listings()
                
                # Связываем listing_id с данными из assets через listinginfo
                if 'listinginfo' in render_data:
                    listinginfo = render_data['listinginfo']
                    log_both("info", f"    📋 listinginfo содержит {len(listinginfo)} записей: {list(listinginfo.keys())[:10]}...")
                    for listing in page_listings:
                        listing_id = listing.get('listing_id')
                        # ВАЖНО: Преобразуем listing_id в строку для сравнения (может быть int или str)
                        if listing_id:
                            listing_id = str(listing_id)
                        else:
                            log_both("warning", f"    ⚠️ Лот не имеет listing_id: {listing}")
                            continue
                        
                        # ВАЖНО: Если listing_id есть в listinginfo, используем его для поиска asset
                        if listing_id in listinginfo:
                            listing_data = listinginfo[listing_id]
                            if 'asset' in listing_data:
                                asset_info = listing_data['asset']
                                asset_id = asset_info.get('id')
                                # ВАЖНО: Преобразуем asset_id в строку для сравнения
                                if asset_id:
                                    asset_id = str(asset_id)
                                contextid = asset_info.get('contextid')
                                
                                # Ищем данные в assets_data_map
                                log_both("info", f"    🔍 ПОИСК ДАННЫХ: listing_id={listing_id} (тип: {type(listing_id).__name__}), asset_id={asset_id} (тип: {type(asset_id).__name__})")
                                log_both("info", f"    📊 assets_data_map содержит {len(assets_data_map)} записей: {list(assets_data_map.keys())[:10]}...")
                                
                                # Пробуем найти по точному asset_id
                                found_asset_data = None
                                if asset_id in assets_data_map:
                                    found_asset_data = assets_data_map[asset_id]
                                    pattern_value = found_asset_data.get('pattern')
                                    log_both("info", f"    ✅ Найдено по точному asset_id: {asset_id}, паттерн={pattern_value} (тип: {type(pattern_value).__name__})")
                                    
                                    # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для asset_id=48106224934
                                    if asset_id == "48106224934":
                                        log_both("info", f"    🎯🎯🎯 СВЯЗЫВАНИЕ: listing_id={listing_id} -> asset_id={asset_id}")
                                        log_both("info", f"       Найденный паттерн: {pattern_value} (тип: {type(pattern_value).__name__})")
                                        log_both("info", f"       Полный found_asset_data: {found_asset_data}")
                                        if pattern_value == 896:
                                            log_both("info", f"    🎯🎯🎯 ПАТТЕРН 896 НАЙДЕН ПРИ СВЯЗЫВАНИИ для listing_id={listing_id}, asset_id={asset_id}!")
                                else:
                                    # Fallback: ищем по частичному совпадению или другим критериям
                                    log_both("warning", f"    ⚠️ Точный asset_id {asset_id} не найден, пробуем fallback поиск")
                                    
                                    # Пробуем найти по listing_id в качестве ключа (иногда используется)
                                    if listing_id in assets_data_map:
                                        found_asset_data = assets_data_map[listing_id]
                                        log_both("info", f"    ✅ Найдено по listing_id как ключу: {listing_id}")
                                    else:
                                        # Пробуем найти первую запись с наклейками (если есть только одна)
                                        assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                                        if len(assets_with_stickers) == 1:
                                            found_asset_data = list(assets_with_stickers.values())[0]
                                            found_key = list(assets_with_stickers.keys())[0]
                                            log_both("info", f"    ✅ Найдено единственное asset с наклейками: {found_key}")
                                        else:
                                            log_both("error", f"    ❌ Не удалось найти подходящие данные в assets_data_map")
                                
                                if found_asset_data:
                                    assets_data = found_asset_data
                                    pattern_value = assets_data.get('pattern')
                                    log_both("info", f"    ✅ НАЙДЕНЫ ДАННЫЕ для asset {asset_id}")
                                    log_both("info", f"       - pattern: {pattern_value} (тип: {type(pattern_value).__name__ if pattern_value is not None else 'None'})")
                                    log_both("info", f"       - float_value: {assets_data.get('float_value')}")
                                    log_both("info", f"       - stickers: {len(assets_data.get('stickers', []))} штук")
                                    
                                    # ВАЖНО: Логируем паттерн 896 специально для диагностики (сравниваем как int и str)
                                    if pattern_value == 896 or pattern_value == "896" or str(pattern_value) == "896":
                                        log_both("info", f"    🎯 ОБНАРУЖЕН ПАТТЕРН 896 для listing_id={listing_id}, asset_id={asset_id}!")
                                    
                                    # Специальное логирование для паттерна 142
                                    if pattern_value == 142 or pattern_value == "142" or str(pattern_value) == "142":
                                        log_both("info", f"    🔥🔥🔥 ОБНАРУЖЕН ПАТТЕРН 142 для listing_id={listing_id}, asset_id={asset_id}!")
                                        log_both("info", f"       float_value: {assets_data.get('float_value')}")
                                        float_val = assets_data.get('float_value')
                                        if float_val and 0.22 <= float_val <= 0.26:
                                            log_both("info", f"    🎯🎯🎯 ПАТТЕРН 142 С FLOAT В ДИАПАЗОНЕ 0.22-0.26: {float_val}!")
                                    
                                    # Специальное логирование для float в диапазоне 0.22-0.26
                                    float_val_check = assets_data.get('float_value')
                                    if float_val_check and 0.22 <= float_val_check <= 0.26:
                                        log_both("info", f"    🎯🎯🎯 ОБНАРУЖЕН FLOAT В ДИАПАЗОНЕ 0.22-0.26: {float_val_check} для listing_id={listing_id}, asset_id={asset_id}!")
                                        log_both("info", f"       pattern: {pattern_value}")
                                    
                                    # Устанавливаем данные в listing
                                    listing['pattern'] = pattern_value
                                    listing['float_value'] = assets_data['float_value']
                                    
                                    # КРИТИЧЕСКИ ВАЖНО: Наклейки из assets
                                    stickers_from_assets = assets_data.get('stickers', [])
                                    log_both("info", f"    🎯 ПОЛУЧЕНЫ НАКЛЕЙКИ ИЗ assets_data: {len(stickers_from_assets)} штук")
                                    log_both("info", f"       stickers_from_assets = {stickers_from_assets}")
                                    
                                    # ПЕРЕДАЕМ В LISTING
                                    listing['stickers'] = stickers_from_assets
                                    log_both("info", f"    📤 УСТАНОВЛЕНО listing['stickers'] = {len(stickers_from_assets)} наклеек")
                                    
                                    listing['asset_id'] = asset_id
                                    listing['contextid'] = contextid
                                    
                                    # ПРОВЕРЯЕМ, ЧТО РЕАЛЬНО ЗАПИСАЛОСЬ
                                    actual_stickers = listing.get('stickers', [])
                                    log_both("info", f"    🔍 ПРОВЕРКА: listing.get('stickers') = {len(actual_stickers)} наклеек")
                                    
                                    if actual_stickers:
                                        log_both("info", f"    ✅ НАКЛЕЙКИ УСПЕШНО ПЕРЕДАНЫ В LISTING:")
                                        for i, sticker in enumerate(actual_stickers):
                                            sticker_name = sticker.name if hasattr(sticker, 'name') else str(sticker)
                                            log_both("info", f"       [{i}] {sticker_name} (тип: {type(sticker)})")
                                    else:
                                        log_both("error", f"    ❌ НАКЛЕЙКИ НЕ ПОПАЛИ В LISTING! stickers_from_assets={len(stickers_from_assets)}, actual_stickers={len(actual_stickers)}")
                                else:
                                    log_both("error", f"    ❌ Asset {asset_id} НЕ НАЙДЕН в assets_data_map!")
                                    log_both("error", f"       Доступные assets: {list(assets_data_map.keys())}")
                        else:
                            # Если listing_id нет в listinginfo, логируем это
                            log_both("warning", f"    ⚠️ listing_id {listing_id} не найден в listinginfo (доступные ключи: {list(listinginfo.keys())[:5]}...)")
                            # Пробуем найти наклейки по другим критериям
                            # (например, если есть только один asset с наклейками)
                            if len(assets_data_map) == 1:
                                # Если только один asset, используем его данные
                                found_asset_data = list(assets_data_map.values())[0]
                                if found_asset_data.get('stickers'):
                                    listing['stickers'] = found_asset_data.get('stickers', [])
                                    listing['pattern'] = found_asset_data.get('pattern')
                                    listing['float_value'] = found_asset_data.get('float_value')
                                    log_both("info", f"    ✅ Fallback: Установлены данные из единственного asset для listing_id={listing_id}")
                            elif len(assets_data_map) > 1:
                                # Если несколько assets, пробуем найти по наклейкам
                                assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                                if len(assets_with_stickers) == 1:
                                    found_asset_data = list(assets_with_stickers.values())[0]
                                    listing['stickers'] = found_asset_data.get('stickers', [])
                                    listing['pattern'] = found_asset_data.get('pattern')
                                    listing['float_value'] = found_asset_data.get('float_value')
                                    log_both("info", f"    ✅ Fallback: Установлены данные из единственного asset с наклейками для listing_id={listing_id}")
                
                # ВАЖНО: Проверяем, что наклейки установлены для всех лотов перед добавлением в all_listings
                for listing in page_listings:
                    if 'stickers' not in listing or not listing.get('stickers'):
                        listing_id_check = listing.get('listing_id')
                        log_both("debug", f"    ⚠️ Лот {listing_id_check}: наклейки не установлены, проверяем fallback")
                        # Fallback: если наклейки не установлены, пробуем найти их в assets_data_map
                        if len(assets_data_map) > 0:
                            # Пробуем найти asset с наклейками
                            assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                            if len(assets_with_stickers) == 1:
                                found_asset_data = list(assets_with_stickers.values())[0]
                                listing['stickers'] = found_asset_data.get('stickers', [])
                                if 'pattern' not in listing:
                                    listing['pattern'] = found_asset_data.get('pattern')
                                if 'float_value' not in listing:
                                    listing['float_value'] = found_asset_data.get('float_value')
                                log_both("info", f"    ✅ Fallback: Установлены наклейки для лота {listing_id_check} из единственного asset с наклейками")
                
                all_listings.extend(page_listings)
                
                # ВАЖНО: Проверяем фильтры сразу после парсинга каждой страницы
                log_both("info", f"    🔍 Проверяем фильтры для {len(page_listings)} лотов на странице {page_num}...")
                
                for listing_idx, listing in enumerate(page_listings):
                    listing_price = listing.get('price', 0.0)
                    listing_id = listing.get('listing_id')
                    listing_pattern = listing.get('pattern')
                    listing_float = listing.get('float_value')
                    stickers = listing.get('stickers', [])
                    inspect_link = listing.get('inspect_link')
                    
                    # Создаем ParsedItemData из данных лота
                    from parsers.item_type_detector import detect_item_type
                    item_type = detect_item_type(
                        hash_name or "",
                        listing_float is not None,
                        len(stickers) > 0
                    )
                    if listing_pattern is not None and listing_pattern > 999:
                        item_type = "keychain"
                    
                    is_stattrak = "StatTrak" in hash_name or "StatTrak™" in hash_name
                    
                    parsed_data = ParsedItemData(
                        float_value=listing_float,
                        pattern=listing_pattern,
                        stickers=stickers,
                        total_stickers_price=0.0,  # Будет заполнено при необходимости
                        item_name=hash_name,
                        item_price=listing_price,
                        inspect_links=[inspect_link] if inspect_link else [],
                        item_type=item_type,
                        is_stattrak=is_stattrak,
                        listing_id=listing_id
                    )
                    
                    # Создаем item dict для FilterService
                    item_dict = {
                        "sell_price_text": f"${listing_price:.2f}",
                        "asset_description": {"market_hash_name": hash_name},
                        "name": hash_name
                    }
                    
                    # Проверяем фильтры через FilterService
                    pattern_str = str(listing_pattern) if listing_pattern is not None else '?'
                    float_str = f"{listing_float:.6f}" if listing_float is not None else '?'
                    log_both("info", f"    ┌─ ЛОТ [{listing_idx + 1}/{len(page_listings)}] (страница {page_num}) ─────────────────────────────────────────────")
                    log_both("info", f"    │ 💰 Цена: ${listing_price:.2f} | 🎨 Паттерн: {pattern_str} | 🔢 Float: {float_str}")
                    log_both("info", f"    │ 📝 Название: {hash_name}")
                    
                    try:
                        matches = await self.filter_service.matches_filters(item_dict, filters, parsed_data)
                        if matches:
                            log_both("info", f"    │ ✅✅✅ ВСЕ ФИЛЬТРЫ ПРОЙДЕНЫ!")
                            log_both("info", f"    └────────────────────────────────────────────────────────────────────")
                            matching_listings.append(parsed_data)
                            
                            # Детальное логирование для паттерна 522
                            if listing_pattern == 522:
                                log_both("info", f"    🎯🎯🎯 ЛОТ С ПАТТЕРНОМ 522 ПРОШЕЛ ВСЕ ФИЛЬТРЫ!")
                                log_both("info", f"       listing_id={listing_id}, price=${listing_price:.2f}, float={listing_float}, pattern={listing_pattern}")
                        else:
                            log_both("info", f"    │ ❌ НЕ ПРОШЕЛ ФИЛЬТРЫ")
                            log_both("info", f"    └────────────────────────────────────────────────────────────────────")
                    except Exception as e:
                        log_both("error", f"    │ ❌ ОШИБКА при проверке фильтров: {e}")
                        log_both("info", f"    └────────────────────────────────────────────────────────────────────")
                        import traceback
                        log_both("debug", f"    Traceback: {traceback.format_exc()}")
                
                # Детальное логирование каждого найденного предмета на странице (только в task_logger)
                if task_logger and task_logger.task_id and page_listings:
                    if total_count is not None:
                        total_pages = (total_count + listings_per_page - 1) // listings_per_page
                        task_logger.info(f"📋 Страница {page_num} из {total_pages}: Детальная информация по найденным предметам:")
                    else:
                        task_logger.info(f"📋 Страница {page_num}: Детальная информация по найденным предметам:")
                    
                    for idx, listing in enumerate(page_listings, 1):
                        listing_id = listing.get('listing_id', 'N/A')
                        price = listing.get('price', 0.0)
                        float_value = listing.get('float_value')
                        pattern = listing.get('pattern')
                        stickers = listing.get('stickers', [])
                        
                        # Формируем строку с информацией о предмете
                        item_info = f"   [{idx}] Лот #{listing_id}:"
                        item_info += f" 💰 Цена: ${price:.2f}"
                        
                        if float_value is not None:
                            item_info += f" | 🔢 Float: {float_value:.6f}"
                        else:
                            item_info += f" | 🔢 Float: N/A"
                        
                        if pattern is not None:
                            item_info += f" | 🎨 Паттерн: {pattern}"
                        else:
                            item_info += f" | 🎨 Паттерн: N/A"
                        
                        if stickers:
                            sticker_names = []
                            for sticker in stickers:
                                sticker_name = None
                                if hasattr(sticker, 'name') and sticker.name:
                                    sticker_name = sticker.name
                                elif isinstance(sticker, dict):
                                    sticker_name = sticker.get('name') or sticker.get('wear') or str(sticker)
                                else:
                                    sticker_name = str(sticker)
                                
                                if sticker_name:
                                    # Добавляем позицию, если есть
                                    if hasattr(sticker, 'position') and sticker.position is not None:
                                        sticker_names.append(f"Поз.{sticker.position + 1}: {sticker_name}")
                                    elif isinstance(sticker, dict) and sticker.get('position') is not None:
                                        sticker_names.append(f"Поз.{sticker['position'] + 1}: {sticker_name}")
                                    else:
                                        sticker_names.append(sticker_name)
                            
                            if sticker_names:
                                stickers_str = ', '.join(sticker_names[:3])  # Показываем первые 3
                                if len(sticker_names) > 3:
                                    stickers_str += f" ... (+{len(sticker_names) - 3} еще)"
                                item_info += f" | 🏷️ Наклейки ({len(stickers)}): {stickers_str}"
                            else:
                                item_info += f" | 🏷️ Наклейки ({len(stickers)}): нет названий"
                        else:
                            item_info += f" | 🏷️ Наклейки: нет"
                        
                        task_logger.info(item_info)
                
                # Логируем прогресс в обычный logger и task_logger
                if total_count is not None:
                    total_pages = (total_count + listings_per_page - 1) // listings_per_page
                    log_both("info", f"✅ Страница {page_num} из {total_pages}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                    if task_logger and task_logger.task_id:
                        task_logger.info(f"✅ Страница {page_num} из {total_pages}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                else:
                    log_both("info", f"✅ Страница {page_num}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                    if task_logger and task_logger.task_id:
                        task_logger.info(f"✅ Страница {page_num}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                
                if page_proxy and self.proxy_manager:
                    await self.proxy_manager.mark_proxy_used(page_proxy, success=True)
                
                # Проверяем, есть ли еще страницы
                # ВАЖНО: Если total_count известен, используем его для определения конца
                # Если total_count неизвестен, используем количество полученных лотов
                if total_count is not None:
                    # Используем total_count для точного определения конца
                    if start + listings_per_page >= total_count:
                        # Достигли конца
                        log_both("info", f"    ✅ Достигли конца: start={start}, listings_per_page={listings_per_page}, total_count={total_count}")
                        break
                else:
                    # Если total_count неизвестен, проверяем количество полученных лотов
                    if len(page_listings) < listings_per_page:
                        # На последней странице меньше listings_per_page лотов - это конец
                        log_both("info", f"    ✅ Достигли конца (нет total_count): получено {len(page_listings)} лотов, ожидалось {listings_per_page}")
                        break
                
                # Обновляем start и page_num для следующей итерации
                start += listings_per_page
                page_num += 1
                log_both("debug", f"    🔄 Переходим к следующей странице: start={start}, page_num={page_num}")
            else:
                log_both("warning", f"    ⚠️ Страница {page_num}: results_html пуст")
                break
        
        log_both("info", f"    📋 Всего найдено {len(all_listings)} лотов на всех страницах для проверки")
        log_both("info", f"    🔍 DEBUG: Начинаем проверку фильтров для {len(all_listings)} лотов")
        log_both("info", f"    🔍 DEBUG: matching_listings до проверки: {len(matching_listings)}")
        
        if not all_listings:
            log_both("error", f"    ⚠️ Не найдено лотов через API /render/, пробуем стандартный HTML парсинг")
            # Fallback к стандартному HTML парсингу
            html = await self._fetch_item_page(appid, hash_name)
            if html:
                parser = ItemPageParser(html)
                page_listings = parser.get_all_listings()
                all_listings.extend(page_listings)
                log_both("info", f"    📋 Fallback: Найдено {len(page_listings)} лотов через HTML парсинг")
            else:
                log_both("error", f"    ⚠️ Не удалось загрузить HTML страницу для fallback")
                return matching_listings
        
        log_both("info", f"    📊 Всего найдено {len(matching_listings)} подходящих лотов из {len(all_listings)}")
        return matching_listings

    async def get_stickers_prices(
        self,
        sticker_names: List[str],
        delay: float = 0.3
    ) -> Dict[str, Optional[float]]:
        """
        Получает цены наклеек через API с учетом кэширования.
        
        Args:
            sticker_names: Список названий наклеек
            delay: Задержка между запросами (в секундах)
            
        Returns:
            Словарь {название_наклейки: цена} или {название_наклейки: None} если цена не найдена
        """
        from parsers.sticker_prices import StickerPricesAPI
        
        if not sticker_names:
            return {}
        
        logger.debug(f"    🏷️ Получаем цены для {len(sticker_names)} наклеек через API")
        logger.info(f"    🔍 Запрашиваем цены для наклеек: {sticker_names[:5]}{'...' if len(sticker_names) > 5 else ''}")
        
        prices = await StickerPricesAPI.get_stickers_prices_batch(
            sticker_names,
            proxy=self.proxy,
            delay=delay,
            redis_service=self.redis_service,
            proxy_manager=self.proxy_manager
        )
        
        logger.info(f"    🏷️ Получено цен из API: {len(prices)} записей")
        if prices:
            logger.info(f"    🔍 Полученные ключи: {list(prices.keys())[:5]}{'...' if len(prices) > 5 else ''}")
            # Проверяем совпадения
            matched = [name for name in sticker_names if name in prices and prices[name] is not None]
            unmatched = [name for name in sticker_names if name not in prices or prices[name] is None]
            if unmatched:
                logger.warning(f"    ⚠️ Не найдено цен для {len(unmatched)} наклеек: {unmatched[:3]}{'...' if len(unmatched) > 3 else ''}")
        return prices

