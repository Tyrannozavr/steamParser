"""
Обработка лотов на странице для параллельного парсинга.
"""
import asyncio
from datetime import datetime
from typing import List, Optional

from ..models import ParsedItemData, SearchFilters
from parsers import detect_item_type
from .process_results import process_item_result


async def process_page_listings(
    parser,
    page_listings: List[dict],
    hash_name: str,
    filters: SearchFilters,
    task,
    worker_db_session,
    redis_service,
    task_logger,
    worker_id: int,
    page_num: int,
    log_func,
    max_listings_time: float = 120.0
) -> List[ParsedItemData]:
    """
    Обрабатывает лоты на странице: проверяет фильтры и сохраняет результаты.
    
    Args:
        parser: Экземпляр SteamMarketParser
        page_listings: Список лотов на странице
        hash_name: Хэш-имя предмета
        filters: Фильтры поиска
        task: Задача мониторинга
        worker_db_session: Сессия БД воркера
        redis_service: Сервис Redis
        task_logger: Логгер задачи
        worker_id: ID воркера
        page_num: Номер страницы
        log_func: Функция для логирования
        max_listings_time: Максимальное время на обработку всех лотов (секунды)
        
    Returns:
        Список подходящих лотов (ParsedItemData)
    """
    page_matching_listings = []
    listings_processed = 0
    listings_processing_start = datetime.now()
    
    for listing in page_listings:
        # Проверяем, не превышен ли таймаут обработки лотов
        listings_elapsed = (datetime.now() - listings_processing_start).total_seconds()
        if listings_elapsed > max_listings_time:
            log_func("warning", f"    ⏱️ Воркер {worker_id}, страница {page_num}: Превышен таймаут обработки лотов ({max_listings_time}с), обработано {listings_processed}/{len(page_listings)} лотов, пропускаем остальные")
            break
        
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
                    log_func("debug", f"    ⏭️ Воркер {worker_id}, страница {page_num}: Пропускаем предмет с паттерном {listing_pattern} (нормализован: {normalized_pattern}), не в списке {target_patterns}")
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
            if task and worker_db_session:
                log_func("info", f"    🔄 Воркер {worker_id}: Найден подходящий предмет, обрабатываем СРАЗУ (task={task.id})")
                try:
                    log_func("info", f"    📝 Воркер {worker_id}: Вызываем process_item_result для немедленной обработки...")
                    # Обрабатываем результат сразу (сохранение в БД + отправка уведомления) с таймаутом
                    try:
                        saved = await asyncio.wait_for(
                            process_item_result(
                                parser=parser,
                                task=task,
                                parsed_data=parsed_data,
                                filters=filters,
                                db_session=worker_db_session,
                                redis_service=redis_service,
                                task_logger=task_logger
                            ),
                            timeout=30.0  # Таймаут 30 секунд для обработки результата
                        )
                    except asyncio.TimeoutError:
                        log_func("error", f"    ⏱️ Воркер {worker_id}: Таймаут при обработке результата (30с), БД может быть недоступна или перегружена")
                        # В случае ошибки добавляем в список для совместимости
                        page_matching_listings.append(parsed_data)
                        continue
                    
                    if saved:
                        log_func("info", f"    │ ✅✅✅ ВСЕ ФИЛЬТРЫ ПРОЙДЕНЫ И ПРЕДМЕТ СОХРАНЕН СРАЗУ!")
                        log_func("info", f"    └────────────────────────────────────────────────────────────────────")
                        # ВАЖНО: НЕ добавляем в page_matching_listings, если результат уже обработан
                        # Это предотвратит повторную обработку через ResultsProcessorService
                        # Уведомление уже отправлено в process_item_result
                        log_func("info", f"    ℹ️ Предмет уже обработан и уведомление отправлено, не добавляем в список для повторной обработки")
                    else:
                        log_func("info", f"    │ ❌ НЕ ПРОШЕЛ ФИЛЬТРЫ ИЛИ УЖЕ СУЩЕСТВУЕТ В БД")
                        log_func("info", f"    └────────────────────────────────────────────────────────────────────")
                except Exception as process_error:
                    error_msg = str(process_error)[:200]
                    log_func("error", f"    ⚠️ Ошибка при обработке результата: {type(process_error).__name__}: {error_msg}")
                    import traceback
                    log_func("error", f"    Traceback: {traceback.format_exc()}")
                    # В случае ошибки все равно добавляем в список для совместимости
                    page_matching_listings.append(parsed_data)
            else:
                # Если нет task или db_manager, просто добавляем в список (старая логика)
                log_func("warning", f"    ⚠️ Воркер {worker_id}: Нет task или db_manager (task={task is not None}, db_manager={worker_db_session is not None}), используем старую логику")
                page_matching_listings.append(parsed_data)
        
        listings_processed += 1
    
    return page_matching_listings

