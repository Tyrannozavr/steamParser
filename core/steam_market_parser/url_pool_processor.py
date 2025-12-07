"""
Модуль для обработки пула URL'ов.
Отвечает за последовательную обработку всех URL'ов из пула.
"""
import asyncio
import httpx
from typing import List, Dict, Any
from loguru import logger

from ..models import SearchFilters
from ..logger import get_task_logger


async def process_url_pool(
    parser,
    listing_parser,
    url_pool: List[Dict[str, Any]],
    filters: SearchFilters,
    task=None,
    db_session=None,
    redis_service=None
) -> Dict[str, Any]:
    """
    Обрабатывает все URL'ы из пула последовательно.
    
    Args:
        parser: Экземпляр SteamMarketParser для использования его методов
        listing_parser: Экземпляр ListingParser для парсинга лотов
        url_pool: Пул URL'ов для обработки
        filters: Параметры поиска
        
    Returns:
        Словарь с объединенными результатами
    """
    all_items = []
    all_listing_ids = set()
    total_count = 0
    
    # Получаем логгер для задачи (если task_id установлен в контексте)
    task_logger = get_task_logger()
    
    logger.info(f"🔄 Начинаем обработку пула из {len(url_pool)} URL'ов...")
    
    # Логируем начало обработки пула в лог задачи
    try:
        if task_logger and task_logger.task_id:
            task_logger.info(f"🔄 Начинаем обработку пула из {len(url_pool)} URL'ов...")
    except Exception:
        pass  # Игнорируем ошибки с task_logger
    
    for idx, url_info in enumerate(url_pool):
        url_type = url_info["type"]
        url = url_info["url"]
        params = url_info["params"]
        page = url_info.get("page", 1)
        total_pages = url_info.get("total_pages", 1)
        
        logger.info(f"📄 [{idx + 1}/{len(url_pool)}] Обрабатываем {url_type} URL (страница {page}/{total_pages})...")
        
        # Логируем прогресс в лог задачи
        try:
            if task_logger and task_logger.task_id:
                if url_type == "query":
                    task_logger.info(f"📄 Обрабатываем query страницу {page} из {total_pages} (URL {idx + 1}/{len(url_pool)})...")
                elif url_type == "direct":
                    task_logger.info(f"📄 Обрабатываем прямую страницу предмета (URL {idx + 1}/{len(url_pool)})...")
                else:
                    task_logger.info(f"📄 Обрабатываем {url_type} URL (страница {page}/{total_pages}, URL {idx + 1}/{len(url_pool)})...")
        except Exception:
            pass  # Игнорируем ошибки с task_logger
        
        # Задержка между запросами
        if idx > 0:
            await parser._random_delay(min_seconds=1.0, max_seconds=2.0)
        
        # Обработка запроса с повторными попытками при 429 ошибках
        max_retries = 3
        max_proxy_switches = 10
        proxy_switches = 0
        attempt = 0
        data = None
        
        while attempt < max_retries:
            try:
                # Обновляем заголовки перед запросом
                headers = parser._get_browser_headers()
                parser._client.headers.update(headers)
                
                # Делаем запрос
                if url_type == "query":
                    response = await parser._client.get(url, params=params)
                else:  # direct
                    full_url = url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
                    logger.debug(f"🔍 Direct URL запрос: {full_url}")
                    response = await parser._client.get(full_url)
                    logger.debug(f"✅ Direct URL ответ: status_code={response.status_code}")
                
                response.raise_for_status()
                data = response.json()
                logger.debug(f"📥 Данные получены: success={data.get('success')}, total_count={data.get('total_count')}, results_len={len(data.get('results', []))}, results_html_len={len(data.get('results_html', ''))}")
                break  # Успешно получили данные
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Обрабатываем 429 ошибку
                    current_proxy = await parser._get_current_proxy()
                    await parser._handle_429_fast(current_proxy, f"'{filters.item_name}' (пул URL'ов)")
                    
                    # Переключаем прокси и повторяем попытку
                    if proxy_switches < max_proxy_switches:
                        proxy_switched = await parser._switch_proxy()
                        if proxy_switched:
                            proxy_switches += 1
                            logger.info(f"🔄 Переключение прокси {proxy_switches}/{max_proxy_switches} из-за 429, продолжаем с новым прокси")
                            attempt = 0  # Сбрасываем счетчик попыток при переключении прокси
                            await asyncio.sleep(1)  # Небольшая задержка перед повторной попыткой
                            continue
                        else:
                            logger.warning(f"⚠️ Не удалось переключить прокси, попытка {attempt + 1}/{max_retries}")
                            attempt += 1
                            if attempt < max_retries:
                                await asyncio.sleep(2)
                                continue
                    else:
                        logger.error(f"❌ Превышено максимальное количество переключений прокси ({max_proxy_switches})")
                        break
                else:
                    # Другая HTTP ошибка
                    logger.error(f"❌ HTTP ошибка {e.response.status_code} при обработке URL [{idx + 1}/{len(url_pool)}]")
                    break
            except Exception as e:
                logger.error(f"❌ Ошибка при запросе URL [{idx + 1}/{len(url_pool)}]: {e}")
                attempt += 1
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                break
        
        if not data:
            logger.warning(f"⚠️ Не удалось получить данные для URL [{idx + 1}/{len(url_pool)}] после {max_retries} попыток")
            continue
        
        try:
            if data.get("success"):
                if url_type == "query":
                    # Обрабатываем результаты query запроса
                    items = data.get("results", [])
                    total_count = max(total_count, data.get("total_count", 0))
                    
                    for item in items:
                        listing_id = item.get("listingid")
                        if listing_id and listing_id not in all_listing_ids:
                            all_listing_ids.add(listing_id)
                            all_items.append(item)
                        elif not listing_id:
                            # Проверяем дубликаты по названию и цене
                            item_name = item.get('name', item.get('asset_description', {}).get('market_hash_name', ''))
                            item_price = item.get('sell_price_text', '').replace('$', '').replace(',', '').strip()
                            is_duplicate = False
                            for existing_item in all_items:
                                existing_name = existing_item.get('name', existing_item.get('asset_description', {}).get('market_hash_name', ''))
                                existing_price = existing_item.get('sell_price_text', '').replace('$', '').replace(',', '').strip()
                                if item_name == existing_name and item_price == existing_price:
                                    is_duplicate = True
                                    break
                            if not is_duplicate:
                                all_items.append(item)
                    
                    logger.info(f"✅ Query страница {page}: получено {len(items)} предметов, уникальных: {len(all_items)}")
                    
                    # Логируем результат в лог задачи
                    try:
                        if task_logger and task_logger.task_id:
                            task_logger.info(f"✅ Query страница {page} из {total_pages}: получено {len(items)} предметов, уникальных: {len(all_items)}")
                    except Exception:
                        pass  # Игнорируем ошибки с task_logger
                else:  # direct
                    # Обрабатываем результаты прямой страницы
                    hash_name = url_info.get("hash_name", "")
                    total_count = max(total_count, data.get("total_count", 0))
                    
                    # ВАЖНО: Используем _parse_all_listings для правильного парсинга render API
                    # Это гарантирует, что мы получим все лоты с правильными данными
                    logger.info(f"🔍 Парсим прямую страницу через _parse_all_listings для '{hash_name}'...")
                    
                    # Логируем начало парсинга прямой страницы в лог задачи
                    try:
                        if task_logger and task_logger.task_id:
                            task_logger.info(f"🔍 Парсим прямую страницу предмета '{hash_name}'...")
                    except Exception:
                        pass  # Игнорируем ошибки с task_logger
                    
                    # ВАЖНО: Формируем target_patterns из фильтров для ранней проверки паттернов
                    target_patterns = None
                    if filters.pattern_list:
                        target_patterns = set(filters.pattern_list.patterns)
                        logger.info(f"    🎯 Фильтр по паттерну (direct): ищем паттерны {target_patterns}")
                    elif filters.pattern_range:
                        target_patterns = set(range(filters.pattern_range.min, filters.pattern_range.max + 1))
                        logger.info(f"    🎯 Фильтр по паттерну (direct): ищем паттерны в диапазоне {filters.pattern_range.min}-{filters.pattern_range.max}")
                    
                    # Используем listing_parser если доступен
                    parsed_listings = await listing_parser.parse_all_listings(
                        filters.appid,
                        hash_name,
                        filters,
                        target_patterns=target_patterns,
                        task_logger=task_logger,
                        task=task,
                        db_session=db_session,
                        redis_service=redis_service
                    )
                    
                    logger.info(f"✅ _parse_all_listings вернул {len(parsed_listings)} лотов для '{hash_name}'")
                    
                    # Логируем результат парсинга прямой страницы в лог задачи
                    if task_logger and task_logger.task_id:
                        task_logger.info(f"✅ Прямая страница: получено {len(parsed_listings)} лотов для '{hash_name}'")
                    
                    # Преобразуем ParsedItemData в формат item для совместимости
                    logger.info(f"🔄 Преобразуем {len(parsed_listings)} ParsedItemData в формат items...")
                    for parsed_item in parsed_listings:
                        listing_id = parsed_item.listing_id
                        logger.debug(f"   🔍 Обрабатываем ParsedItemData: listing_id={listing_id}, price={parsed_item.item_price}, pattern={parsed_item.pattern}")
                        
                        if listing_id and listing_id not in all_listing_ids:
                            all_listing_ids.add(listing_id)
                            item = {
                                'name': hash_name,
                                'asset_description': {'market_hash_name': hash_name},
                                'sell_price_text': f"${parsed_item.item_price:.2f}" if parsed_item.item_price else "$0.00",
                                'listingid': listing_id,
                                'parsed_data': {
                                    'item_price': parsed_item.item_price,
                                    'float_value': parsed_item.float_value,
                                    'pattern': parsed_item.pattern,
                                    'stickers': parsed_item.stickers,
                                    'listing_id': listing_id
                                }
                            }
                            all_items.append(item)
                            logger.info(f"   ✅ Добавлен item в all_items: listing_id={listing_id}, price=${parsed_item.item_price:.2f}, pattern={parsed_item.pattern}")
                        elif not listing_id:
                            logger.warning(f"   ⚠️ ParsedItemData без listing_id, пропускаем: price=${parsed_item.item_price:.2f}, pattern={parsed_item.pattern}")
                        elif listing_id in all_listing_ids:
                            logger.debug(f"   ⏭️ listing_id={listing_id} уже в all_listing_ids, пропускаем дубликат")
                    
                    logger.info(f"✅ Прямая страница {page}: получено {len(parsed_listings)} лотов, уникальных: {len(all_items)}")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных URL [{idx + 1}/{len(url_pool)}] ({url_type}): {e}", exc_info=True)
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            continue
    
    logger.info(f"📊 Обработка пула завершена: получено {len(all_items)} уникальных предметов из {total_count} всего")
    
    # Логируем завершение обработки пула в лог задачи
    try:
        if task_logger and task_logger.task_id:
            task_logger.info(f"📊 Обработка пула завершена: получено {len(all_items)} уникальных предметов из {total_count} всего (обработано {len(url_pool)} URL'ов)")
    except Exception:
        pass  # Игнорируем ошибки с task_logger
    
    return {
        "success": True,
        "total_count": total_count,
        "results": all_items
    }

