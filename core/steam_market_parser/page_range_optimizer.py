"""
Модуль для оптимизации диапазона страниц при наличии фильтра по цене.
Использует бинарный поиск для определения максимальной страницы, которую нужно парсить.
"""
from typing import Optional, Tuple, List
from loguru import logger


def build_pages_list(
    total_count: int,
    listings_per_page: int = 20
) -> List[Tuple[int, int, int]]:
    """
    Создает список всех страниц для парсинга.
    
    Args:
        total_count: Общее количество лотов
        listings_per_page: Количество лотов на странице (по умолчанию 20)
        
    Returns:
        Список кортежей (page_num, start, count)
    """
    pages_to_fetch = []
    start = 0
    page_num = 1
    total_pages = (total_count + listings_per_page - 1) // listings_per_page
    
    while start < total_count:
        pages_to_fetch.append((page_num, start, listings_per_page))
        start += listings_per_page
        page_num += 1
    
    return pages_to_fetch


async def find_max_page_with_price_filter(
    parser,
    appid: int,
    hash_name: str,
    max_price: float,
    total_count: int,
    listings_per_page: int = 20,
    log_func=None
) -> int:
    """
    Использует бинарный поиск для определения максимальной страницы,
    которую нужно парсить при наличии фильтра по максимальной цене.
    
    Поскольку предметы на Steam Market отсортированы по возрастанию цены,
    если на странице N первый элемент имеет цену > max_price,
    то все страницы >= N имеют цены > max_price и их можно не парсить.
    
    Args:
        parser: Экземпляр парсера с методом _fetch_render_api
        appid: ID приложения
        hash_name: Хэш-имя предмета
        max_price: Максимальная цена фильтра
        total_count: Общее количество лотов
        listings_per_page: Количество лотов на странице
        log_func: Функция для логирования (опционально)
        
    Returns:
        Номер максимальной страницы, которую нужно парсить (1-based)
    """
    def log(level: str, message: str):
        if log_func:
            log_func(level, message)
        else:
            if level == "info":
                logger.info(message)
            elif level == "debug":
                logger.debug(message)
            elif level == "warning":
                logger.warning(message)
            elif level == "error":
                logger.error(message)
    
    total_pages = (total_count + listings_per_page - 1) // listings_per_page
    
    if total_pages <= 1:
        log("info", f"🔍 Оптимизация диапазона: всего {total_pages} страниц, оптимизация не требуется")
        return total_pages
    
    log("info", f"🔍 Оптимизация диапазона страниц: всего {total_pages} страниц, max_price=${max_price:.2f}")
    
    # Бинарный поиск: ищем последнюю страницу, где первый элемент <= max_price
    left = 1  # Первая страница (1-based)
    right = total_pages  # Последняя страница (1-based)
    max_page_to_parse = total_pages  # По умолчанию парсим все страницы
    
    # Проверяем первую страницу - если она уже дороже, то ничего не парсим
    try:
        first_page_data = await parser._fetch_render_api(
            appid, hash_name, start=0, count=listings_per_page
        )
        if first_page_data and first_page_data.get("success"):
            results_html = first_page_data.get("results_html", "")
            if results_html:
                from parsers import ItemPageParser
                parser_obj = ItemPageParser(results_html)
                page_listings = parser_obj.get_all_listings()
                if page_listings:
                    # Проверяем первые 2 элемента, используем более дешевый для определения границы
                    first_item_price = page_listings[0].get('price', 0.0)
                    reference_price = first_item_price
                    
                    if len(page_listings) >= 2:
                        second_item_price = page_listings[1].get('price', 0.0)
                        # Если второй элемент дешевле первого, используем его (предмет мог выбиться из списка)
                        if second_item_price < first_item_price:
                            reference_price = second_item_price
                            log("debug", f"   ⚠️ Второй элемент дешевле первого (${second_item_price:.2f} < ${first_item_price:.2f}), используем второй для проверки")
                    
                    if reference_price > max_price:
                        log("info", f"❌ Оптимизация: даже первая страница дороже ${max_price:.2f} (эталонная цена=${reference_price:.2f}), парсить нечего")
                        return 0  # Не парсим ничего
    except Exception as e:
        log("warning", f"⚠️ Ошибка при проверке первой страницы: {e}, парсим все страницы")
        return total_pages
    
    # Бинарный поиск
    iterations = 0
    max_iterations = 20  # Защита от бесконечного цикла
    
    while left <= right and iterations < max_iterations:
        iterations += 1
        mid_page = (left + right) // 2
        mid_start = (mid_page - 1) * listings_per_page
        
        log("debug", f"🔍 Итерация {iterations}: проверяем страницу {mid_page}/{total_pages} (start={mid_start})")
        
        try:
            # Запрашиваем среднюю страницу
            page_data = await parser._fetch_render_api(
                appid, hash_name, start=mid_start, count=listings_per_page
            )
            
            if not page_data or not page_data.get("success"):
                log("warning", f"⚠️ Не удалось получить страницу {mid_page}, используем все страницы")
                return total_pages
            
            results_html = page_data.get("results_html", "")
            if not results_html:
                log("warning", f"⚠️ Пустой results_html на странице {mid_page}, используем все страницы")
                return total_pages
            
            # Парсим HTML и получаем цены первых элементов
            from parsers import ItemPageParser
            parser_obj = ItemPageParser(results_html)
            page_listings = parser_obj.get_all_listings()
            
            if not page_listings:
                log("warning", f"⚠️ Нет лотов на странице {mid_page}, используем все страницы")
                return total_pages
            
            # Проверяем первые 2 элемента, используем более дешевый для определения границы
            first_item_price = page_listings[0].get('price', 0.0)
            reference_price = first_item_price
            
            if len(page_listings) >= 2:
                second_item_price = page_listings[1].get('price', 0.0)
                # Если второй элемент дешевле первого, используем его (предмет мог выбиться из списка)
                if second_item_price < first_item_price:
                    reference_price = second_item_price
                    log("debug", f"   ⚠️ Страница {mid_page}: второй элемент дешевле первого (${second_item_price:.2f} < ${first_item_price:.2f}), используем второй для проверки")
            
            log("debug", f"   💰 Страница {mid_page}: эталонная цена = ${reference_price:.2f} (первый=${first_item_price:.2f})")
            
            if reference_price > max_price:
                # Все страницы >= mid_page имеют цены > max_price (т.к. сортировка по возрастанию)
                # Значит максимальная страница для парсинга = mid_page - 1
                max_page_to_parse = mid_page - 1
                right = mid_page - 1
                log("debug", f"   ❌ Страница {mid_page} дороже ${max_price:.2f} (эталонная=${reference_price:.2f}), уменьшаем правую границу до {right}")
            else:
                # Страница mid_page имеет цены <= max_price
                # Значит нужно проверить дальше (может быть еще страницы с подходящими ценами)
                max_page_to_parse = mid_page
                left = mid_page + 1
                log("debug", f"   ✅ Страница {mid_page} подходит (<= ${max_price:.2f}, эталонная=${reference_price:.2f}), увеличиваем левую границу до {left}")
        
        except Exception as e:
            log("warning", f"⚠️ Ошибка при проверке страницы {mid_page}: {e}, используем все страницы")
            return total_pages
    
    if iterations >= max_iterations:
        log("warning", f"⚠️ Достигнут лимит итераций ({max_iterations}), используем все страницы")
        return total_pages
    
    # Убеждаемся, что max_page_to_parse не меньше 1
    if max_page_to_parse < 1:
        max_page_to_parse = 1
    
    saved_pages = total_pages - max_page_to_parse
    if saved_pages > 0:
        log("info", f"✅ Оптимизация завершена: нужно парсить страницы 1-{max_page_to_parse} из {total_pages} (сэкономлено {saved_pages} страниц, {saved_pages*100//total_pages}%)")
    else:
        log("info", f"✅ Оптимизация завершена: нужно парсить все {total_pages} страниц (оптимизация не дала результата)")
    
    return max_page_to_parse


