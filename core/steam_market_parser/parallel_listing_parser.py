"""
Модуль для параллельного парсинга страниц лотов.
Использует Redis очередь для распределения страниц между воркерами.
"""
import asyncio
import json
from typing import Optional, List, Set
from datetime import datetime
from loguru import logger

from ..models import SearchFilters, ParsedItemData
from core.steam_market_parser.logger_utils import log_both
from core.steam_market_parser.page_range_optimizer import build_optimized_pages_list
from .parallel_listing_utils import get_available_proxies, get_random_proxy
from .parallel_listing_worker import process_page_from_queue


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
        db_manager: Менеджер БД
        
    Returns:
        Список ParsedItemData
    """
    def log(level: str, message: str):
        log_both(level, message, task_logger)
    
    log("info", f"🚀 parse_listings_parallel: Начало (total_count={total_count}, active_proxies={active_proxies_count}, redis_service={redis_service is not None})")
    
    # Создаем оптимизированный список страниц для парсинга
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
    
    # Получаем список активных прокси
    available_proxies = await get_available_proxies(parser, log)
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
    
    # ВАЖНО: Результаты теперь сохраняются в Redis (без блокировки)
    # В конце соберем все результаты из Redis
    matching_listings = []
    max_retries = 3  # Максимум 3 попытки для страницы
    
    # Счетчики для диагностики
    task_start_times = {}  # page_num -> start_time
    task_stages = {}  # page_num -> current_stage
    
    # Запускаем воркеры параллельно
    log("info", f"🚀 Запускаем {max_concurrent} воркеров для обработки страниц из Redis очереди...")
    
    workers = [
        asyncio.create_task(
            process_page_from_queue(
                worker_id=worker_id,
                queue_key=queue_key,
                redis_service=redis_service,
                parser=parser,
                appid=appid,
                hash_name=hash_name,
                filters=filters,
                task=task,
                db_manager=db_manager,
                task_logger=task_logger,
                redis_service_for_notifications=redis_service,
                available_proxies=available_proxies,
                max_retries=max_retries,
                total_pages=total_pages,
                task_start_times=task_start_times,
                task_stages=task_stages,
                log_func=log
            )
        )
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
    
    # Собираем результаты из Redis (быстро, без блокировки)
    # ВАЖНО: Если результаты уже обработаны в параллельном парсере (сразу после нахождения),
    # то они не будут в Redis, так как process_item_result уже обработал их
    try:
        from .parallel_listing_redis_storage import get_all_results_from_redis, cleanup_redis_results
        
        log("info", f"📥 Собираем результаты из Redis...")
        matching_listings = await get_all_results_from_redis(
            redis_service=redis_service,
            task_id=task.id if task else 0,
            total_pages=total_pages,
            log_func=log
        )
        
        # Очищаем результаты из Redis после сбора
        await cleanup_redis_results(
            redis_service=redis_service,
            task_id=task.id if task else 0,
            total_pages=total_pages,
            log_func=log
        )
        
        # Получаем количество завершенных страниц из Redis
        completed_count = 0
        if task:
            completed_key = f"parsing:completed:task_{task.id}"
            try:
                completed_str = await redis_service.get(completed_key)
                if completed_str:
                    completed_count = int(completed_str)
                # Очищаем счетчик
                await redis_service.delete(completed_key)
            except Exception:
                pass
        
        log("info", f"📊 Параллельный парсинг завершен: проверено {completed_count}/{len(pages_to_fetch)} страниц, найдено {len(matching_listings)} подходящих лотов")
    except Exception as e:
        log("error", f"❌ Ошибка при сборе результатов из Redis: {e}")
        import traceback
        log("error", f"   Traceback: {traceback.format_exc()}")
    if len(matching_listings) == 0:
        log("info", f"ℹ️ Список результатов пуст - все найденные предметы уже обработаны сразу (уведомления отправлены)")
    
    return matching_listings
