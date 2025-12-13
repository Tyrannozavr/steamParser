"""
Воркер для параллельного парсинга лотов.
Обрабатывает страницы из Redis очереди.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Callable

from ..models import SearchFilters, ParsedItemData
from .parallel_listing_utils import get_random_proxy
from .parallel_listing_page_parser import extract_assets_data, parse_page_listings, link_listings_with_assets
from .parallel_listing_listings_processor import process_page_listings


async def process_page_from_queue(
    worker_id: int,
    queue_key: str,
    redis_service,
    parser,
    appid: int,
    hash_name: str,
    filters: SearchFilters,
    task,
    db_manager,
    task_logger,
    redis_service_for_notifications,
    available_proxies: List,
    max_retries: int,
    total_pages: int,
    task_start_times: Dict[int, datetime],
    task_stages: Dict[int, str],
    log_func: Callable
):
    """
    Воркер: берет страницы из Redis очереди и обрабатывает их.
    
    ВАЖНО: Создает одну сессию БД для всего воркера (для всех страниц, которые он обработает).
    Это безопасно, потому что воркер обрабатывает страницы последовательно (не параллельно).
    Это более эффективно, чем создавать сессию для каждой страницы.
    
    Args:
        worker_id: ID воркера
        queue_key: Ключ Redis очереди
        redis_service: Сервис Redis для очереди
        parser: Экземпляр SteamMarketParser
        appid: ID приложения
        hash_name: Хэш-имя предмета
        filters: Фильтры поиска
        task: Задача мониторинга
        db_manager: Менеджер БД
        task_logger: Логгер задачи
        redis_service_for_notifications: Сервис Redis для уведомлений
        available_proxies: Список доступных прокси
        max_retries: Максимальное количество попыток
        total_pages: Общее количество страниц
        task_start_times: Словарь времен начала обработки страниц
        task_stages: Словарь текущих этапов обработки страниц
        log_func: Функция для логирования
    """
    log_func("info", f"    👷 Воркер {worker_id}: Запущен, ожидает страницы из очереди...")
    pages_processed = 0
    
    # ВАЖНО: Создаем одну сессию БД для всего воркера (для всех страниц, которые он обработает)
    # Это безопасно, потому что воркер обрабатывает страницы последовательно (не параллельно)
    # Это более эффективно, чем создавать сессию для каждой страницы
    worker_db_session = None
    if task and db_manager:
        try:
            worker_db_session = await asyncio.wait_for(
                db_manager.get_session(),
                timeout=10.0  # Таймаут 10 секунд для создания сессии
            )
            log_func("debug", f"    🔧 Воркер {worker_id}: Создана сессия БД для всех страниц воркера")
        except asyncio.TimeoutError:
            log_func("error", f"    ⏱️ Воркер {worker_id}: Таймаут при создании сессии БД (10с), БД может быть недоступна")
            worker_db_session = None
        except Exception as session_error:
            error_msg = str(session_error)[:200]
            log_func("error", f"    ❌ Воркер {worker_id}: Ошибка при создании сессии БД: {type(session_error).__name__}: {error_msg}")
            worker_db_session = None
    
    try:
        while True:
            page_data_str = None
            page_data = None
            page_num = None
            page_start = None
            page_count = None
            
            try:
                # Берем страницу из очереди (блокирующий pop с таймаутом 5 секунд)
                log_func("debug", f"    🔍 Воркер {worker_id}: Ожидает страницу из очереди (таймаут 5с)...")
                page_data_str = await redis_service.rpop(queue_key, timeout=5.0)
                
                if not page_data_str:
                    # Очередь пуста, проверяем еще раз
                    queue_length = await redis_service.llen(queue_key)
                    if queue_length == 0:
                        log_func("info", f"    ✅ Воркер {worker_id}: Очередь пуста, завершает работу (обработано страниц: {pages_processed})")
                        break
                    else:
                        log_func("debug", f"    ⏳ Воркер {worker_id}: Таймаут, но в очереди еще {queue_length} страниц, продолжаем...")
                        continue
                
                # Парсим данные страницы
                try:
                    page_data = json.loads(page_data_str)
                    page_num = page_data["page_num"]
                    page_start = page_data["page_start"]
                    page_count = page_data["page_count"]
                except Exception as e:
                    log_func("error", f"    ❌ Воркер {worker_id}: Ошибка при парсинге данных страницы: {e}")
                    log_func("error", f"       Данные: {page_data_str[:100]}")
                    continue
                
                # Проверяем, активна ли задача (для немедленной остановки)
                if task and worker_db_session:
                    try:
                        from sqlalchemy import select
                        from core import MonitoringTask
                        result = await worker_db_session.execute(
                            select(MonitoringTask).where(MonitoringTask.id == task.id)
                        )
                        db_task = result.scalar_one_or_none()
                        if db_task and not db_task.is_active:
                            log_func("info", f"🛑 Воркер {worker_id}: Задача {task.id} деактивирована, останавливаем обработку страницы {page_num}")
                            continue
                    except Exception as e:
                        log_func("warning", f"⚠️ Воркер {worker_id}: Ошибка при проверке статуса задачи: {e}")
                
                # Начинаем обработку страницы
                task_start_time = datetime.now()
                task_start_times[page_num] = task_start_time
                task_stages[page_num] = "начало"
                pages_processed += 1
                
                log_func("info", f"    📄 Воркер {worker_id}: Начал обработку страницы {page_num}/{total_pages} (start={page_start}, count={page_count})")
                
                # Heartbeat для отслеживания зависших воркеров
                heartbeat_task = None
                current_page_num = page_num
                async def heartbeat():
                    while True:
                        await asyncio.sleep(30)  # Каждые 30 секунд
                        elapsed = (datetime.now() - task_start_time).total_seconds()
                        current_stage = task_stages.get(current_page_num, "неизвестно")
                        log_func("warning", f"    💓 Воркер {worker_id}, страница {current_page_num}: HEARTBEAT - еще работает (этап: '{current_stage}', прошло {elapsed:.1f}с)")
                
                try:
                    heartbeat_task = asyncio.create_task(heartbeat())
                except Exception as hb_error:
                    log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Не удалось создать heartbeat: {hb_error}")
                
                # Обрабатываем страницу с retry
                for attempt in range(max_retries):
                    page_proxy = None
                    temp_client = None
                    temp_parser = None
                    
                    try:
                        # Этап 1: Выбор прокси
                        proxy_select_start = datetime.now()
                        task_stages[page_num] = f"выбор_прокси (попытка {attempt + 1})"
                        log_func("debug", f"    🔍 Воркер {worker_id}, страница {page_num}: Выбираем прокси (попытка {attempt + 1}/{max_retries})...")
                        
                        page_proxy = get_random_proxy(available_proxies)
                        proxy_select_time = (datetime.now() - proxy_select_start).total_seconds()
                        
                        if not page_proxy:
                            log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Нет доступных прокси (попытка {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Нет доступных прокси после {max_retries} попыток")
                                break
                        
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} выбран за {proxy_select_time:.2f}с")
                        
                        # Этап 2: Создание HTTP клиента
                        client_create_start = datetime.now()
                        task_stages[page_num] = f"создание_клиента (прокси {page_proxy.id}, попытка {attempt + 1})"
                        log_func("debug", f"    🔧 Воркер {worker_id}, страница {page_num}: Создаем HTTP клиент с прокси ID={page_proxy.id}...")
                        
                        from ..steam_http_client import SteamHttpClient
                        # Уменьшаем таймаут httpx до 20 секунд для быстрого переключения на другой прокси
                        temp_client = SteamHttpClient(proxy=page_proxy.url, timeout=20, proxy_manager=parser.proxy_manager)
                        await temp_client._ensure_client()
                        
                        temp_parser = parser.__class__(proxy=page_proxy.url, timeout=20, redis_service=parser.redis_service, proxy_manager=parser.proxy_manager)
                        await temp_parser._ensure_client()
                        
                        client_create_time = (datetime.now() - client_create_start).total_seconds()
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: HTTP клиент создан за {client_create_time:.2f}с")
                        
                        # Этап 3: Ротация заголовков
                        headers_start = datetime.now()
                        task_stages[page_num] = f"ротация_заголовков (прокси {page_proxy.id}, попытка {attempt + 1})"
                        log_func("debug", f"    🔄 Воркер {worker_id}, страница {page_num}: Обновляем заголовки...")
                        page_headers = temp_parser._get_browser_headers()
                        temp_parser._client.headers.update(page_headers)
                        headers_time = (datetime.now() - headers_start).total_seconds()
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Заголовки обновлены за {headers_time:.2f}с")
                        
                        # Этап 4: Выполнение запроса
                        request_start = datetime.now()
                        task_stages[page_num] = f"выполнение_запроса (прокси {page_proxy.id}, start={page_start}, попытка {attempt + 1})"
                        log_func("info", f"    📡 Воркер {worker_id}, страница {page_num}: Отправляем запрос через прокси ID={page_proxy.id} (start={page_start}, count={page_count})...")
                        
                        try:
                            # Увеличиваем таймаут до 120 секунд, чтобы хватило на несколько попыток с переключением прокси
                            # (каждая попытка до 20 сек + задержки между попытками)
                            render_data = await asyncio.wait_for(
                                temp_parser._fetch_render_api(appid, hash_name, start=page_start, count=page_count),
                                timeout=120.0
                            )
                            request_time = (datetime.now() - request_start).total_seconds()
                            log_func("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Запрос выполнен за {request_time:.2f}с")
                        except asyncio.TimeoutError:
                            request_time = (datetime.now() - request_start).total_seconds()
                            log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: ТАЙМАУТ запроса после {request_time:.2f}с на этапе 'выполнение_запроса'")
                            raise
                        except Exception as req_error:
                            request_time = (datetime.now() - request_start).total_seconds()
                            log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: ОШИБКА запроса после {request_time:.2f}с: {type(req_error).__name__}: {req_error}")
                            raise
                        
                        if render_data is None:
                            log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} не вернул данные (попытка {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Прокси ID={page_proxy.id} не вернул данные после {max_retries} попыток")
                                break
                        
                        # Этап 5: Парсинг данных
                        parse_start = datetime.now()
                        task_stages[page_num] = f"парсинг_данных (прокси {page_proxy.id}, попытка {attempt + 1})"
                        log_func("info", f"    🔍 Воркер {worker_id}, страница {page_num}: Начинаем парсинг данных...")
                        
                        # Извлекаем данные из assets
                        assets_data_map = extract_assets_data(render_data, worker_id, page_num, log_func)
                        
                        # Парсим HTML из results_html
                        results_html = render_data.get('results_html', '')
                        if not results_html:
                            log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: results_html пуст (попытка {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2.0)
                                continue
                            else:
                                log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: results_html пуст после {max_retries} попыток")
                                break
                        
                        page_listings = parse_page_listings(render_data, worker_id, page_num, log_func)
                        
                        # Связываем listing_id с данными из assets через listinginfo
                        link_listings_with_assets(page_listings, render_data, assets_data_map, worker_id, page_num, log_func)
                        
                        # Обрабатываем каждый лот и проверяем фильтры
                        # ВАЖНО: Используем сессию БД воркера (создана в начале функции)
                        # Сессия переиспользуется для всех страниц, обрабатываемых этим воркером
                        page_matching_listings = await process_page_listings(
                            parser=parser,
                            page_listings=page_listings,
                            hash_name=hash_name,
                            filters=filters,
                            task=task,
                            worker_db_session=worker_db_session,
                            redis_service=redis_service_for_notifications,
                            task_logger=task_logger,
                            worker_id=worker_id,
                            page_num=page_num,
                            log_func=log_func,
                            max_listings_time=120.0
                        )
                        
                        parse_time = (datetime.now() - parse_start).total_seconds()
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Парсинг завершен за {parse_time:.2f}с, найдено {len(page_matching_listings)} подходящих из {len(page_listings)} лотов")
                        
                        # Сохраняем результаты в Redis (без блокировки - быстрее!)
                        save_start = datetime.now()
                        task_stages[page_num] = "сохранение_результатов"
                        try:
                            from .parallel_listing_redis_storage import save_page_results_to_redis
                            
                            # Сохраняем в Redis (быстро, без блокировки)
                            saved = await asyncio.wait_for(
                                save_page_results_to_redis(
                                    redis_service=redis_service_for_notifications,
                                    task_id=task.id if task else 0,
                                    page_num=page_num,
                                    page_results=page_matching_listings,
                                    log_func=log_func
                                ),
                                timeout=5.0  # Таймаут 5 секунд для Redis (должно быть быстро)
                            )
                            
                            if saved:
                                # Обновляем счетчик завершенных страниц в Redis (атомарная операция, без блокировки)
                                if task and redis_service_for_notifications and redis_service_for_notifications._client:
                                    try:
                                        completed_key = f"parsing:completed:task_{task.id}"
                                        await redis_service_for_notifications._client.incr(completed_key)
                                    except Exception:
                                        pass
                                
                                total_time = (datetime.now() - task_start_time).total_seconds()
                                log_func("info", f"    ✅ Воркер {worker_id}, страница {page_num}/{total_pages} завершена: Найдено {len(page_listings)} лотов, подходящих {len(page_matching_listings)} (время: {total_time:.2f}с)")
                            else:
                                log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Не удалось сохранить результаты в Redis")
                        except asyncio.TimeoutError:
                            log_func("error", f"    ⏱️ Воркер {worker_id}, страница {page_num}: Таймаут при сохранении результатов в Redis (5с)")
                        except Exception as save_error:
                            error_msg = str(save_error)[:200]
                            log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Ошибка при сохранении результатов в Redis: {type(save_error).__name__}: {error_msg}")
                        
                        save_time = (datetime.now() - save_start).total_seconds()
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Результаты сохранены в Redis за {save_time:.2f}с")
                        
                        # Отмечаем прокси как успешно использованный
                        if parser.proxy_manager and page_proxy:
                            await parser.proxy_manager.mark_proxy_used(page_proxy, success=True)
                        
                        # Успешно обработали страницу, выходим из цикла retry
                        task_stages[page_num] = "завершено"
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                pass
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
                        log_func("error", f"    ⏱️ Воркер {worker_id}, страница {page_num}: ТАЙМАУТ запроса (120с) на этапе '{current_stage}' после {timeout_time:.2f}с работы (попытка {attempt + 1}/{max_retries})")
                        
                        if attempt < max_retries - 1:
                            log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Таймаут запроса, повторяем с другим прокси...")
                            if page_proxy and parser.proxy_manager:
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Timeout")
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Таймаут запроса после {max_retries} попыток")
                            if page_proxy and parser.proxy_manager:
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error="Timeout")
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
                        log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: ОШИБКА на этапе '{current_stage}' после {error_time:.2f}с: {type(e).__name__}: {error_msg} (попытка {attempt + 1}/{max_retries})")
                        import traceback
                        log_func("error", f"    📋 Traceback: {traceback.format_exc()[:500]}")
                        
                        if attempt < max_retries - 1:
                            log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Ошибка, повторяем с другим прокси...")
                            if page_proxy and parser.proxy_manager:
                                is_429 = "429" in error_msg or "Too Many Requests" in error_msg
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error=error_msg, is_429_error=is_429)
                            await asyncio.sleep(2.0)
                            continue
                        else:
                            log_func("error", f"    ❌ Воркер {worker_id}, страница {page_num}: Ошибка после {max_retries} попыток: {type(e).__name__}: {error_msg}")
                            if page_proxy and parser.proxy_manager:
                                is_429 = "429" in error_msg or "Too Many Requests" in error_msg
                                await parser.proxy_manager.mark_proxy_used(page_proxy, success=False, error=error_msg, is_429_error=is_429)
                            if page_num in task_start_times:
                                del task_start_times[page_num]
                            if page_num in task_stages:
                                del task_stages[page_num]
                            break
                    finally:
                        # Отменяем heartbeat при выходе из цикла retry
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                pass
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
                log_func("error", f"    ❌ Воркер {worker_id}: КРИТИЧЕСКАЯ ОШИБКА при обработке страницы: {type(e).__name__}: {error_msg}")
                import traceback
                log_func("error", f"    📋 Traceback: {traceback.format_exc()}")
                if 'heartbeat_task' in locals() and heartbeat_task:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                if page_num:
                    if page_num in task_start_times:
                        del task_start_times[page_num]
                    if page_num in task_stages:
                        del task_stages[page_num]
    finally:
        # Закрываем сессию БД воркера после завершения работы (для всех страниц)
        if worker_db_session:
            try:
                await asyncio.wait_for(worker_db_session.close(), timeout=5.0)
                log_func("debug", f"    🔧 Воркер {worker_id}: Сессия БД закрыта")
            except (asyncio.TimeoutError, Exception) as close_error:
                log_func("warning", f"    ⚠️ Воркер {worker_id}: Ошибка при закрытии сессии БД: {close_error}")
    
    log_func("info", f"    🏁 Воркер {worker_id}: Завершил работу (обработано страниц: {pages_processed})")