async def build_optimized_pages_list(
    parser,
    appid: int,
    hash_name: str,
    filters,
    total_count: int,
    listings_per_page: int = 20,
    log_func=None
) -> List[Tuple[int, int, int]]:
    """
    Создает оптимизированный список страниц для парсинга.
    Если есть фильтр по максимальной цене, использует бинарный поиск
    для определения максимальной страницы.
    
    Args:
        parser: Экземпляр парсера с методом _fetch_render_api
        appid: ID приложения
        hash_name: Хэш-имя предмета
        filters: Объект SearchFilters с фильтрами
        total_count: Общее количество лотов
        listings_per_page: Количество лотов на странице
        log_func: Функция для логирования (опционально)
        
    Returns:
        Список кортежей (page_num, start, count)
    """
    def log(level: str, message: str):
        if log_func:
            log_func(level, message)
        else:
            if level == "info":
                logger.info(message)
            elif level == "debug":
                logger.debug(message)
            elif level == "warning":
                logger.warning(message)
            elif level == "error":
                logger.error(message)
    
    # Если нет фильтра по цене, парсим все страницы
    if not filters.max_price:
        log("info", f"📄 Нет фильтра по цене, парсим все страницы")
        return build_pages_list(total_count, listings_per_page)
    
    # Используем бинарный поиск для определения максимальной страницы
    max_page = await find_max_page_with_price_filter(
        parser=parser,
        appid=appid,
        hash_name=hash_name,
        max_price=filters.max_price,
        total_count=total_count,
        listings_per_page=listings_per_page,
        log_func=log_func
    )
    
    if max_page <= 0:
        log("info", f"📄 Оптимизация: не нужно парсить ни одной страницы (все дороже ${filters.max_price:.2f})")
        return []
    
    # Создаем список страниц до максимальной
    pages_to_fetch = []
    start = 0
    page_num = 1
    
    while page_num <= max_page and start < total_count:
        pages_to_fetch.append((page_num, start, listings_per_page))
        start += listings_per_page
        page_num += 1
    
    log("info", f"📄 Оптимизированный список: {len(pages_to_fetch)} страниц (из {((total_count + listings_per_page - 1) // listings_per_page)})")
    
    return pages_to_fetch

