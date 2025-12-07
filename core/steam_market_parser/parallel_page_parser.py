"""
Модуль для параллельного парсинга страниц.
Отвечает за параллельную обработку нескольких страниц с распределением запросов между прокси.
"""
import asyncio
import httpx
from collections import deque
from typing import Dict, Any, List
from loguru import logger

from ..models import SearchFilters


async def parse_all_pages_parallel(
    parser,
    filters: SearchFilters,
    params: Dict[str, Any],
    items: List[Dict[str, Any]],
    total_count: int,
    current_start: int,
    max_per_request: int,
    active_proxies_count: int,
    max_retries: int,
    retry_delay: float,
    task_logger=None,
    total_pages: int = 0
):
    """
    Параллельный парсинг всех страниц с распределением запросов между прокси.
    Каждый запрос страницы использует отдельный прокси через get_next_proxy.
    Задержки применяются для каждого прокси отдельно.
    
    Args:
        parser: Экземпляр SteamMarketParser для использования его методов
        filters: Параметры поиска
        params: Параметры запроса
        items: Текущий список предметов
        total_count: Общее количество предметов
        current_start: Текущая позиция начала
        max_per_request: Максимальное количество предметов за запрос
        active_proxies_count: Количество активных прокси
        max_retries: Максимальное количество попыток
        retry_delay: Задержка между попытками
        task_logger: Опциональный логгер для задачи
        total_pages: Общее количество страниц
    """
    # Создаем список всех страниц, которые нужно запросить
    pages_to_fetch = []
    start = current_start
    
    while start < total_count:
        remaining = total_count - start
        request_count = min(max_per_request, remaining)
        pages_to_fetch.append((start, request_count))
        start += request_count
    
    if not pages_to_fetch:
        logger.info("📄 Нет страниц для парсинга")
        return
    
    logger.info(f"📄 Всего страниц для парсинга: {len(pages_to_fetch)}")
    if task_logger and task_logger.task_id and total_pages > 0:
        task_logger.info(f"📄 Всего страниц для парсинга: {total_pages}")
    
    # Создаем семафор для ограничения параллельных запросов (по количеству прокси)
    max_concurrent = min(active_proxies_count, len(pages_to_fetch)) if active_proxies_count > 0 else 1
    semaphore = asyncio.Semaphore(max_concurrent)
    logger.info(f"🔄 Параллельный парсинг страниц: максимум {max_concurrent} одновременных запросов")
    
    # Результаты (упорядоченный список)
    results = [None] * len(pages_to_fetch)
    lock = asyncio.Lock()
    completed_pages = 0  # Счетчик завершенных страниц
    
    async def fetch_page(page_idx: int, page_start: int, page_count: int):
        """Запрашивает одну страницу через отдельный прокси."""
        nonlocal completed_pages
        
        async with semaphore:
            # Получаем отдельный прокси для этого запроса
            page_proxy = None
            page_proxy_url = None
            if parser.proxy_manager:
                page_proxy = await parser.proxy_manager.get_next_proxy(force_refresh=False)
                if page_proxy:
                    page_proxy_url = page_proxy.url
                    logger.debug(f"   🌐 Страница {page_idx + 1}: Используем прокси ID={page_proxy.id}")
            
            # Если нет отдельного прокси, используем основной
            if not page_proxy_url:
                page_proxy_url = parser.proxy
            
            # Создаем отдельный HTTP клиент для этого прокси
            headers = parser._get_browser_headers()
            page_client = httpx.AsyncClient(
                proxy=page_proxy_url,
                timeout=parser.timeout,
                headers=headers,
                follow_redirects=True,
                cookies={}
            )
            
            try:
                # Параметры для этой страницы
                page_params = params.copy()
                page_params["start"] = page_start
                page_params["count"] = page_count
                
                page_success = False
                data_page = None
                
                for page_attempt in range(max_retries):
                    try:
                        # Обновляем заголовки перед запросом
                        page_headers = parser._get_browser_headers()
                        page_client.headers.update(page_headers)
                        
                        proxy_info = f" (через прокси: {page_proxy_url[:50]}...)" if page_proxy_url else " (прямое подключение)"
                        page_num = (page_start // max_per_request) + 1
                        logger.debug(f"📡 Страница {page_idx + 1}: Запрос к Steam API (start={page_start}, count={page_count}){proxy_info}")
                        if task_logger and task_logger.task_id and total_pages > 0:
                            task_logger.info(f"📄 Проверяем страницу {page_num} из {total_pages}")
                        
                        response_page = await page_client.get(parser.BASE_URL, params=page_params)
                        
                        logger.info(f"📥 Страница {page_idx + 1}: Получен ответ: status_code={response_page.status_code}")
                        
                        # Обработка 429
                        if response_page.status_code == 429:
                            should_retry = await parser._handle_429_error(
                                response=response_page,
                                attempt=page_attempt,
                                max_retries=max_retries,
                                base_delay=retry_delay,
                                context=f"страница {page_idx + 1} для '{filters.item_name}'"
                            )
                            if should_retry:
                                continue
                            else:
                                logger.warning(f"⚠️ Не удалось получить страницу {page_idx + 1} после {max_retries} попыток.")
                                break
                        
                        response_page.raise_for_status()
                        data_page = response_page.json()
                        
                        if data_page.get("success"):
                            page_items = data_page.get("results", [])
                            if page_items:
                                async with lock:
                                    results[page_idx] = page_items
                                    completed_pages += 1
                                    current_completed = completed_pages
                                page_num = page_idx + 1
                                logger.info(f"✅ Страница {page_num}/{len(pages_to_fetch)}: Получено {len(page_items)} предметов (проверено: {current_completed}/{len(pages_to_fetch)})")
                                if task_logger and task_logger.task_id and total_pages > 0:
                                    # Вычисляем номер страницы относительно общего количества
                                    actual_page = (page_start // max_per_request) + 1
                                    task_logger.info(f"✅ Страница {actual_page} из {total_pages}: Получено {len(page_items)} предметов")
                                page_success = True
                                break
                            else:
                                logger.warning(f"⚠️ Страница {page_idx + 1}: Пустой ответ")
                                break
                        else:
                            logger.warning(f"⚠️ Страница {page_idx + 1}: API вернул ошибку: {data_page.get('error', 'Unknown')}")
                            break
                            
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429:
                            should_retry = await parser._handle_429_error(
                                response=e.response,
                                attempt=page_attempt,
                                max_retries=max_retries,
                                base_delay=retry_delay,
                                context=f"страница {page_idx + 1} для '{filters.item_name}' (HTTPStatusError)"
                            )
                            if should_retry:
                                continue
                            else:
                                logger.warning(f"⚠️ Не удалось получить страницу {page_idx + 1} после {max_retries} попыток.")
                                break
                        else:
                            logger.error(f"❌ HTTP ошибка {e.response.status_code} при запросе страницы {page_idx + 1}: {e}")
                            break
                    except Exception as e:
                        logger.error(f"❌ Ошибка при запросе страницы {page_idx + 1}: {e}")
                        break
                
                # Отмечаем прокси как использованный
                if page_proxy and parser.proxy_manager:
                    await parser.proxy_manager.mark_proxy_used(page_proxy, success=page_success)
                
            finally:
                await page_client.aclose()
    
    # Запускаем все запросы параллельно
    tasks = [
        fetch_page(page_idx, page_start, page_count)
        for page_idx, (page_start, page_count) in enumerate(pages_to_fetch)
    ]
    
    await asyncio.gather(*tasks)
    
    # Собираем результаты в правильном порядке
    for page_items in results:
        if page_items:
            items.extend(page_items)
    
    logger.info(f"📊 Параллельный парсинг всех страниц завершен: проверено {completed_pages}/{len(pages_to_fetch)} страниц, получено {len(items)} из {total_count} предметов")

