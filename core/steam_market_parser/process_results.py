"""
Модуль для обработки результатов парсинга.
Отвечает за фильтрацию, запрос цен наклеек (если нужно) и отправку уведомлений в телеграм.
Обрабатывает результаты сразу после парсинга страницы, не накапливая их.
"""
import asyncio
import json
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from core import FoundItem, MonitoringTask
from ..models import ParsedItemData, SearchFilters
from services.redis_service import RedisService
from services.filter_service import FilterService
from ..logger import get_task_logger
from core import MonitoringTask


async def process_item_result(
    parser,
    task: MonitoringTask,
    parsed_data: ParsedItemData,
    filters: SearchFilters,
    db_session: AsyncSession,
    redis_service: Optional[RedisService] = None,
    task_logger=None
) -> bool:
    # ВАЖНО: Если task был загружен в другой сессии, загружаем его заново в текущей сессии
    # Это предотвращает ошибку "Instance is not persistent within this Session"
    if task and hasattr(task, 'id'):
        try:
            # Пытаемся загрузить task в текущей сессии с таймаутом
            task = await asyncio.wait_for(
                db_session.get(MonitoringTask, task.id),
                timeout=10.0  # Таймаут 10 секунд для загрузки задачи
            )
            if not task:
                logger.error(f"❌ Задача {task.id if hasattr(task, 'id') else 'unknown'} не найдена в БД")
                return False
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Таймаут при загрузке задачи из БД (10с), БД может быть недоступна")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить task в текущей сессии: {e}, используем переданный объект")
    """
    Обрабатывает результат парсинга одного предмета:
    1. Проверяет фильтры
    2. Если нужны цены наклеек - запрашивает их
    3. Если все фильтры пройдены - сохраняет в БД и отправляет уведомление в телеграм
    
    Args:
        parser: Экземпляр SteamMarketParser для использования его методов
        task: Задача мониторинга
        parsed_data: Данные распарсенного предмета
        filters: Фильтры для проверки
        db_session: Сессия БД для сохранения результатов
        redis_service: Сервис Redis для публикации уведомлений
        task_logger: Логгер для задачи (опционально)
        
    Returns:
        True если предмет прошел фильтры и был сохранен, False иначе
    """
    if not task_logger:
        task_logger = get_task_logger()
    
    item_name = parsed_data.item_name or task.item_name
    item_price = parsed_data.item_price or 0.0
    listing_id = parsed_data.listing_id
    
    # Создаем item dict для FilterService
    item_dict = {
        "sell_price_text": f"${item_price:.2f}",
        "asset_description": {"market_hash_name": item_name},
        "name": item_name,
        "listingid": listing_id
    }
    
    # ШАГ 1: Сначала проверяем базовые фильтры (цена, паттерн, float, название) БЕЗ запроса цен наклеек
    # Это позволяет быстро отсеять предметы, которые не подходят
    logger.info(f"🔍 Проверяем базовые фильтры для: {item_name} (${item_price:.2f})")
    if task_logger:
        task_logger.info(f"🔍 Проверяем базовые фильтры для: {item_name} (${item_price:.2f})")
    
    try:
        filter_service = parser.filter_service
        
        # Проверяем базовые фильтры без наклеек (временно убираем фильтр наклеек)
        # Создаем копию фильтров без проверки наклеек для быстрой проверки
        from copy import deepcopy
        filters_without_stickers = deepcopy(filters)
        filters_without_stickers.stickers_filter = None
        
        # Временно убираем наклейки из parsed_data для быстрой проверки
        original_stickers = parsed_data.stickers
        parsed_data.stickers = []
        parsed_data.total_stickers_price = 0.0
        
        # Проверяем каждый фильтр отдельно для детального логирования
        # 1. Проверка цены
        if not filter_service.check_price(item_dict, filters):
            logger.info(f"❌ Предмет не прошел фильтр ЦЕНЫ: {item_name} (${item_price:.2f}, max_price: {filters.max_price})")
            if task_logger:
                task_logger.info(f"❌ Предмет не прошел фильтр ЦЕНЫ: ${item_price:.2f} > ${filters.max_price:.2f}")
            parsed_data.stickers = original_stickers
            return False
        
        # 2. Проверка названия
        if not filter_service.check_item_name(item_dict, filters, parsed_data):
            logger.info(f"❌ Предмет не прошел фильтр НАЗВАНИЯ: {item_name}")
            if task_logger:
                task_logger.info(f"❌ Предмет не прошел фильтр НАЗВАНИЯ")
            parsed_data.stickers = original_stickers
            return False
        
        # 3. Проверка паттерна
        pattern = parsed_data.pattern if parsed_data else None
        item_type = parsed_data.item_type if parsed_data else None
        if not filter_service.check_pattern(pattern, filters, item_type):
            expected_patterns = filters.pattern_list.patterns if filters.pattern_list else (f"{filters.pattern_range.min}-{filters.pattern_range.max}" if filters.pattern_range else "нет")
            logger.info(f"❌ Предмет не прошел фильтр ПАТТЕРНА: {item_name} (паттерн: {pattern}, ожидаемые: {expected_patterns})")
            if task_logger:
                task_logger.info(f"❌ Предмет не прошел фильтр ПАТТЕРНА: {pattern}")
            parsed_data.stickers = original_stickers
            return False
        
        # 4. Проверка float
        float_value = parsed_data.float_value if parsed_data else None
        if not filter_service.check_float(float_value, filters):
            float_range = f"{filters.float_range.min}-{filters.float_range.max}" if filters.float_range else "нет"
            logger.info(f"❌ Предмет не прошел фильтр FLOAT: {item_name} (float: {float_value}, ожидаемый диапазон: {float_range})")
            if task_logger:
                task_logger.info(f"❌ Предмет не прошел фильтр FLOAT: {float_value} (диапазон: {float_range})")
            parsed_data.stickers = original_stickers
            return False
        
        # Восстанавливаем наклейки
        parsed_data.stickers = original_stickers
        
        logger.info(f"✅ Предмет прошел базовые фильтры: {item_name}")
        if task_logger:
            task_logger.info(f"✅ Предмет прошел базовые фильтры")
    
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке базовых фильтров для {item_name}: {e}")
        if task_logger:
            task_logger.error(f"❌ Ошибка при проверке базовых фильтров: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return False
    
    # ШАГ 2: Если базовые фильтры пройдены, проверяем, нужны ли цены наклеек
    # Цены наклеек нужны в двух случаях:
    # 1. Есть фильтр по наклейкам (min_stickers_price, max_overpay_coefficient)
    # 2. Предмет прошел все фильтры и нужно опубликовать результат (для отображения в уведомлении)
    needs_sticker_prices_for_filter = (
        filters.stickers_filter is not None and
        (filters.stickers_filter.min_stickers_price is not None or 
         filters.stickers_filter.max_overpay_coefficient is not None)
    )
    
    # Запрашиваем цены наклеек только если:
    # 1. Есть фильтр по наклейкам ИЛИ
    # 2. Предмет прошел все фильтры и нужно для публикации
    if parsed_data.stickers and needs_sticker_prices_for_filter:
        # Проверяем, есть ли уже цены наклеек
        has_prices = any(sticker.price is not None and sticker.price > 0 for sticker in parsed_data.stickers)
        
        # Детальное логирование для отладки
        stickers_count = len(parsed_data.stickers)
        stickers_names = [s.name for s in parsed_data.stickers[:3]]  # Первые 3 для логирования
        logger.info(f"📋 Запрашиваем цены для {stickers_count} наклеек: {stickers_names}{'...' if stickers_count > 3 else ''}")
        if task_logger:
            task_logger.info(f"📋 Запрашиваем цены для {stickers_count} наклеек: {stickers_names}{'...' if stickers_count > 3 else ''}")
        
        if not has_prices:
            logger.info(f"💰 Запрашиваем цены наклеек для {item_name}...")
            if task_logger:
                task_logger.info(f"💰 Запрашиваем цены наклеек...")
            
            # Используем StickerPriceResolver для получения цен наклеек
            if parser and hasattr(parser, 'get_stickers_prices'):
                from core.utils.sticker_parser import StickerPriceResolver
                from parsers.sticker_prices import StickerPricesAPI
                
                # Создаем resolver
                price_resolver = StickerPriceResolver(
                    sticker_prices_api=StickerPricesAPI,
                    redis_service=redis_service,
                    proxy_manager=parser.proxy_manager if hasattr(parser, 'proxy_manager') else None
                )
                
                # Извлекаем названия наклеек
                sticker_names = []
                for s in parsed_data.stickers:
                    sticker_name = s.name if hasattr(s, 'name') and s.name else (s.wear if hasattr(s, 'wear') and s.wear else None)
                    if sticker_name:
                        sticker_names.append(sticker_name)
                    else:
                        logger.warning(f"⚠️ Наклейка без названия: name={getattr(s, 'name', None)}, wear={getattr(s, 'wear', None)}, position={getattr(s, 'position', None)}")
                
                if sticker_names:
                    logger.info(f"📋 Запрашиваем цены для {len(sticker_names)} наклеек: {sticker_names}")
                    if task_logger:
                        task_logger.info(f"📋 Запрашиваем цены для {len(sticker_names)} наклеек: {sticker_names}")
                    
                    # Получаем цены через resolver (с гибким сопоставлением)
                    prices = await price_resolver.get_stickers_prices(
                        sticker_names,
                        appid=task.appid if hasattr(task, 'appid') else 730,
                        currency=1,
                        proxy=parser.proxy if hasattr(parser, 'proxy') else None,
                        delay=0.3,
                        use_fuzzy_matching=True
                    )
                    
                    # Детальное логирование для отладки
                    logger.info(f"📊 Получено цен из API: {len(prices)} записей")
                    logger.info(f"   🔍 Запрошенные названия: {sticker_names}")
                    logger.info(f"   🔍 Полученные ключи: {list(prices.keys()) if prices else 'пусто'}")
                    # Проверяем совпадения
                    if prices:
                        matched = [name for name in sticker_names if name in prices and prices[name] is not None]
                        unmatched = [name for name in sticker_names if name not in prices or prices[name] is None]
                        logger.info(f"   ✅ Найдено цен: {len(matched)} из {len(sticker_names)}")
                        if unmatched:
                            logger.warning(f"   ⚠️ Не найдено цен для {len(unmatched)} наклеек: {unmatched}")
                            # Показываем, какие цены были получены
                            found_prices = {k: v for k, v in prices.items() if v is not None}
                            if found_prices:
                                logger.info(f"   💰 Найденные цены: {found_prices}")
                    else:
                        logger.warning(f"   ❌ API не вернул ни одной цены!")
                    if task_logger:
                        task_logger.info(f"📊 Получено цен из API: {len(prices)} записей")
                        if prices:
                            task_logger.info(f"   Запрошено: {sticker_names}")
                            task_logger.info(f"   Получено: {list(prices.keys())}")
                    
                    # Обновляем цены наклеек
                    updated_stickers = []
                    total_stickers_price = 0.0
                    updated_count = 0
                    failed_stickers = []
                    cached_stickers = []
                    
                    for sticker in parsed_data.stickers:
                        sticker_name = sticker.name if hasattr(sticker, 'name') and sticker.name else (sticker.wear if hasattr(sticker, 'wear') and sticker.wear else None)
                        if sticker_name:
                            if sticker_name in prices and prices[sticker_name] is not None:
                                old_price = sticker.price
                                sticker.price = prices[sticker_name]
                                total_stickers_price += prices[sticker_name]
                                updated_count += 1
                                # Проверяем, была ли цена в кэше (если old_price был None, значит запрашивали через API)
                                if old_price is None:
                                    cached_stickers.append(sticker_name)
                                logger.debug(f"💰 Обновлена цена для '{sticker_name}': {old_price} -> ${prices[sticker_name]:.2f}")
                            elif sticker.price and sticker.price > 0:
                                # У наклейки уже была цена (из предыдущего запроса или кэша)
                                total_stickers_price += sticker.price
                                logger.debug(f"💰 Использована существующая цена для '{sticker_name}': ${sticker.price:.2f}")
                            else:
                                # Цена не найдена
                                failed_stickers.append(sticker_name)
                                logger.warning(f"⚠️ Цена не найдена для наклейки '{sticker_name}'")
                                if task_logger:
                                    task_logger.warning(f"⚠️ Цена не найдена для '{sticker_name}'")
                        else:
                            logger.warning(f"⚠️ Не удалось извлечь название наклейки из объекта: {sticker}")
                        updated_stickers.append(sticker)
                    
                    parsed_data.stickers = updated_stickers
                    parsed_data.total_stickers_price = total_stickers_price
                    
                    # Выводим детальную информацию о результатах
                    if cached_stickers:
                        logger.info(f"📦 Использованы цены из кэша для {len(cached_stickers)} наклеек")
                        if task_logger:
                            task_logger.info(f"📦 Использованы цены из кэша для {len(cached_stickers)} наклеек")
                    
                    if failed_stickers:
                        logger.warning(f"⚠️ Не удалось получить цены для {len(failed_stickers)} наклеек: {', '.join(failed_stickers[:5])}{'...' if len(failed_stickers) > 5 else ''}")
                        if task_logger:
                            task_logger.warning(f"⚠️ Не удалось получить цены для {len(failed_stickers)} наклеек")
                    
                    if updated_count > 0:
                        logger.info(f"✅ Получены цены наклеек: ${total_stickers_price:.2f} (обновлено {updated_count} из {len(parsed_data.stickers)})")
                        if task_logger:
                            task_logger.info(f"✅ Получены цены наклеек: ${total_stickers_price:.2f} (обновлено {updated_count} из {len(parsed_data.stickers)})")
                    else:
                        logger.warning(f"⚠️ Не удалось получить цены ни для одной наклейки (всего {len(parsed_data.stickers)} наклеек)")
                        if task_logger:
                            task_logger.warning(f"⚠️ Не удалось получить цены ни для одной наклейки")
                else:
                    logger.warning(f"⚠️ Не удалось извлечь названия наклеек для запроса цен")
            else:
                    logger.warning(f"⚠️ Парсер не установлен или не имеет метода get_stickers_prices, невозможно запросить цены наклеек")
        else:
            # Цены уже есть, просто суммируем их
            total_stickers_price = sum(s.price for s in parsed_data.stickers if s.price and s.price > 0)
            parsed_data.total_stickers_price = total_stickers_price
            logger.debug(f"💰 Используем уже имеющиеся цены наклеек: ${total_stickers_price:.2f}")
    
    # ШАГ 3: Проверяем фильтры наклеек (если они есть) через FilterService
    logger.info(f"🔍 Проверяем фильтры наклеек для: {item_name} (${item_price:.2f})")
    if task_logger:
        task_logger.info(f"🔍 Проверяем фильтры наклеек для: {item_name} (${item_price:.2f})")
    
    try:
        filter_service = parser.filter_service
        
        # Если есть фильтр по наклейкам, проверяем его отдельно для детального логирования
        if filters.stickers_filter:
            stickers_count = len(parsed_data.stickers) if parsed_data.stickers else 0
            total_stickers_price = parsed_data.total_stickers_price if parsed_data.total_stickers_price else 0.0
            
            if task_logger:
                task_logger.info(f"📊 Наклеек: {stickers_count}, общая цена: ${total_stickers_price:.2f}")
            
            # Проверяем наклейки отдельно для детального логирования
            stickers_passed = await filter_service.check_stickers(parsed_data, item_dict, filters)
            
            if not stickers_passed:
                # Детальное логирование причины отказа с конкретными значениями
                if filters.stickers_filter.min_stickers_price is not None:
                    if total_stickers_price < filters.stickers_filter.min_stickers_price:
                        reason = f"Суммарно наклейки стоят ${total_stickers_price:.2f}, фильтр ${filters.stickers_filter.min_stickers_price:.2f} - не проходит"
                        logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {item_name} - {reason}")
                        if task_logger:
                            task_logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {reason}")
                    elif total_stickers_price == 0.0:
                        reason = f"Цена наклеек $0.00 - цены наклеек не были получены (фильтр: ${filters.stickers_filter.min_stickers_price:.2f})"
                        logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {item_name} - {reason}")
                        if task_logger:
                            task_logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {reason}")
                elif filters.stickers_filter.max_overpay_coefficient is not None:
                    reason = f"Не прошел проверку коэффициента переплаты (максимум: {filters.stickers_filter.max_overpay_coefficient})"
                    logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {item_name} - {reason}")
                    if task_logger:
                        task_logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {reason}")
                elif stickers_count == 0:
                    reason = f"Предмет без наклеек (0 наклеек), но установлен фильтр по наклейкам"
                    logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {item_name} - {reason}")
                    if task_logger:
                        task_logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {reason}")
                else:
                    reason = f"Не прошел проверку наклеек (неизвестная причина, наклеек: {stickers_count}, цена: ${total_stickers_price:.2f})"
                    logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {item_name} - {reason}")
                    if task_logger:
                        task_logger.info(f"❌ Предмет не прошел фильтр НАКЛЕЕК: {reason}")
                return False
            else:
                logger.info(f"✅ Предмет прошел фильтр наклеек: {item_name} (цена наклеек: ${total_stickers_price:.2f})")
                if task_logger:
                    task_logger.info(f"✅ Предмет прошел фильтр наклеек (цена наклеек: ${total_stickers_price:.2f})")
        
        # Проверяем все остальные фильтры через matches_filters
        matches = await filter_service.matches_filters(item_dict, filters, parsed_data)
        
        if not matches:
            logger.info(f"❌ Предмет не прошел фильтры: {item_name}")
            if task_logger:
                task_logger.info(f"❌ Предмет не прошел фильтры")
            return False
        
        logger.info(f"✅ Предмет прошел все фильтры (включая наклейки): {item_name}")
        if task_logger:
            task_logger.success(f"✅ Предмет прошел все фильтры")
        
        # ШАГ 4: Если предмет прошел все фильтры, запрашиваем цены наклеек для публикации
        # (если они еще не запрошены)
        if parsed_data.stickers and not needs_sticker_prices_for_filter:
            # Цены наклеек нужны только для отображения в уведомлении
            has_prices = any(sticker.price is not None and sticker.price > 0 for sticker in parsed_data.stickers)
            
            if not has_prices:
                logger.info(f"💰 Запрашиваем цены наклеек для публикации: {item_name}...")
                if task_logger:
                    task_logger.info(f"💰 Запрашиваем цены наклеек для публикации...")
                
                # Используем метод парсера для получения цен наклеек
                if parser and hasattr(parser, 'get_stickers_prices'):
                    sticker_names = []
                    for s in parsed_data.stickers:
                        sticker_name = s.name if hasattr(s, 'name') and s.name else (s.wear if hasattr(s, 'wear') and s.wear else None)
                        if sticker_name:
                            sticker_names.append(sticker_name)
                    
                    if sticker_names:
                        prices = await parser.get_stickers_prices(sticker_names, delay=0.3)
                        
                        # Обновляем цены наклеек
                        total_stickers_price = 0.0
                        for sticker in parsed_data.stickers:
                            sticker_name = sticker.name if hasattr(sticker, 'name') and sticker.name else (sticker.wear if hasattr(sticker, 'wear') and sticker.wear else None)
                            if sticker_name and sticker_name in prices and prices[sticker_name] is not None:
                                sticker.price = prices[sticker_name]
                                total_stickers_price += prices[sticker_name]
                        
                        parsed_data.total_stickers_price = total_stickers_price
                        logger.info(f"✅ Получены цены наклеек для публикации: ${total_stickers_price:.2f}")
                        if task_logger:
                            task_logger.info(f"✅ Получены цены наклеек для публикации: ${total_stickers_price:.2f}")
        
        # Проверяем дубликаты по listing_id (приоритетная проверка) с таймаутом
        if listing_id:
            try:
                all_task_items = await asyncio.wait_for(
                    db_session.execute(
                        select(FoundItem).where(FoundItem.task_id == task.id)
                    ),
                    timeout=10.0  # Таймаут 10 секунд для запроса к БД
                )
                for existing_item in all_task_items.scalars().all():
                    try:
                        existing_data = json.loads(existing_item.item_data_json)
                        existing_listing_id = existing_data.get('listing_id')
                        if existing_listing_id and str(existing_listing_id) == str(listing_id):
                            logger.info(f"⏭️ Предмет с listing_id={listing_id} уже существует в БД (ID={existing_item.id}), пропускаем")
                            if task_logger:
                                task_logger.info(f"⏭️ Предмет уже существует в БД, пропускаем")
                            return False
                    except (json.JSONDecodeError, AttributeError):
                        pass
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Таймаут при проверке дубликатов по listing_id (10с), БД может быть недоступна")
                if task_logger:
                    task_logger.error(f"⏱️ Таймаут при проверке дубликатов")
                return False
            except Exception as db_error:
                logger.error(f"❌ Ошибка при проверке дубликатов по listing_id: {type(db_error).__name__}: {db_error}")
                if task_logger:
                    task_logger.error(f"❌ Ошибка при проверке дубликатов: {db_error}")
                return False
        
        # Дополнительная проверка по комбинации task_id + item_name + price + listing_id
        # Для брелков и других предметов с listing_id это более точная проверка
        if listing_id:
            # Если есть listing_id, проверяем по нему (уже проверили выше, но на всякий случай)
            try:
                existing_query = select(FoundItem).where(
                    FoundItem.task_id == task.id,
                    FoundItem.item_name == item_name,
                    FoundItem.price == item_price
                )
                existing_items = await asyncio.wait_for(
                    db_session.execute(existing_query),
                    timeout=10.0  # Таймаут 10 секунд для запроса к БД
                )
                for existing_item in existing_items.scalars().all():
                    try:
                        existing_data = json.loads(existing_item.item_data_json)
                        existing_listing_id = existing_data.get('listing_id')
                        # ВАЖНО: Приводим к строке для корректного сравнения (защита от дублей)
                        listing_id_str = str(listing_id) if listing_id else None
                        # Если у существующего предмета нет listing_id или он отличается - это разные лоты
                        if existing_listing_id and listing_id_str and str(existing_listing_id) == listing_id_str:
                            logger.info(f"⏭️ Предмет с listing_id={listing_id} уже существует в БД (ID={existing_item.id}), пропускаем")
                            if task_logger:
                                task_logger.info(f"⏭️ Предмет уже существует в БД, пропускаем")
                            return False
                    except (json.JSONDecodeError, AttributeError):
                        pass
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Таймаут при проверке дубликатов (10с), БД может быть недоступна")
                if task_logger:
                    task_logger.error(f"⏱️ Таймаут при проверке дубликатов")
                return False
            except Exception as db_error:
                logger.error(f"❌ Ошибка при проверке дубликатов: {type(db_error).__name__}: {db_error}")
                if task_logger:
                    task_logger.error(f"❌ Ошибка при проверке дубликатов: {db_error}")
                return False
        else:
            # Если нет listing_id, проверяем только по task_id + item_name + price
            try:
                existing_query = select(FoundItem).where(
                    FoundItem.task_id == task.id,
                    FoundItem.item_name == item_name,
                    FoundItem.price == item_price
                )
                existing = await asyncio.wait_for(
                    db_session.execute(existing_query.limit(1)),
                    timeout=10.0  # Таймаут 10 секунд для запроса к БД
                )
                if existing.scalar_one_or_none():
                    logger.info(f"⏭️ Предмет уже существует в БД, пропускаем: {item_name} (${item_price:.2f})")
                    if task_logger:
                        task_logger.info(f"⏭️ Предмет уже существует в БД, пропускаем")
                    return False
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Таймаут при проверке дубликатов (10с), БД может быть недоступна")
                if task_logger:
                    task_logger.error(f"⏱️ Таймаут при проверке дубликатов")
                return False
            except Exception as db_error:
                logger.error(f"❌ Ошибка при проверке дубликатов: {type(db_error).__name__}: {db_error}")
                if task_logger:
                    task_logger.error(f"❌ Ошибка при проверке дубликатов: {db_error}")
                return False
        
        # Преобразуем parsed_data в JSON-сериализуемый формат
        serialized_data = _serialize_for_json(parsed_data)
        
        # Убеждаемся, что listing_id сохранен
        if listing_id and isinstance(serialized_data, dict):
            serialized_data['listing_id'] = listing_id
        
        # Создаем FoundItem
        found_item = FoundItem(
            task_id=task.id,
            item_name=item_name,
            price=item_price,
            item_data_json=json.dumps(serialized_data, ensure_ascii=False),
            market_url=item_name,
            notification_sent=False
        )
        
        try:
            db_session.add(found_item)
            await asyncio.wait_for(
                db_session.flush(),  # Получаем ID предмета
                timeout=10.0  # Таймаут 10 секунд для flush
            )
            
            # Обновляем счетчик найденных предметов в задаче
            await asyncio.wait_for(
                db_session.refresh(task),
                timeout=10.0  # Таймаут 10 секунд для refresh
            )
            task.items_found += 1
            task.total_checks += 1
            
            # Сохраняем изменения в БД
            await asyncio.wait_for(
                db_session.commit(),
                timeout=10.0  # Таймаут 10 секунд для commit
            )
            
            logger.info(f"💾 Предмет сохранен в БД: {item_name} (${item_price:.2f}), ID={found_item.id}")
            if task_logger:
                task_logger.success(f"💾 Предмет сохранен в БД: {item_name} (${item_price:.2f})")
            
            # Публикуем уведомление в Redis сразу
            if redis_service and redis_service.is_connected():
                notification_data = {
                    "type": "found_item",
                    "item_id": found_item.id,
                    "task_id": task.id,
                    "item_name": found_item.item_name,
                    "price": found_item.price,
                    "market_url": found_item.market_url,
                    "item_data_json": found_item.item_data_json,
                    "task_name": task.name
                }
                logger.info(f"📤 Публикуем уведомление в Redis канал 'found_items' для предмета {found_item.id}")
                if task_logger:
                    task_logger.info(f"📤 Публикуем уведомление в Telegram")
                
                await redis_service.publish("found_items", notification_data)
                logger.info(f"✅ Уведомление опубликовано для предмета {found_item.id}")
                if task_logger:
                    task_logger.success(f"✅ Уведомление отправлено в Telegram")
            
            return True
            
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Таймаут при сохранении предмета {item_name} в БД (10с), БД может быть недоступна или перегружена")
            if task_logger:
                task_logger.error(f"⏱️ Таймаут при сохранении")
            try:
                await asyncio.wait_for(db_session.rollback(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass
            return False
        except Exception as save_error:
            logger.error(f"❌ Ошибка при сохранении предмета {item_name} в БД: {save_error}")
            if task_logger:
                task_logger.error(f"❌ Ошибка при сохранении: {save_error}")
            try:
                await asyncio.wait_for(db_session.rollback(), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке фильтров для {item_name}: {e}")
        if task_logger:
            task_logger.error(f"❌ Ошибка при проверке фильтров: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return False


def _serialize_for_json(obj: Any) -> Any:
    """
    Рекурсивно преобразует Pydantic модели и другие объекты в JSON-сериализуемый формат.
    
    Args:
        obj: Объект для сериализации
        
    Returns:
        Сериализуемый объект
    """
    if hasattr(obj, 'model_dump'):
        # Pydantic v2
        return obj.model_dump()
    elif hasattr(obj, 'dict'):
        # Pydantic v1
        return obj.dict()
    elif isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Для других типов пытаемся преобразовать в строку
        return str(obj)

