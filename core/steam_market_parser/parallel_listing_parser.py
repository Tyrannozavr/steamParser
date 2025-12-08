"""
Модуль для параллельного парсинга страниц лотов.
Использует Redis очередь для распределения страниц между воркерами.
"""
import asyncio
import json
import random
from typing import Optional, List, Set
from datetime import datetime
from loguru import logger

from ..models import SearchFilters, ParsedItemData
from parsers import ItemPageParser, detect_item_type
from core.steam_market_parser.logger_utils import log_both
from core.steam_market_parser.page_range_optimizer import build_optimized_pages_list


async def parse_listings_parallel(
    parser,
    appid: int,
    hash_name: str,
    filters: SearchFilters,
    target_patterns: Optional[Set[int]],
    listings_per_page: int,
    total_count: int,
    active_proxies_count: int,
    task_logger=None,
    task=None,
    db_session=None,
    redis_service=None,
    db_manager=None
) -> List[ParsedItemData]:
    """
    Параллельный парсинг всех страниц лотов с использованием Redis очереди.
    Воркеры берут страницы из очереди последовательно (с первой по последнюю).
    
    Args:
        parser: Экземпляр SteamMarketParser
        appid: ID приложения
        hash_name: Хэш-имя предмета
        filters: Фильтры поиска
        target_patterns: Целевые паттерны
        listings_per_page: Лотов на страницу (20)
        total_count: Общее количество лотов
        active_proxies_count: Количество активных прокси
        task_logger: Логгер задачи
        task: Задача мониторинга
        db_session: Сессия БД
        redis_service: Сервис Redis
        
    Returns:
        Список ParsedItemData
    """
    def log(level: str, message: str):
        log_both(level, message, task_logger)
    
    log("info", f"🚀 parse_listings_parallel: Начало (total_count={total_count}, active_proxies={active_proxies_count}, redis_service={redis_service is not None})")
    
    # Создаем оптимизированный список страниц для парсинга
    # Если есть фильтр по цене, используем бинарный поиск для определения максимальной страницы
    pages_to_fetch = await build_optimized_pages_list(
        parser=parser,
        appid=appid,
        hash_name=hash_name,
        filters=filters,
        total_count=total_count,
        listings_per_page=listings_per_page,
        log_func=log
    )
    
    if not pages_to_fetch:
        log("info", "📄 Нет страниц лотов для парсинга")
        return []
    
    total_pages = len(pages_to_fetch)
    log("info", f"📄 Всего страниц лотов для парсинга: {total_pages} (всего лотов: {total_count})")
    
    # Получаем список активных прокси из Redis кэша (без обращения к БД)
    if not parser.proxy_manager:
        log("error", "❌ ProxyManager не доступен")
        return []
    
    # Получаем прокси напрямую из Redis кэша, минуя БД
    available_proxies = []
    if parser.proxy_manager.redis_service:
        try:
            log("debug", "🔍 Получаем прокси из Redis кэша...")
            cached_proxies_data = await parser.proxy_manager.redis_service.get(parser.proxy_manager.REDIS_CACHE_KEY)
            if cached_proxies_data:
                import json as json_lib
                from datetime import datetime as dt
                from core import Proxy
                cached_proxies = json_lib.loads(cached_proxies_data)
                
                for p_data in cached_proxies:
                    # Проверяем блокировку через Redis
                    proxy_id = p_data["id"]
                    blocked_key = f"{parser.proxy_manager.REDIS_BLOCKED_PREFIX}{proxy_id}"
                    blocked_until = await parser.proxy_manager.redis_service.get(blocked_key)
                    
                    is_blocked = False
                    if blocked_until:
                        try:
                            blocked_until_dt = dt.fromisoformat(blocked_until)
                            if dt.now() < blocked_until_dt:
                                is_blocked = True
                        except:
                            pass
                    
                    if not is_blocked and p_data.get("is_active", True):
                        # Создаем объект Proxy без привязки к сессии
                        proxy = Proxy(
                            id=proxy_id,
                            url=p_data["url"],
                            is_active=p_data.get("is_active", True),
                            delay_seconds=p_data.get("delay_seconds", 0.2),
                            success_count=p_data.get("success_count", 0),
                            fail_count=p_data.get("fail_count", 0),
                            last_used=dt.fromisoformat(p_data["last_used"]) if p_data.get("last_used") else None,
                            last_error=p_data.get("last_error")
                        )
                        from sqlalchemy.orm import make_transient
                        make_transient(proxy)
                        available_proxies.append(proxy)
        except Exception as e:
            log("warning", f"⚠️ Ошибка при получении прокси из Redis: {e}")
    
    # Если не получилось из Redis, пробуем через get_active_proxies (но без force_refresh)
    if not available_proxies:
        try:
            log("debug", "🔍 Получаем прокси через get_active_proxies...")
            active_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=False)
            if active_proxies:
                # Фильтруем только не заблокированные прокси
                for proxy in active_proxies:
                    is_blocked = False
                    if parser.proxy_manager.redis_service:
                        try:
                            blocked_key = f"{parser.proxy_manager.REDIS_BLOCKED_PREFIX}{proxy.id}"
                            blocked_until = await parser.proxy_manager.redis_service.get(blocked_key)
                            if blocked_until:
                                from datetime import datetime as dt
                                try:
                                    blocked_until_dt = dt.fromisoformat(blocked_until)
                                    if dt.now() < blocked_until_dt:
                                        is_blocked = True
                                except:
                                    pass
                        except:
                            pass
                    
                    if not is_blocked:
                        available_proxies.append(proxy)
        except Exception as e:
            log("error", f"❌ Ошибка при получении прокси: {e}")
    
    if not available_proxies:
        log("error", "❌ Нет доступных прокси")
        return []
    
    log("info", f"🌐 Доступно прокси: {len(available_proxies)}")
    
    # Параллельно n = proxies_count / 3 запросов
    max_concurrent = max(1, len(available_proxies) // 3)
    log("info", f"🔄 Параллельный парсинг: максимум {max_concurrent} одновременных воркеров (из {len(available_proxies)} прокси)")
    
    # Проверяем наличие Redis для очереди
    log("debug", f"🔍 Проверяем Redis: redis_service={redis_service is not None}, is_connected={redis_service.is_connected() if redis_service else False}")
    if not redis_service:
        log("error", "❌ Redis не доступен для очереди страниц: redis_service is None")
        return []
    if not redis_service.is_connected():
        log("error", "❌ Redis не доступен для очереди страниц: redis_service не подключен")
        try:
            await redis_service.connect()
            log("info", "✅ Redis подключен")
        except Exception as e:
            log("error", f"❌ Не удалось подключиться к Redis: {e}")
            return []
    
    # Создаем уникальный ключ очереди для этой задачи
    queue_key = f"parsing:pages:task_{task.id if task else 'unknown'}"
    log("info", f"📋 Создаем Redis очередь страниц: {queue_key}")
    
    # Добавляем все страницы в Redis очередь (в обратном порядке, чтобы брать с первой)
    try:
        log("info", f"📥 Добавляем {len(pages_to_fetch)} страниц в Redis очередь...")
        page_data_list = []
        for page_num, page_start, page_count in pages_to_fetch:
            page_data = json.dumps({
                "page_num": page_num,
                "page_start": page_start,
                "page_count": page_count,
                "appid": appid,
                "hash_name": hash_name
            })
            page_data_list.append(page_data)
        
        # Добавляем все страницы в очередь (LPUSH добавляет в начало, поэтому добавляем в обратном порядке)
        await redis_service.lpush(queue_key, *reversed(page_data_list))
        queue_length = await redis_service.llen(queue_key)
        log("info", f"✅ Добавлено {len(pages_to_fetch)} страниц в очередь (длина очереди: {queue_length})")
    except Exception as e:
        log("error", f"❌ Ошибка при добавлении страниц в очередь: {e}")
        import traceback
        log("error", f"   Traceback: {traceback.format_exc()}")
        return []
    
    # Результаты (упорядоченный список)
    results = [None] * len(pages_to_fetch)
    matching_listings = []
    lock = asyncio.Lock()
    completed_pages = 0
    max_retries = 3  # Максимум 3 попытки для страницы
    
    # Счетчики для диагностики
    task_start_times = {}  # page_num -> start_time
    task_stages = {}  # page_num -> current_stage
    
    async def get_random_proxy() -> Optional:
        """Получает случайный прокси из доступных."""
        if not available_proxies:
            return None
        return random.choice(available_proxies)
    
    async def process_page_from_queue(worker_id: int):
        """Воркер: берет страницы из Redis очереди и обрабатывает их."""
        nonlocal completed_pages, matching_listings
        
        log("info", f"    👷 Воркер {worker_id}: Запущен, ожидает страницы из очереди...")
        pages_processed = 0
        
        while True:
            page_data_str = None
            page_data = None
            page_num = None
            page_start = None
            page_count = None
            
            try:
                # Берем страницу из очереди (блокирующий pop с таймаутом 5 секунд)
                log("debug", f"    🔍 Воркер {worker_id}: Ожидает страницу из очереди (таймаут 5с)...")
                page_data_str = await redis_service.rpop(queue_key, timeout=5.0)
                
                if not page_data_str:
                    # Очередь пуста, проверяем еще раз
                    queue_length = await redis_service.llen(queue_key)
                    if queue_length == 0:
                        log("info", f"    ✅ Воркер {worker_id}: Очередь пуста, завершает работу (обработано страниц: {pages_processed})")
                        break
                    else:
                        log("debug", f"    ⏳ Воркер {worker_id}: Таймаут, но в очереди еще {queue_length} страниц, продолжаем...")
                        continue
                
                # Парсим данные страницы
                try:
                    page_data = json.loads(page_data_str)
                    page_num = page_data["page_num"]
                    page_start = page_data["page_start"]
                    page_count = page_data["page_count"]
                except Exception as e:
                    log("error", f"    ❌ Воркер {worker_id}: Ошибка при парсинге данных страницы: {e}")
                    log("error", f"       Данные: {page_data_str[:100]}")
                    continue
                
                # Проверяем, активна ли задача (для немедленной остановки)
                if task:
                    try:
                        from sqlalchemy import select
                        from core import MonitoringTask
                        if db_session:
                            result = await db_session.execute(
                                select(MonitoringTask).where(MonitoringTask.id == task.id)
                            )
                            db_task = result.scalar_one_or_none()
                            if db_task and not db_task.is_active:
                                log("info", f"🛑 Воркер {worker_id}: Задача {task.id} деактивирована, останавливаем обработку страницы {page_num}")
                                # Возвращаем страницу в очередь для других воркеров (если они еще работают)
                                # Но лучше просто пропустить эту страницу
                                continue
                    except Exception as e:
                        log("warning", f"⚠️ Воркер {worker_id}: Ошибка при проверке статуса задачи: {e}")
                
                # Начинаем обработку страницы
                task_start_time = datetime.now()
                task_start_times[page_num] = task_start_time
                task_stages[page_num] = "начало"
                pages_processed += 1
                
                log("info", f"    📄 Воркер {worker_id}: Начал обработку страницы {page_num}/{total_pages} (start={page_start}, count={page_count})")
                
                # Heartbeat для отслеживания зависших воркеров
                heartbeat_task = None
                # Сохраняем page_num в локальную переменную для heartbeat
                current_page_num = page_num
                async def heartbeat():
                    while True:
                        await asyncio.sleep(30)  # Каждые 30 секунд
                        elapsed = (datetime.now() - task_start_time).total_seconds()
                        current_stage = task_stages.get(current_page_num, "неизвестно")
                        log("warning", f"    💓 Воркер {worker_id}, страница {current_page_num}: HEARTBEAT - еще работает (этап: '{current_stage}', прошло {elapsed:.1f}с)")
                
                try:
                    heartbeat_task = asyncio.create_task(heartbeat())
                except Exception as hb_error:
                    log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Не удалось создать heartbeat: {hb_error}")
                
                # Обрабатываем страницу с retry
                for attempt in range(max_retries):
                    page_proxy = None
                    temp_client = None
                    temp_parser = None
                    
                    try:
                        # Этап 1: Выбор прокси
                        proxy_select_start = datetime.now()
                        task_stages[page_num] = f"выбор_прокси (попытка {attempt + 1})"
                        log("debug", f"    🔍 Воркер {worker_id}, страница {page_num}: Выбираем прокси (попытка {attempt + 1}/{max_retries})...")
                        
                        page_proxy = await get_random_proxy()
                        proxy_select_time = (datetime.now() - proxy_select_start).total_seconds()
                        
                        if not page_proxy:
                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Нет доступных прокси (попытка {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Нет доступных прокси после {max_retries} попыток")
                                async with lock:
                                    completed_pages += 1
                                break
                        
                        log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} выбран за {proxy_select_time:.2f}с")
                        
                        # Этап 2: Создание HTTP клиента
                        client_create_start = datetime.now()
                        task_stages[page_num] = f"создание_клиента (прокси {page_proxy.id}, попытка {attempt + 1})"
                        log("debug", f"    🔧 Воркер {worker_id}, страница {page_num}: Создаем HTTP клиент с прокси ID={page_proxy.id}...")
                        
                        from ..steam_http_client import SteamHttpClient
                        temp_client = SteamHttpClient(proxy=page_proxy.url, timeout=30, proxy_manager=parser.proxy_manager)
                        await temp_client._ensure_client()
                        
                        temp_parser = parser.__class__(proxy=page_proxy.url, timeout=30, redis_service=parser.redis_service, proxy_manager=parser.proxy_manager)
                        await temp_parser._ensure_client()
                        
                        client_create_time = (datetime.now() - client_create_start).total_seconds()
                        log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: HTTP клиент создан за {client_create_time:.2f}с")
                        
                        # Этап 3: Ротация заголовков
                        headers_start = datetime.now()
                        task_stages[page_num] = f"ротация_заголовков (прокси {page_proxy.id}, попытка {attempt + 1})"
                        log("debug", f"    🔄 Воркер {worker_id}, страница {page_num}: Обновляем заголовки...")
                        page_headers = temp_parser._get_browser_headers()
                        temp_parser._client.headers.update(page_headers)
                        headers_time = (datetime.now() - headers_start).total_seconds()
                        log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Заголовки обновлены за {headers_time:.2f}с")
                        
                        # Этап 4: Выполнение запроса
                        request_start = datetime.now()
                        task_stages[page_num] = f"выполнение_запроса (прокси {page_proxy.id}, start={page_start}, попытка {attempt + 1})"
                        log("info", f"    📡 Воркер {worker_id}, страница {page_num}: Отправляем запрос через прокси ID={page_proxy.id} (start={page_start}, count={page_count})...")
                        
                        try:
                            render_data = await asyncio.wait_for(
                                temp_parser._fetch_render_api(appid, hash_name, start=page_start, count=page_count),
                                timeout=60.0
                            )
                            request_time = (datetime.now() - request_start).total_seconds()
                            log("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Запрос выполнен за {request_time:.2f}с")
                        except asyncio.TimeoutError:
                            request_time = (datetime.now() - request_start).total_seconds()
                            log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: ТАЙМАУТ запроса после {request_time:.2f}с на этапе 'выполнение_запроса'")
                            raise
                        except Exception as req_error:
                            request_time = (datetime.now() - request_start).total_seconds()
                            log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: ОШИБКА запроса после {request_time:.2f}с: {type(req_error).__name__}: {req_error}")
                            raise
                        
                        if render_data is None:
                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} не вернул данные (попытка {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} не вернул данные после {max_retries} попыток")
                                async with lock:
                                    completed_pages += 1
                                break
                        
                        # Этап 5: Парсинг данных
                        parse_start = datetime.now()
                        task_stages[page_num] = f"парсинг_данных (прокси {page_proxy.id}, попытка {attempt + 1})"
                        log("info", f"    🔍 Воркер {worker_id}, страница {page_num}: Начинаем парсинг данных...")
                        
                        page_matching_listings = []
                        
                        # Извлекаем данные из assets
                        assets_data_map = {}
                        if 'assets' in render_data and '730' in render_data['assets']:
                            app_assets = render_data['assets']['730']
                            for contextid, items in app_assets.items():
                                for itemid, item in items.items():
                                    itemid = str(itemid)
                                    pattern = None
                                    float_value = None
                                    stickers = []
                                    
                                    # Парсим asset_properties для паттерна и float
                                    if 'asset_properties' in item:
                                        props = item['asset_properties']
                                        for prop in props:
                                            prop_id = prop.get('propertyid')
                                            # propertyid=1 для скинов, propertyid=3 для брелков
                                            # Проверяем оба, но не перезаписываем, если паттерн уже найден
                                            if (prop_id == 1 or prop_id == 3) and pattern is None:
                                                pattern = prop.get('int_value')
                                                try:
                                                    pattern = int(pattern) if pattern is not None else None
                                                except (ValueError, TypeError):
                                                    pattern = None
                                            elif prop_id == 2:
                                                float_value_raw = prop.get('float_value')
                                                try:
                                                    float_value = float(float_value_raw) if float_value_raw is not None else None
                                                except (ValueError, TypeError):
                                                    float_value = None
                                    
                                    # Парсим descriptions для наклеек используя StickerParser
                                    if 'descriptions' in item:
                                        from core.utils.sticker_parser import StickerParser
                                        parsed_stickers = StickerParser.parse_stickers_from_asset(item, max_stickers=5)
                                        stickers.extend(parsed_stickers)
                                    
                                    # Сохраняем данные
                                    if pattern is not None or float_value is not None or stickers:
                                        # Сохраняем по itemid (это ID из assets)
                                        assets_data_map[itemid] = {
                                            'pattern': pattern,
                                            'float_value': float_value,
                                            'stickers': stickers,
                                            'contextid': contextid,
                                            'itemid': itemid  # Сохраняем для отладки
                                        }
                                        if stickers:
                                            log("debug", f"    💾 Воркер {worker_id}, страница {page_num}: Сохранены наклейки для itemid={itemid}: {[s.name for s in stickers[:3]]}")
                        
                        # Парсим HTML из results_html
                        results_html = render_data.get('results_html', '')
                        if not results_html:
                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: results_html пуст (попытка {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: results_html пуст после {max_retries} попыток")
                                async with lock:
                                    completed_pages += 1
                                break
                        
                        parser_obj = ItemPageParser(results_html)
                        page_listings = parser_obj.get_all_listings()
                        
                        # Связываем listing_id с данными из assets через listinginfo
                        if 'listinginfo' in render_data:
                            listinginfo = render_data['listinginfo']
                            for listing in page_listings:
                                listing_id = listing.get('listing_id')
                                if listing_id:
                                    listing_id = str(listing_id)
                                else:
                                    continue
                                
                                if listing_id in listinginfo:
                                    listing_data = listinginfo[listing_id]
                                    if 'asset' in listing_data:
                                        asset_info = listing_data['asset']
                                        asset_id = asset_info.get('id')
                                        asset_contextid = asset_info.get('contextid')
                                        if asset_id:
                                            asset_id = str(asset_id)
                                        
                                        # Ищем данные в assets_data_map
                                        found_asset_data = None
                                        if asset_id in assets_data_map:
                                            found_asset_data = assets_data_map[asset_id]
                                            log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по asset_id={asset_id}")
                                        elif listing_id in assets_data_map:
                                            found_asset_data = assets_data_map[listing_id]
                                            log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по listing_id={listing_id}")
                                        else:
                                            # Fallback: ищем по itemid из сохраненных данных
                                            # Проверяем, есть ли в assets_data_map запись с таким itemid
                                            for key, data in assets_data_map.items():
                                                if data.get('itemid') == asset_id:
                                                    found_asset_data = data
                                                    log("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по itemid={asset_id} (ключ в map: {key})")
                                                    break
                                            
                                            if not found_asset_data:
                                                # Fallback 1: ищем по всем ключам, сравнивая itemid
                                                for key, data in assets_data_map.items():
                                                    stored_itemid = data.get('itemid')
                                                    if stored_itemid and str(stored_itemid) == str(asset_id):
                                                        found_asset_data = data
                                                        log("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по itemid={asset_id} (ключ в map: {key})")
                                                        break
                                                
                                                if not found_asset_data:
                                                    # Fallback 2: единственный asset с наклейками на странице
                                                    assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                                                    if len(assets_with_stickers) == 1:
                                                        found_asset_data = list(assets_with_stickers.values())[0]
                                                        log("info", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Использован fallback (единственный asset с наклейками) для listing_id={listing_id}, asset_id={asset_id}")
                                                    elif len(assets_with_stickers) > 1:
                                                        # Если несколько assets с наклейками, пробуем найти по контексту
                                                        # Ищем asset с таким же contextid
                                                        if 'asset_contextid' in locals() and asset_contextid:
                                                            matching_by_context = [v for k, v in assets_with_stickers.items() if v.get('contextid') == asset_contextid]
                                                            if len(matching_by_context) == 1:
                                                                found_asset_data = matching_by_context[0]
                                                                log("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по contextid={asset_contextid} для listing_id={listing_id}")
                                                        else:
                                                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: НЕ НАЙДЕН asset для listing_id={listing_id}, asset_id={asset_id}")
                                                            log("warning", f"       assets_data_map содержит {len(assets_data_map)} записей")
                                                            log("warning", f"       assets_with_stickers: {len(assets_with_stickers)} записей")
                                                            if assets_data_map:
                                                                log("warning", f"       Примеры ключей в assets_data_map: {list(assets_data_map.keys())[:5]}")
                                                                sample_itemids = [v.get('itemid') for v in list(assets_data_map.values())[:5] if v.get('itemid')]
                                                                if sample_itemids:
                                                                    log("warning", f"       Примеры itemid в данных: {sample_itemids}")
                                                    else:
                                                        log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: НЕ НАЙДЕН asset для listing_id={listing_id}, asset_id={asset_id}")
                                                        log("warning", f"       assets_data_map содержит {len(assets_data_map)} записей")
                                                        log("warning", f"       assets_with_stickers: {len(assets_with_stickers)} записей")
                                                        if assets_data_map:
                                                            log("warning", f"       Примеры ключей в assets_data_map: {list(assets_data_map.keys())[:5]}")
                                                            sample_itemids = [v.get('itemid') for v in list(assets_data_map.values())[:5] if v.get('itemid')]
                                                            if sample_itemids:
                                                                log("warning", f"       Примеры itemid в данных: {sample_itemids}")
                                        
                                        if found_asset_data:
                                            stickers_count = len(found_asset_data.get('stickers', []))
                                            listing['pattern'] = found_asset_data.get('pattern')
                                            listing['float_value'] = found_asset_data.get('float_value')
                                            listing['stickers'] = found_asset_data.get('stickers', [])
                                            log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Связаны данные для listing_id={listing_id}: наклеек={stickers_count}, pattern={found_asset_data.get('pattern')}, float={found_asset_data.get('float_value')}")
                                        else:
                                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: НЕ СВЯЗАНЫ данные для listing_id={listing_id}, asset_id={asset_id} - наклейки будут пустыми")
                        
                        # Обрабатываем каждый лот и проверяем фильтры
                        for listing in page_listings:
                            listing_price = listing.get('price', 0.0)
                            listing_id = listing.get('listing_id')
                            listing_pattern = listing.get('pattern')
                            listing_float = listing.get('float_value')
                            stickers = listing.get('stickers', [])
                            inspect_link = listing.get('inspect_link')
                            
                            # Создаем ParsedItemData
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
                                total_stickers_price=0.0,
                                item_name=hash_name,
                                item_price=listing_price,
                                inspect_links=[inspect_link] if inspect_link else [],
                                item_type=item_type,
                                is_stattrak=is_stattrak,
                                listing_id=listing_id
                            )
                            
                            # РАННЯЯ ПРОВЕРКА ПАТТЕРНА: если паттерн известен и не подходит - пропускаем сразу
                            # Это предотвращает обработку предметов, которые точно не пройдут фильтры
                            if listing_pattern is not None and filters.pattern_list:
                                target_patterns = filters.pattern_list.patterns if filters.pattern_list else []
                                if target_patterns:
                                    # Нормализуем паттерн (для keychain берем остаток от деления на 1000)
                                    normalized_pattern = listing_pattern % 1000 if listing_pattern > 999 else listing_pattern
                                    if normalized_pattern not in target_patterns:
                                        log("debug", f"    ⏭️ Воркер {worker_id}, страница {page_num}: Пропускаем предмет с паттерном {listing_pattern} (нормализован: {normalized_pattern}), не в списке {target_patterns}")
                                        continue
                            
                            # Проверяем фильтры без сохранения в БД
                            item_dict = {
                                "sell_price_text": f"${listing_price:.2f}",
                                "asset_description": {"market_hash_name": hash_name},
                                "name": hash_name
                            }
                            matches = await parser.filter_service.matches_filters(item_dict, filters, parsed_data)
                            if matches:
                                # ВАЖНО: Обрабатываем результат СРАЗУ после нахождения, а не после всех страниц
                                # Это гарантирует, что уведомления отправляются немедленно
                                if task and db_manager:
                                    log("info", f"    🔄 Воркер {worker_id}: Найден подходящий предмет, обрабатываем СРАЗУ (task={task.id}, db_manager={db_manager is not None})")
                                    try:
                                        # Создаем отдельную сессию БД для этого воркера
                                        worker_db_session = await db_manager.get_session()
                                        try:
                                            from .process_results import process_item_result
                                            
                                            log("info", f"    📝 Воркер {worker_id}: Вызываем process_item_result для немедленной обработки...")
                                            # Обрабатываем результат сразу (сохранение в БД + отправка уведомления)
                                            saved = await process_item_result(
                                                parser=parser,
                                                task=task,
                                                parsed_data=parsed_data,
                                                filters=filters,
                                                db_session=worker_db_session,
                                                redis_service=redis_service,
                                                task_logger=task_logger
                                            )
                                            
                                            if saved:
                                                log("info", f"    │ ✅✅✅ ВСЕ ФИЛЬТРЫ ПРОЙДЕНЫ И ПРЕДМЕТ СОХРАНЕН СРАЗУ!")
                                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                                                # ВАЖНО: НЕ добавляем в page_matching_listings, если результат уже обработан
                                                # Это предотвратит повторную обработку через ResultsProcessorService
                                                # Уведомление уже отправлено в process_item_result
                                                log("info", f"    ℹ️ Предмет уже обработан и уведомление отправлено, не добавляем в список для повторной обработки")
                                            else:
                                                log("info", f"    │ ❌ НЕ ПРОШЕЛ ФИЛЬТРЫ ИЛИ УЖЕ СУЩЕСТВУЕТ В БД")
                                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                                        finally:
                                            # Закрываем сессию воркера
                                            await worker_db_session.close()
                                    except Exception as process_error:
                                        error_msg = str(process_error)[:200]
                                        log("error", f"    ⚠️ Ошибка при обработке результата: {type(process_error).__name__}: {error_msg}")
                                        import traceback
                                        log("error", f"    Traceback: {traceback.format_exc()}")
                                        # В случае ошибки все равно добавляем в список для совместимости
                                        page_matching_listings.append(parsed_data)
                                else:
                                    # Если нет task или db_manager, просто добавляем в список (старая логика)
                                    log("warning", f"    ⚠️ Воркер {worker_id}: Нет task или db_manager (task={task is not None}, db_manager={db_manager is not None}), используем старую логику")
                                    page_matching_listings.append(parsed_data)
                        
                        parse_time = (datetime.now() - parse_start).total_seconds()
                        log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Парсинг завершен за {parse_time:.2f}с, найдено {len(page_matching_listings)} подходящих из {len(page_listings)} лотов")
                        
                        # Сохраняем результаты
                        save_start = datetime.now()
                        task_stages[page_num] = "сохранение_результатов"
                        async with lock:
                            # Находим индекс страницы в исходном списке
                            page_idx = page_num - 1
                            if 0 <= page_idx < len(results):
                                results[page_idx] = page_matching_listings
                            completed_pages += 1
                            total_time = (datetime.now() - task_start_time).total_seconds()
                            log("info", f"    ✅ Воркер {worker_id}, страница {page_num}/{total_pages} завершена: Найдено {len(page_listings)} лотов, подходящих {len(page_matching_listings)} (завершено страниц: {completed_pages}/{len(pages_to_fetch)}, время: {total_time:.2f}с)")
                        
                        save_time = (datetime.now() - save_start).total_seconds()
                        log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Результаты сохранены за {save_time:.2f}с")
                        
                        # Отмечаем прокси как успешно использованный
                        proxy_mark_start = datetime.now()
                        if parser.proxy_manager and page_proxy:
                            await parser.proxy_manager.mark_proxy_used(page_proxy, success=True)
                        proxy_mark_time = (datetime.now() - proxy_mark_start).total_seconds()
                        log("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} отмечен как успешный за {proxy_mark_time:.2f}с")
                        
                        # Успешно обработали страницу, выходим из цикла retry
                        task_stages[page_num] = "завершено"
                        if page_num in task_start_times:
                            del task_start_times[page_num]
                        if page_num in task_stages:
                            del task_stages[page_num]
                        break
                        
                    except asyncio.TimeoutError:
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                pass
                        timeout_time = (datetime.now() - task_start_time).total_seconds()
                        current_stage = task_stages.get(page_num, "неизвестно")
                        log("error", f"    ⏱️ Воркер {worker_id}, страница {page_num}: ТАЙМАУТ запроса (60с) на этапе '{current_stage}' после {timeout_time:.2f}с работы (попытка {attempt + 1}/{max_retries})")
                        
                        if attempt < max_retries - 1:
                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Таймаут запроса, повторяем с другим прокси...")
                            if page_proxy and parser.proxy_manager:
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Timeout")
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Таймаут запроса после {max_retries} попыток, общее время: {timeout_time:.2f}с")
                            log("error", f"    📋 ДЕТАЛИ ОШИБКИ: Воркер {worker_id}, страница {page_num}, этап: {current_stage}, прокси: {page_proxy.id if page_proxy else 'None'}, время: {timeout_time:.2f}с")
                            if page_proxy and parser.proxy_manager:
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Timeout")
                            async with lock:
                                completed_pages += 1
                            if page_num in task_start_times:
                                del task_start_times[page_num]
                            if page_num in task_stages:
                                del task_stages[page_num]
                            break
                    except Exception as e:
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                pass
                        error_msg = str(e)[:200]
                        current_stage = task_stages.get(page_num, "неизвестно")
                        error_time = (datetime.now() - task_start_time).total_seconds()
                        log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: ОШИБКА на этапе '{current_stage}' после {error_time:.2f}с: {type(e).__name__}: {error_msg} (попытка {attempt + 1}/{max_retries})")
                        import traceback
                        log("error", f"    📋 Traceback: {traceback.format_exc()[:500]}")
                        
                        if attempt < max_retries - 1:
                            log("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Ошибка, повторяем с другим прокси...")
                            if page_proxy and parser.proxy_manager:
                                is_429 = "429" in error_msg or "Too Many Requests" in error_msg
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error=error_msg, is_429_error=is_429)
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            log("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Ошибка после {max_retries} попыток: {type(e).__name__}: {error_msg}")
                            log("error", f"    📋 ДЕТАЛИ ОШИБКИ: Воркер {worker_id}, страница {page_num}, этап: {current_stage}, прокси: {page_proxy.id if page_proxy else 'None'}, ошибка: {error_msg}")
                            if page_proxy and parser.proxy_manager:
                                is_429 = "429" in error_msg or "Too Many Requests" in error_msg
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error=error_msg, is_429_error=is_429)
                            async with lock:
                                completed_pages += 1
                            if page_num in task_start_times:
                                del task_start_times[page_num]
                            if page_num in task_stages:
                                del task_stages[page_num]
                            break
                    finally:
                        # Закрываем клиенты
                        if temp_parser:
                            try:
                                await temp_parser.close()
                            except:
                                pass
                        if temp_client:
                            try:
                                await temp_client.close()
                            except:
                                pass
                
            except Exception as e:
                error_msg = str(e)[:200]
                log("error", f"    ❌ Воркер {worker_id}: КРИТИЧЕСКАЯ ОШИБКА при обработке страницы: {type(e).__name__}: {error_msg}")
                import traceback
                log("error", f"    📋 Traceback: {traceback.format_exc()}")
                if page_num:
                    async with lock:
                        completed_pages += 1
                    if page_num in task_start_times:
                        del task_start_times[page_num]
                    if page_num in task_stages:
                        del task_stages[page_num]
        
        log("info", f"    🏁 Воркер {worker_id}: Завершил работу (обработано страниц: {pages_processed})")
    
    # Запускаем воркеры параллельно
    log("info", f"🚀 Запускаем {max_concurrent} воркеров для обработки страниц из Redis очереди...")
    
    workers = [
        asyncio.create_task(process_page_from_queue(worker_id))
        for worker_id in range(1, max_concurrent + 1)
    ]
    
    # Ждем завершения всех воркеров
    try:
        await asyncio.gather(*workers, return_exceptions=True)
    except Exception as e:
        log("error", f"❌ Ошибка при выполнении воркеров: {e}")
        import traceback
        log("error", f"   Traceback: {traceback.format_exc()}")
    
    # Очищаем очередь после завершения
    try:
        await redis_service.delete(queue_key)
        log("info", f"🗑️ Очередь {queue_key} очищена")
    except Exception as e:
        log("warning", f"⚠️ Не удалось очистить очередь {queue_key}: {e}")
    
    # Проверяем зависшие задачи (если есть)
    if task_start_times:
        now = datetime.now()
        hung_pages = []
        for page_num, start_time in task_start_times.items():
            elapsed = (now - start_time).total_seconds()
            if elapsed > 300:  # 5 минут
                current_stage = task_stages.get(page_num, "неизвестно")
                hung_pages.append((page_num, elapsed, current_stage))
        
        if hung_pages:
            log("error", f"⚠️ Обнаружены зависшие страницы:")
            for page_num, elapsed, stage in hung_pages:
                log("error", f"   📋 Страница {page_num}: зависла на этапе '{stage}' уже {elapsed:.1f}с")
    
    # Собираем результаты в правильном порядке
    # ВАЖНО: Если результаты уже обработаны в параллельном парсере (сразу после нахождения),
    # то page_matching_listings будет пустым, и мы не вернем их для повторной обработки
    for page_matching_listings in results:
        if page_matching_listings:
            matching_listings.extend(page_matching_listings)
    
    log("info", f"📊 Параллельный парсинг завершен: проверено {completed_pages}/{len(pages_to_fetch)} страниц, найдено {len(matching_listings)} подходящих лотов")
    if len(matching_listings) == 0:
        log("info", f"ℹ️ Список результатов пуст - все найденные предметы уже обработаны сразу (уведомления отправлены)")
    
    return matching_listings
