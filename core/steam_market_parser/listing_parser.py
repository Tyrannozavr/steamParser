"""
Модуль для парсинга лотов.
Отвечает за парсинг отдельных лотов и страниц предметов.
"""
import asyncio
from typing import Optional, List
from loguru import logger

try:
    from parser_api.app import parser
except ImportError:
    # Если parser_api недоступен (например, нет fastapi), создаем заглушку
    parser = None
    logger.warning("⚠️ parser_api.app недоступен, некоторые функции могут не работать")

from parsers import ItemPageParser, detect_item_type, InspectLinkParser
from ..models import ParsedItemData, SearchFilters
from .logger_utils import log_both
from .item_page_parser import parse_item_page
from .listing_page_parser import parse_listing_page


class ListingParser:
    """
    Класс для парсинга лотов.
    Принимает ссылку на парсер для использования его методов.
    """
    
    def __init__(self, parser):
        """
        Инициализация парсера лотов.
        
        Args:
            parser: Экземпляр SteamMarketParser для использования его методов
        """
        self.parser = parser
    
    async def parse_all_listings(
        self,
        appid: int,
        hash_name: str,
        filters: SearchFilters,
        target_patterns: Optional[set] = None,
        task_logger = None,
        task = None,
        db_session = None,
        redis_service = None
    ) -> list[ParsedItemData]:
        """
        Парсит ВСЕ лоты на ВСЕХ страницах предмета и возвращает список всех подходящих лотов.
        Каждый лот проверяется по цене и паттерну.
        Поддерживает пагинацию - парсит все страницы, если их несколько.
        Обрабатывает результаты сразу после парсинга каждой страницы (фильтрация и отправка уведомлений).

        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            filters: Фильтры для проверки лотов
            target_patterns: Опциональный set паттернов для фильтрации
            task_logger: Опциональный логгер для задачи
            task: Задача мониторинга (для сохранения результатов)
            db_session: Сессия БД (для сохранения результатов)
            redis_service: Сервис Redis (для отправки уведомлений)

        Returns:
            Список ParsedItemData для всех подходящих лотов
        """
        parser = self.parser
        
        # Устанавливаем task, db_session, redis_service в parser для доступа из process_item_result
        if task:
            parser._current_task = task
        if db_session:
            parser._current_db_session = db_session
        if redis_service:
            parser._current_redis_service = redis_service
        
        # Используем log_both из logger_utils
        def log(level: str, message: str):
            log_both(level, message, task_logger)
        
        log("info", f"    🚀 parse_all_listings: hash_name={hash_name}, target_patterns={target_patterns}")
        
        matching_listings = []
        all_listings = []
        
        # Используем API /render/ для получения паттерна и float напрямую из JSON
        log("info", f"    🚀 Используем API /render/ для быстрого получения паттерна и float из JSON")
        
        # ВАЖНО: Максимальное значение count для render endpoint = 20
        listings_per_page = 20
        MAX_PAGES_TO_PARSE = 100
        start = 0
        page_num = 1
        total_count = None
        
        # Словарь для хранения данных из assets
        assets_data_map = {}
        
        # Периодическая проверка прокси (раз в 5 минут)
        import time
        last_proxy_check_time = time.time()
        PROXY_CHECK_INTERVAL = 300  # 5 минут
        
        # Определяем, использовать ли параллельный парсинг
        use_parallel = False
        active_proxies_count = 0
        if parser.proxy_manager:
            available_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=False)
            active_proxies_count = len(available_proxies) if available_proxies else 0
            # Используем параллельный парсинг, если есть 3+ прокси
            if active_proxies_count >= 3:
                use_parallel = True
                log("info", f"    🚀 Параллельный парсинг страниц лотов: используем {active_proxies_count} прокси")
        
        # ВАЖНО: Получаем total_count с первой страницы ДО проверки параллельного парсинга
        # Это нужно для того, чтобы знать, сколько страниц парсить, и активировать параллельный парсинг
        if total_count is None:
            # Получаем total_count с первой страницы
            first_page_proxy = None
            if parser.proxy_manager:
                first_page_proxy = await parser.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
            
            if first_page_proxy:
                try:
                    from ..steam_http_client import SteamHttpClient
                    temp_client = SteamHttpClient(proxy=first_page_proxy.url, timeout=30, proxy_manager=parser.proxy_manager)
                    await temp_client._ensure_client()
                    try:
                        temp_parser = parser.__class__(proxy=first_page_proxy.url, timeout=30, redis_service=parser.redis_service, proxy_manager=parser.proxy_manager)
                        await temp_parser._ensure_client()
                        first_page_data = await temp_parser._fetch_render_api(appid, hash_name, start=0, count=listings_per_page)
                        await temp_parser.close()
                        if first_page_data:
                            total_count = first_page_data.get('total_count')
                            if total_count:
                                log("info", f"    📊 Всего лотов: {total_count}")
                                if parser.proxy_manager:
                                    await parser.proxy_manager.mark_proxy_used(first_page_proxy, success=True)
                    finally:
                        await temp_client.close()
                except Exception as e:
                    log("warning", f"    ⚠️ Не удалось получить total_count с первой страницы: {e}")
            else:
                # Если нет прокси, пробуем через основной парсер
                try:
                    first_page_data = await parser._fetch_render_api(appid, hash_name, start=0, count=listings_per_page)
                    if first_page_data:
                        total_count = first_page_data.get('total_count')
                        if total_count:
                            log("info", f"    📊 Всего лотов: {total_count}")
                except Exception as e:
                    log("warning", f"    ⚠️ Не удалось получить total_count с первой страницы через основной парсер: {e}")
        
        # Если есть total_count и достаточно прокси - используем параллельный парсинг
        if use_parallel and total_count and total_count > listings_per_page:
            from .parallel_listing_parser import parse_listings_parallel
            # Получаем db_manager из parser, если доступен
            db_manager = getattr(parser, 'db_manager', None)
            if task_logger:
                task_logger.info(f"🔍 ListingParser: Используем параллельный парсинг (task={task.id if task else None}, db_manager={db_manager is not None})")
            matching_listings = await parse_listings_parallel(
                parser, appid, hash_name, filters, target_patterns,
                listings_per_page, total_count, active_proxies_count,
                task_logger, task, db_session, redis_service, db_manager
            )
            return matching_listings
        
        # Последовательный парсинг страниц (fallback или если мало прокси)
        # Парсим страницы через API /render/
        while page_num <= MAX_PAGES_TO_PARSE:
            # Проверяем, активна ли задача (для немедленной остановки)
            if task:
                # Обновляем задачу из БД для проверки актуального статуса
                try:
                    from sqlalchemy import select
                    from core import MonitoringTask
                    if db_session:
                        result = await db_session.execute(
                            select(MonitoringTask).where(MonitoringTask.id == task.id)
                        )
                        db_task = result.scalar_one_or_none()
                        if db_task and not db_task.is_active:
                            log("info", f"🛑 Задача {task.id} деактивирована, останавливаем парсинг")
                            break
                except Exception as e:
                    log("warning", f"⚠️ Ошибка при проверке статуса задачи: {e}")
            
            if total_count is not None:
                total_pages = (total_count + listings_per_page - 1) // listings_per_page
                log("info", f"📋 Страница {page_num} из {total_pages}: Обрабатываем лоты...")
            else:
                log("info", f"📋 Страница {page_num}: Обрабатываем лоты... (всего лотов пока неизвестно)")
            
            # Пробуем получить рабочий прокси
            page_proxy = None
            render_data = None
            
            log("info", f"    🔍 Страница {page_num}: Начинаем поиск рабочего прокси...")
            
            # Периодическая проверка прокси (раз в 5 минут), если нет доступных
            if parser.proxy_manager:
                current_time = time.time()
                time_since_check = current_time - last_proxy_check_time
                
                available_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=False)
                
                # Если прошло больше 5 минут и нет доступных прокси - обновляем список
                if time_since_check > PROXY_CHECK_INTERVAL and (not available_proxies or len(available_proxies) == 0):
                    log("info", f"    🔄 Страница {page_num}: Прошло {time_since_check:.0f} сек с последней проверки, обновляем список прокси...")
                    last_proxy_check_time = current_time
                    available_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=True)
                    log("info", f"    📊 Страница {page_num}: После обновления доступно {len(available_proxies) if available_proxies else 0} прокси")
            
            if parser.proxy_manager:
                available_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=False)
                
                if not available_proxies:
                    log("warning", f"    ⚠️ Страница {page_num}: Нет доступных прокси, пробуем обновить список")
                    available_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=True)
                
                max_proxy_attempts = len(available_proxies) if available_proxies else 3  # Уменьшено с 20 до 3, чтобы не зависать
                log("info", f"    📊 Страница {page_num}: Доступно {len(available_proxies) if available_proxies else 0} прокси, максимум попыток: {max_proxy_attempts}")
                
                for attempt in range(max_proxy_attempts):
                    log("info", f"    🔄 Страница {page_num}: Попытка {attempt + 1}/{max_proxy_attempts} получить рабочий прокси...")
                    
                    if available_proxies and len(available_proxies) > 0:
                        page_proxy = available_proxies[attempt % len(available_proxies)]
                        log("info", f"    🔄 Страница {page_num}: Попытка {attempt + 1}/{max_proxy_attempts}, пробуем прокси ID={page_proxy.id}")
                    else:
                        log("info", f"    🔄 Страница {page_num}: Попытка {attempt + 1} - получаем прокси через get_next_proxy (precheck={attempt == 0})...")
                        if parser and parser.proxy_manager:
                            page_proxy = await parser.proxy_manager.get_next_proxy(force_refresh=(attempt == 0), precheck=(attempt == 0))
                        else:
                            page_proxy = None
                        if not page_proxy:
                            log("warning", f"    ⚠️ Страница {page_num}: Попытка {attempt + 1} - не удалось получить прокси")
                            
                            # НЕ запускаем проверку всех прокси - это может зависнуть
                            # Просто ждем немного и пробуем еще раз, или пропускаем страницу
                            if attempt < max_proxy_attempts - 1:
                                log("info", f"    ⏳ Страница {page_num}: Ожидаем 2 секунды перед следующей попыткой...")
                                await asyncio.sleep(2)
                            else:
                                # Все попытки исчерпаны - пропускаем страницу
                                log("warning", f"    ⏭️ Страница {page_num}: Все {max_proxy_attempts} попыток исчерпаны, пропускаем страницу")
                            continue
                    
                    log("debug", f"    ⏳ Страница {page_num}: Задержка перед запросом...")
                    if parser:
                        await parser._random_delay(min_seconds=1.0, max_seconds=2.0)
                    else:
                        await asyncio.sleep(1.5)  # Fallback задержка
                    
                    log("info", f"    🚀 Страница {page_num}: Пробуем загрузить данные через прокси ID={page_proxy.id}...")
                    try:
                        from ..steam_http_client import SteamHttpClient
                        temp_client = SteamHttpClient(proxy=page_proxy.url, timeout=30, proxy_manager=parser.proxy_manager)
                        await temp_client._ensure_client()
                        try:
                            # Используем класс парсера из parser
                            temp_parser = parser.__class__(proxy=page_proxy.url, timeout=30, redis_service=parser.redis_service, proxy_manager=parser.proxy_manager)
                            await temp_parser._ensure_client()
                            render_data = await temp_parser._fetch_render_api(appid, hash_name, start=start, count=listings_per_page)
                            await temp_parser.close()
                            
                            if render_data is not None:
                                log("info", f"    ✅ Страница {page_num}: Успешно загружена через прокси ID={page_proxy.id} (попытка {attempt + 1})")
                                if parser.proxy_manager:
                                    await parser.proxy_manager.mark_proxy_used(page_proxy, success=True)
                                break
                            else:
                                log("warning", f"    ⚠️ Страница {page_num}: Прокси ID={page_proxy.id} не вернул данные, пробуем следующий")
                                if parser.proxy_manager:
                                    await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Не удалось загрузить данные")
                        finally:
                            await temp_client.close()
                    except Exception as e:
                        log("warning", f"    ⚠️ Страница {page_num}: Ошибка с прокси ID={page_proxy.id}: {type(e).__name__}, пробуем следующий")
                        if parser.proxy_manager:
                            await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error=str(e))
                        continue
                
                if render_data is None:
                    log("warning", f"    ⚠️ Страница {page_num}: Не удалось загрузить через все доступные прокси ({max_proxy_attempts} попыток)")
                    log("info", f"    ⏳ Страница {page_num}: Все прокси недоступны, ожидаем появления доступных прокси...")
                    
                    # Цикл ожидания доступных прокси (не пропускаем страницу!)
                    wait_cycle = 0
                    max_wait_cycles = 10000  # Максимум циклов ожидания (практически бесконечно)
                    check_interval_cycles = 60  # Проверяем прокси каждые 60 циклов (5 минут при задержке 5 сек)
                    
                    while render_data is None and wait_cycle < max_wait_cycles:
                        wait_cycle += 1
                        current_time = time.time()
                        time_since_check = current_time - last_proxy_check_time
                        
                        # Проверяем доступность прокси каждые 5 минут
                        should_check = (wait_cycle % check_interval_cycles == 0) or (time_since_check > PROXY_CHECK_INTERVAL)
                        
                        if should_check:
                            log("info", f"    🔄 Страница {page_num}: Проверяем доступность прокси (цикл ожидания {wait_cycle}, прошло {time_since_check:.0f} сек)...")
                            last_proxy_check_time = current_time
                            available_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=True)
                            log("info", f"    📊 Страница {page_num}: После обновления доступно {len(available_proxies) if available_proxies else 0} прокси")
                            
                            # Если появились доступные прокси - пробуем снова
                            if available_proxies and len(available_proxies) > 0:
                                log("info", f"    ✅ Страница {page_num}: Появились доступные прокси, пробуем загрузить страницу...")
                                # Пробуем получить прокси и загрузить страницу
                                page_proxy = await parser.proxy_manager.get_next_proxy(force_refresh=False, skip_delay=True)
                                if page_proxy:
                                    try:
                                        from ..steam_http_client import SteamHttpClient
                                        temp_client = SteamHttpClient(proxy=page_proxy.url, timeout=30, proxy_manager=parser.proxy_manager)
                                        await temp_client._ensure_client()
                                        try:
                                            temp_parser = parser.__class__(proxy=page_proxy.url, timeout=30, redis_service=parser.redis_service, proxy_manager=parser.proxy_manager)
                                            await temp_parser._ensure_client()
                                            render_data = await temp_parser._fetch_render_api(appid, hash_name, start=start, count=listings_per_page)
                                            await temp_parser.close()
                                            
                                            if render_data is not None:
                                                log("info", f"    ✅ Страница {page_num}: Успешно загружена через прокси ID={page_proxy.id} после ожидания")
                                                if parser.proxy_manager:
                                                    await parser.proxy_manager.mark_proxy_used(page_proxy, success=True)
                                                break  # Выходим из цикла ожидания
                                            else:
                                                log("warning", f"    ⚠️ Страница {page_num}: Прокси ID={page_proxy.id} не вернул данные, продолжаем ожидание")
                                                if parser.proxy_manager:
                                                    await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Не удалось загрузить данные")
                                        finally:
                                            await temp_client.close()
                                    except Exception as e:
                                        log("warning", f"    ⚠️ Страница {page_num}: Ошибка с прокси ID={page_proxy.id if page_proxy else 'None'}: {type(e).__name__}, продолжаем ожидание")
                                        if parser.proxy_manager and page_proxy:
                                            await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error=str(e))
                        
                        # Ждем 5 секунд перед следующей проверкой
                        await asyncio.sleep(5.0)
                    
                    # Если после всех циклов ожидания все еще нет данных - это критическая ошибка
                    if render_data is None:
                        log("error", f"    ❌ Страница {page_num}: Критическая ошибка - не удалось загрузить после {wait_cycle} циклов ожидания")
                        log("error", f"    ⚠️ Пропускаем страницу {page_num} из-за критической ошибки")
                        start += listings_per_page
                        page_num += 1
                        continue
            else:
                log("warning", f"    ⚠️ Страница {page_num}: Нет proxy_manager, используем основной парсер")
                await parser._random_delay(min_seconds=1.0, max_seconds=2.0)
                render_data = await parser._fetch_render_api(appid, hash_name, start=start, count=listings_per_page)
                
                if render_data is None:
                    log("warning", f"    ⚠️ Не удалось загрузить страницу {page_num} через основной парсер")
                    start += listings_per_page
                    page_num += 1
                    continue
            
            # Обновляем total_count из первой страницы
            if total_count is None:
                total_count = render_data.get('total_count')
                if total_count:
                    log("info", f"    📊 Всего лотов: {total_count}")
                    log("info", f"    🔍 DEBUG: total_count установлен в {total_count} на странице {page_num}")
            else:
                current_total = render_data.get('total_count')
                if current_total and current_total != total_count:
                    log("warning", f"    ⚠️ total_count изменился: было {total_count}, стало {current_total}, обновляем")
                    total_count = current_total
            
            # Извлекаем данные из assets
            log("info", f"    🚀 НАЧИНАЕМ ПАРСИНГ ASSETS (страница {page_num}, start={start})")
            
            if 'assets' in render_data and '730' in render_data['assets']:
                app_assets = render_data['assets']['730']
                log("info", f"    📊 Найдено {len(app_assets)} контекстов в assets")
                
                # Логируем все asset_id для отладки
                all_asset_ids = []
                for contextid, items in app_assets.items():
                    all_asset_ids.extend(items.keys())
                log("info", f"    📋 Все asset_id на странице {page_num}: {sorted([str(aid) for aid in all_asset_ids])[:20]}... (всего {len(all_asset_ids)})")
                for contextid, items in app_assets.items():
                    for itemid, item in items.items():
                        itemid = str(itemid)
                        pattern = None
                        float_value = None
                        stickers = []
                        
                        # Парсим asset_properties для паттерна и float
                        if 'asset_properties' in item:
                            props = item['asset_properties']
                            log("info", f"    🔍 Asset {itemid}: Найдено {len(props)} свойств в asset_properties")
                            
                            if page_num == 1:
                                log("info", f"    📋 ДЕТАЛЬНАЯ ИНФОРМАЦИЯ для asset {itemid} (страница 1):")
                                log("info", f"       asset_properties (RAW): {props}")
                                for idx, prop in enumerate(props):
                                    log("info", f"       [{idx}] propertyid={prop.get('propertyid')}, keys={list(prop.keys())}, values={prop}")
                            
                            for prop in props:
                                prop_id = prop.get('propertyid')
                                # propertyid=1 для скинов, propertyid=3 для брелков
                                # Проверяем оба, но не перезаписываем, если паттерн уже найден
                                if (prop_id == 1 or prop_id == 3) and pattern is None:
                                    pattern = prop.get('int_value')
                                    log("info", f"    ✅ Asset {itemid}: Найден паттерн (propertyid={prop_id}): {pattern} (тип: {type(pattern).__name__})")
                                    log("info", f"       RAW prop: {prop}")
                                    if pattern == 896 or pattern == "896" or str(pattern) == "896":
                                        log("info", f"    🔥 НАЙДЕН ПАТТЕРН 896 в asset {itemid} на странице {page_num} (start={start})!")
                                    if pattern == 142 or pattern == "142" or str(pattern) == "142":
                                        log("info", f"    🔥🔥🔥 НАЙДЕН ПАТТЕРН 142 в asset {itemid} на странице {page_num} (start={start})!")
                                        log("info", f"       RAW prop для паттерна 142: {prop}")
                                        log("info", f"       float_value в этом asset: {float_value}")
                                elif prop_id == 2:
                                    float_value_raw = prop.get('float_value')
                                    try:
                                        float_value = float(float_value_raw) if float_value_raw is not None else None
                                    except (ValueError, TypeError):
                                        float_value = float_value_raw
                                        log("warning", f"    ⚠️ Asset {itemid}: Не удалось преобразовать float_value {float_value_raw} к float")
                                    log("info", f"    ✅ Asset {itemid}: Найден float (propertyid=2): {float_value_raw} -> {float_value} (тип: {type(float_value).__name__})")
                                    
                                    if float_value and 0.22 <= float_value <= 0.26:
                                        log("info", f"    🎯🎯🎯 НАЙДЕН FLOAT в диапазоне 0.22-0.26: {float_value} (тип: {type(float_value).__name__})")
                        else:
                            log("warning", f"    ⚠️ Asset {itemid}: Нет asset_properties")
                            if page_num == 1:
                                log("warning", f"    📋 ДЕТАЛЬНАЯ ИНФОРМАЦИЯ для asset {itemid} (страница 1, нет asset_properties): keys={list(item.keys())}")
                                log("warning", f"       Полный item (первые 500 символов): {str(item)[:500]}")
                        
                        # Парсим descriptions для наклеек
                        if 'descriptions' in item:
                            log("info", f"    🔍 ПАРСИНГ DESCRIPTIONS: Найдено {len(item['descriptions'])} descriptions для item {itemid}")
                            for desc in item['descriptions']:
                                desc_name = desc.get('name', '')
                                log("info", f"    📝 Description: name='{desc_name}', value_length={len(desc.get('value', ''))}")
                                if desc_name == 'sticker_info':
                                    sticker_html = desc.get('value', '')
                                    log("info", f"    🎯 Найден sticker_info для item {itemid}, HTML длина: {len(sticker_html)}")
                                    if sticker_html:
                                        from bs4 import BeautifulSoup
                                        from ..models import StickerInfo
                                        sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                        images = sticker_soup.find_all('img')
                                        log("info", f"    🖼️ Найдено {len(images)} изображений наклеек")
                                        
                                        # Парсим наклейки из title атрибутов изображений
                                        # Одинаковые наклейки должны парситься (у них разные позиции)
                                        # Используем множество для отслеживания наклеек, найденных из title (чтобы не дублировать с текстом)
                                        found_sticker_names_from_title = set()
                                        
                                        for idx, img in enumerate(images):
                                            if idx >= 5:
                                                log("warning", f"    ⚠️ Пропускаем изображение {idx}: достигнут лимит наклеек (максимум 5)")
                                                break
                                            
                                            title = img.get('title', '')
                                            log("debug", f"    🏷️ Изображение {idx}: title='{title}'")
                                            if title and 'Sticker:' in title:
                                                sticker_name = title.replace('Sticker: ', '').strip()
                                                if sticker_name and len(sticker_name) > 3:
                                                    # Одинаковые наклейки должны парситься (у них разные позиции)
                                                    log("info", f"    ✅ Найдена наклейка из title: {sticker_name} (позиция {idx})")
                                                    stickers.append(StickerInfo(
                                                        position=idx,
                                                        name=sticker_name,
                                                        wear=sticker_name,
                                                        price=None
                                                    ))
                                                    found_sticker_names_from_title.add(sticker_name)
                                        
                                        # Парсим из текста (только если наклейка еще не была найдена из title)
                                        text_content = sticker_soup.get_text()
                                        if 'Sticker:' in text_content:
                                            import re
                                            sticker_text_match = re.search(r'Sticker:\s*([^<]+)', text_content, re.IGNORECASE)
                                            if sticker_text_match:
                                                sticker_text = sticker_text_match.group(1).strip()
                                                log("debug", f"    📝 Текст наклеек: '{sticker_text}'")
                                                sticker_names_from_text = [s.strip() for s in sticker_text.split(',') if s.strip()]
                                                log("info", f"    📋 Найдено {len(sticker_names_from_text)} наклеек в тексте")
                                                
                                                # Добавляем наклейки из текста, избегая дубликатов с теми, что уже найдены из title
                                                for idx, sticker_name in enumerate(sticker_names_from_text):
                                                    if len(stickers) >= 5:
                                                        log("warning", f"    ⚠️ Достигнут лимит наклеек (5), пропускаем: {sticker_name}")
                                                        break
                                                    
                                                    if sticker_name and len(sticker_name) > 3:
                                                        # Проверяем, не была ли уже добавлена наклейка с таким же именем из title
                                                        # (избегаем дубликатов от парсинга title и текста)
                                                        if sticker_name in found_sticker_names_from_title:
                                                            log("debug", f"    ⏭️ Пропускаем дубликат наклейки {sticker_name} из текста (уже найдена из title)")
                                                            continue
                                                        
                                                        # Добавляем наклейку из текста на следующую свободную позицию
                                                        position = len(stickers)
                                                        if position > 4:
                                                            log("warning", f"    ⚠️ Пропускаем наклейку {sticker_name}: достигнут лимит позиций (максимум 5 наклеек)")
                                                            break
                                                        
                                                        log("info", f"    ✅ Добавлена наклейка из текста: {sticker_name} (позиция {position})")
                                                        stickers.append(StickerInfo(
                                                            position=position,
                                                            name=sticker_name,
                                                            wear=sticker_name,
                                                            price=None
                                                        ))
                                        
                                        log("info", f"    📊 Итого найдено {len(stickers)} наклеек для item {itemid}")
                                        break
                        else:
                            log("debug", f"    ❌ Нет descriptions для item {itemid}")
                        
                        # Сохраняем данные
                        if pattern is not None or float_value is not None or stickers:
                            if pattern is not None:
                                pattern_original = pattern
                                try:
                                    pattern = int(pattern)
                                    if pattern_original != pattern:
                                        log("info", f"    🔄 Паттерн преобразован: {pattern_original} (тип: {type(pattern_original).__name__}) -> {pattern} (тип: {type(pattern).__name__})")
                                except (ValueError, TypeError):
                                    log("warning", f"    ⚠️ Не удалось преобразовать паттерн в int: {pattern} (тип: {type(pattern).__name__})")
                                    pattern = None
                            
                            if float_value is not None:
                                float_original = float_value
                                try:
                                    float_value = float(float_value)
                                    if float_original != float_value:
                                        log("info", f"    🔄 Float преобразован: {float_original} (тип: {type(float_original).__name__}) -> {float_value} (тип: {type(float_value).__name__})")
                                except (ValueError, TypeError):
                                    log("warning", f"    ⚠️ Не удалось преобразовать float_value в float: {float_value} (тип: {type(float_value).__name__})")
                                    float_value = None
                            
                            assets_data_map[itemid] = {
                                'pattern': pattern,
                                'float_value': float_value,
                                'stickers': stickers,
                                'contextid': contextid
                            }
                            
                            log("info", f"    💾 СОХРАНЕНО В assets_data_map[{itemid}]:")
                            log("info", f"       - pattern: {pattern} (тип: {type(pattern).__name__})")
                            log("info", f"       - float_value: {float_value}")
                            log("info", f"       - stickers: {len(stickers)} штук")
                            log("info", f"       - contextid: {contextid}")
                            
                            if page_num == 1:
                                log("info", f"    🔥 КРИТИЧЕСКОЕ: Сохранен asset_id={itemid} с pattern={pattern} (тип: {type(pattern).__name__})")
                                log("info", f"       Полный объект: pattern={pattern}, float={float_value}, stickers={len(stickers)}, contextid={contextid}")
                        else:
                            log("info", f"    ❌ НЕ СОХРАНЕНО для item {itemid}: pattern={pattern}, float={float_value}, stickers={len(stickers)}")
            
            # Парсим HTML из results_html
            results_html = render_data.get('results_html', '')
            if results_html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(results_html, 'html.parser')
                parser_obj = ItemPageParser(results_html)
                page_listings = parser_obj.get_all_listings()
                
                # Связываем listing_id с данными из assets через listinginfo
                if 'listinginfo' in render_data:
                    listinginfo = render_data['listinginfo']
                    log("info", f"    📋 listinginfo содержит {len(listinginfo)} записей: {list(listinginfo.keys())[:10]}...")
                    
                    # Логируем все listing_id для отладки
                    all_listing_ids_from_html = [str(l.get('listing_id')) for l in page_listings if l.get('listing_id')]
                    log("info", f"    📋 Все listing_id из HTML на странице {page_num}: {all_listing_ids_from_html[:20]}... (всего {len(all_listing_ids_from_html)})")
                    
                    for listing in page_listings:
                        listing_id = listing.get('listing_id')
                        if listing_id:
                            listing_id = str(listing_id)
                        else:
                            log("warning", f"    ⚠️ Лот не имеет listing_id: {listing}")
                            continue
                        
                        if listing_id in listinginfo:
                            listing_data = listinginfo[listing_id]
                            if 'asset' in listing_data:
                                asset_info = listing_data['asset']
                                asset_id = asset_info.get('id')
                                if asset_id:
                                    asset_id = str(asset_id)
                                contextid = asset_info.get('contextid')
                                
                                log("info", f"    🔍 ПОИСК ДАННЫХ: listing_id={listing_id} (тип: {type(listing_id).__name__}), asset_id={asset_id} (тип: {type(asset_id).__name__})")
                                log("info", f"    📊 assets_data_map содержит {len(assets_data_map)} записей: {list(assets_data_map.keys())[:10]}...")
                                
                                found_asset_data = None
                                if asset_id in assets_data_map:
                                    found_asset_data = assets_data_map[asset_id]
                                    pattern_value = found_asset_data.get('pattern')
                                    log("info", f"    ✅ Найдено по точному asset_id: {asset_id}, паттерн={pattern_value} (тип: {type(pattern_value).__name__})")
                                else:
                                    log("warning", f"    ⚠️ Точный asset_id {asset_id} не найден, пробуем fallback поиск")
                                    
                                    if listing_id in assets_data_map:
                                        found_asset_data = assets_data_map[listing_id]
                                        log("info", f"    ✅ Найдено по listing_id как ключу: {listing_id}")
                                    else:
                                        assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                                        if len(assets_with_stickers) == 1:
                                            found_asset_data = list(assets_with_stickers.values())[0]
                                            found_key = list(assets_with_stickers.keys())[0]
                                            log("info", f"    ✅ Найдено единственное asset с наклейками: {found_key}")
                                        else:
                                            log("error", f"    ❌ Не удалось найти подходящие данные в assets_data_map")
                                
                                if found_asset_data:
                                    assets_data = found_asset_data
                                    pattern_value = assets_data.get('pattern')
                                    log("info", f"    ✅ НАЙДЕНЫ ДАННЫЕ для asset {asset_id}")
                                    log("info", f"       - pattern: {pattern_value} (тип: {type(pattern_value).__name__ if pattern_value is not None else 'None'})")
                                    log("info", f"       - float_value: {assets_data.get('float_value')}")
                                    log("info", f"       - stickers: {len(assets_data.get('stickers', []))} штук")
                                    
                                    listing['pattern'] = pattern_value
                                    listing['float_value'] = assets_data['float_value']
                                    
                                    stickers_from_assets = assets_data.get('stickers', [])
                                    log("info", f"    🎯 ПОЛУЧЕНЫ НАКЛЕЙКИ ИЗ assets_data: {len(stickers_from_assets)} штук")
                                    listing['stickers'] = stickers_from_assets
                                    log("info", f"    📤 УСТАНОВЛЕНО listing['stickers'] = {len(stickers_from_assets)} наклеек")
                                    
                                    listing['asset_id'] = asset_id
                                    listing['contextid'] = contextid
                                else:
                                    log("error", f"    ❌ Asset {asset_id} НЕ НАЙДЕН в assets_data_map!")
                                    log("error", f"       Доступные assets: {list(assets_data_map.keys())}")
                        else:
                            log("warning", f"    ⚠️ listing_id {listing_id} не найден в listinginfo (доступные ключи: {list(listinginfo.keys())[:5]}...)")
                            if len(assets_data_map) == 1:
                                found_asset_data = list(assets_data_map.values())[0]
                                if found_asset_data.get('stickers'):
                                    listing['stickers'] = found_asset_data.get('stickers', [])
                                    listing['pattern'] = found_asset_data.get('pattern')
                                    listing['float_value'] = found_asset_data.get('float_value')
                                    log("info", f"    ✅ Fallback: Установлены данные из единственного asset для listing_id={listing_id}")
                            elif len(assets_data_map) > 1:
                                assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                                if len(assets_with_stickers) == 1:
                                    found_asset_data = list(assets_with_stickers.values())[0]
                                    listing['stickers'] = found_asset_data.get('stickers', [])
                                    listing['pattern'] = found_asset_data.get('pattern')
                                    listing['float_value'] = found_asset_data.get('float_value')
                                    log("info", f"    ✅ Fallback: Установлены данные из единственного asset с наклейками для listing_id={listing_id}")
                
                # Проверяем, что наклейки установлены для всех лотов
                for listing in page_listings:
                    if 'stickers' not in listing or not listing.get('stickers'):
                        listing_id_check = listing.get('listing_id')
                        log("debug", f"    ⚠️ Лот {listing_id_check}: наклейки не установлены, проверяем fallback")
                        if len(assets_data_map) > 0:
                            assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                            if len(assets_with_stickers) == 1:
                                found_asset_data = list(assets_with_stickers.values())[0]
                                listing['stickers'] = found_asset_data.get('stickers', [])
                                if 'pattern' not in listing:
                                    listing['pattern'] = found_asset_data.get('pattern')
                                if 'float_value' not in listing:
                                    listing['float_value'] = found_asset_data.get('float_value')
                                log("info", f"    ✅ Fallback: Установлены наклейки для лота {listing_id_check} из единственного asset с наклейками")
                
                all_listings.extend(page_listings)
                
                # Проверяем фильтры сразу после парсинга каждой страницы
                log("info", f"    🔍 Проверяем фильтры для {len(page_listings)} лотов на странице {page_num}...")
                
                for listing_idx, listing in enumerate(page_listings):
                    listing_price = listing.get('price', 0.0)
                    listing_id = listing.get('listing_id')
                    listing_pattern = listing.get('pattern')
                    listing_float = listing.get('float_value')
                    stickers = listing.get('stickers', [])
                    inspect_link = listing.get('inspect_link')
                    
                    # Создаем ParsedItemData из данных лота
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
                    
                    # Создаем item dict для FilterService
                    item_dict = {
                        "sell_price_text": f"${listing_price:.2f}",
                        "asset_description": {"market_hash_name": hash_name},
                        "name": hash_name
                    }
                    
                    # Проверяем фильтры через FilterService
                    pattern_str = str(listing_pattern) if listing_pattern is not None else '?'
                    float_str = f"{listing_float:.6f}" if listing_float is not None else '?'
                    log("info", f"    ┌─ ЛОТ [{listing_idx + 1}/{len(page_listings)}] (страница {page_num}) ─────────────────────────────────────────────")
                    log("info", f"    │ 💰 Цена: ${listing_price:.2f} | 🎨 Паттерн: {pattern_str} | 🔢 Float: {float_str}")
                    log("info", f"    │ 📝 Название: {hash_name}")
                    
                    # РАННЯЯ ПРОВЕРКА ПАТТЕРНА: если есть фильтр по паттерну и паттерн не совпадает, пропускаем лот
                    # Это экономит время и ресурсы (не запрашиваем цены наклеек для неподходящих лотов)
                    if target_patterns is not None and listing_pattern is not None:
                        try:
                            pattern_int = int(listing_pattern)
                            if pattern_int not in target_patterns:
                                log("info", f"    │ ⏭️  ПАТТЕРН {pattern_int} НЕ СОВПАДАЕТ С ФИЛЬТРОМ {target_patterns}, ПРОПУСКАЕМ ЛОТ")
                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                                continue  # Пропускаем этот лот, не обрабатываем дальше
                        except (ValueError, TypeError):
                            # Если не удалось преобразовать паттерн в int, продолжаем обычную обработку
                            pass
                    
                    # Обрабатываем результат сразу через process_results
                    # Это включает проверку фильтров, запрос цен наклеек (если нужно) и отправку уведомлений
                    try:
                        from .process_results import process_item_result
                        
                        if task and db_session:
                            # Обрабатываем результат сразу
                            saved = await process_item_result(
                                parser=parser,
                                task=task,
                                parsed_data=parsed_data,
                                filters=filters,
                                db_session=db_session,
                                redis_service=redis_service,
                                task_logger=task_logger
                            )
                            
                            if saved:
                                log("info", f"    │ ✅✅✅ ВСЕ ФИЛЬТРЫ ПРОЙДЕНЫ И ПРЕДМЕТ СОХРАНЕН!")
                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                                matching_listings.append(parsed_data)
                                
                                if listing_pattern == 522:
                                    log("info", f"    🎯🎯🎯 ЛОТ С ПАТТЕРНОМ 522 ПРОШЕЛ ВСЕ ФИЛЬТРЫ И СОХРАНЕН!")
                                    log("info", f"       listing_id={listing_id}, price=${listing_price:.2f}, float={listing_float}, pattern={listing_pattern}")
                            else:
                                log("info", f"    │ ❌ НЕ ПРОШЕЛ ФИЛЬТРЫ ИЛИ УЖЕ СУЩЕСТВУЕТ В БД")
                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                        else:
                            # Fallback: используем старую логику проверки фильтров (без сохранения)
                            log("warning", f"    ⚠️ Task или db_session не доступны, используем только проверку фильтров")
                            matches = await parser.filter_service.matches_filters(item_dict, filters, parsed_data)
                            if matches:
                                log("info", f"    │ ✅✅✅ ВСЕ ФИЛЬТРЫ ПРОЙДЕНЫ (но не сохранено - нет task/db_session)")
                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                                matching_listings.append(parsed_data)
                            else:
                                log("info", f"    │ ❌ НЕ ПРОШЕЛ ФИЛЬТРЫ")
                                log("info", f"    └────────────────────────────────────────────────────────────────────")
                    except Exception as e:
                        log("error", f"    │ ❌ ОШИБКА при обработке результата: {e}")
                        log("info", f"    └────────────────────────────────────────────────────────────────────")
                        import traceback
                        log("debug", f"    Traceback: {traceback.format_exc()}")
                
                # Логируем прогресс
                if total_count is not None:
                    total_pages = (total_count + listings_per_page - 1) // listings_per_page
                    log("info", f"✅ Страница {page_num} из {total_pages}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                    if task_logger and task_logger.task_id:
                        task_logger.info(f"✅ Страница {page_num} из {total_pages}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                else:
                    log("info", f"✅ Страница {page_num}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                    if task_logger and task_logger.task_id:
                        task_logger.info(f"✅ Страница {page_num}: Найдено {len(page_listings)} лотов (всего: {len(all_listings)})")
                
                if page_proxy and parser.proxy_manager:
                    await parser.proxy_manager.mark_proxy_used(page_proxy, success=True)
                
                # Проверяем, есть ли еще страницы
                # ВАЖНО: Используем два критерия для определения конца:
                # 1. Если получено меньше listings_per_page лотов - это конец (надежнее, чем total_count)
                # 2. Если start + listings_per_page >= total_count - это тоже конец
                if len(page_listings) < listings_per_page:
                    log("info", f"    ✅ Достигли конца: получено {len(page_listings)} лотов, ожидалось {listings_per_page} (надежный критерий)")
                    break
                
                if total_count is not None:
                    if start + listings_per_page >= total_count:
                        log("info", f"    ✅ Достигли конца по total_count: start={start}, listings_per_page={listings_per_page}, total_count={total_count}")
                        # Но продолжаем, если получили полную страницу (на случай, если total_count изменился)
                        if len(page_listings) >= listings_per_page:
                            log("warning", f"    ⚠️ Получена полная страница ({len(page_listings)} лотов), но start + listings_per_page >= total_count. Продолжаем парсинг...")
                            # Не break, продолжаем парсинг
                        else:
                            break
                
                start += listings_per_page
                page_num += 1
                log("debug", f"    🔄 Переходим к следующей странице: start={start}, page_num={page_num}")
            else:
                log("warning", f"    ⚠️ Страница {page_num}: results_html пуст")
                break
        
        log("info", f"    📋 Всего найдено {len(all_listings)} лотов на всех страницах для проверки")
        log("info", f"    🔍 DEBUG: Начинаем проверку фильтров для {len(all_listings)} лотов")
        log("info", f"    🔍 DEBUG: matching_listings до проверки: {len(matching_listings)}")
        
        if not all_listings:
            log("error", f"    ⚠️ Не найдено лотов через API /render/, пробуем стандартный HTML парсинг")
            html = await parser._fetch_item_page(appid, hash_name)
            if html:
                parser_obj = ItemPageParser(html)
                page_listings = parser_obj.get_all_listings()
                all_listings.extend(page_listings)
                log("info", f"    📋 Fallback: Найдено {len(page_listings)} лотов через HTML парсинг")
            else:
                log("error", f"    ⚠️ Не удалось загрузить HTML страницу для fallback")
                return matching_listings
        
        log("info", f"    📊 Всего найдено {len(matching_listings)} подходящих лотов из {len(all_listings)}")
        return matching_listings
    
    async def parse_item_page(
        self,
        appid: int,
        hash_name: str,
        listing_id: Optional[str] = None,
        target_patterns: Optional[set] = None
    ) -> Optional[ParsedItemData]:
        """
        Парсит страницу предмета и извлекает детальные данные.
        Использует кэш Redis по listing_id для избежания повторных запросов.

        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            listing_id: Опциональный ID конкретного лота (если известен)
            target_patterns: Опциональный set паттернов для фильтрации

        Returns:
            ParsedItemData или None при ошибке
        """
        return await parse_item_page(
            self.parser,
            appid,
            hash_name,
            listing_id,
            target_patterns
        )

    async def parse_listing_page(
        self,
        appid: int,
        hash_name: str,
        listing_id: str
    ) -> Optional[ParsedItemData]:
        """
        Парсит страницу конкретного лота для получения данных (float, pattern, наклейки).
        Использует кэш Redis для избежания повторных запросов.
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            listing_id: ID лота
            
        Returns:
            ParsedItemData или None
        """
        parser = self.parser
        
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

