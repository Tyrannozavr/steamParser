"""
Сервис фильтрации предметов для Steam Market парсера.
Отвечает за проверку всех фильтров: цена, float, паттерн, наклейки.
"""
from typing import Dict, Any, Optional
from loguru import logger

from core.models import SearchFilters, ParsedItemData
from parsers.item_type_detector import detect_item_type


class FilterService:
    """Сервис для проверки соответствия предметов фильтрам."""
    
    def __init__(
        self,
        base_price_manager=None,
        proxy_manager=None,
        parser=None
    ):
        """
        Инициализация сервиса фильтрации.
        
        Args:
            base_price_manager: Менеджер базовых цен для расчета формулы наклеек
            proxy_manager: Менеджер прокси для запросов базовых цен
            parser: Парсер SteamMarketParser для получения цен наклеек (опционально)
        """
        self.base_price_manager = base_price_manager
        self.proxy_manager = proxy_manager
        self.parser = parser
    
    def check_price(
        self,
        item: Dict[str, Any],
        filters: SearchFilters
    ) -> bool:
        """
        Быстрая проверка по цене (без парсинга страницы).
        
        Args:
            item: Данные предмета из Steam API
            filters: Параметры фильтрации
            
        Returns:
            True, если предмет проходит проверку по цене
        """
        if filters.max_price is not None:
            price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
            try:
                price = float(price_text)
                if price > filters.max_price:
                    logger.debug(f"    ❌ Цена ${price:.2f} превышает максимальную ${filters.max_price:.2f}")
                    return False
                logger.debug(f"    ✅ Цена ${price:.2f} в пределах максимальной ${filters.max_price:.2f}")
            except (ValueError, AttributeError):
                logger.debug(f"    ⚠️ Не удалось распарсить цену из '{price_text}'")
        return True
    
    def check_float(
        self,
        float_value: Optional[float],
        filters: SearchFilters
    ) -> bool:
        """
        Проверка float-значения.
        
        Args:
            float_value: Float-значение предмета
            filters: Параметры фильтрации
            
        Returns:
            True, если float проходит проверку
        """
        if not filters.float_range:
            return True
        
        if float_value is None:
            logger.info(f"    ❌ Float не определен, но требуется фильтр float_range ({filters.float_range.min:.6f}-{filters.float_range.max:.6f})")
            return False
        
        # Нормализуем float_value к float для корректного сравнения
        try:
            float_value_normalized = float(float_value)
        except (ValueError, TypeError):
            logger.warning(f"    ⚠️ Не удалось нормализовать float_value {float_value} к float")
            float_value_normalized = float_value
        
        logger.info(f"    🔍 ПРОВЕРКА FLOAT: float_value={float_value} (нормализован: {float_value_normalized:.6f}), диапазон: {filters.float_range.min:.6f}-{filters.float_range.max:.6f}")
        
        if not (filters.float_range.min <= float_value_normalized <= filters.float_range.max):
            logger.info(f"    ❌ Float {float_value} (нормализован: {float_value_normalized:.6f}) не в диапазоне {filters.float_range.min:.6f}-{filters.float_range.max:.6f}")
            return False
        
        logger.info(f"    ✅ Float {float_value} (нормализован: {float_value_normalized:.6f}) в диапазоне {filters.float_range.min:.6f}-{filters.float_range.max:.6f}")
        return True
    
    def check_pattern(
        self,
        pattern: Optional[int],
        filters: SearchFilters,
        item_type: Optional[str] = None
    ) -> bool:
        """
        Проверка паттерна.
        
        Args:
            pattern: Паттерн предмета
            filters: Параметры фильтрации
            item_type: Тип предмета ('skin' или 'keychain')
            
        Returns:
            True, если паттерн проходит проверку
        """
        # Проверка паттерна (новый формат - список)
        if filters.pattern_list:
            if filters.pattern_list.item_type == "keychain" and item_type != "keychain":
                logger.debug(f"    ⚠️ Фильтр pattern_list для брелков, но предмет - скин, пропускаем фильтр по паттерну")
                return True
            elif filters.pattern_list.item_type == "skin" and item_type == "keychain":
                logger.debug(f"    ⚠️ Фильтр pattern_list для скинов, но предмет - брелок, пропускаем фильтр по паттерну")
                return True
            
            if pattern is None:
                logger.info(f"    ❌ Паттерн не определен")
                return False
            
            # Нормализуем паттерн к int для корректного сравнения
            try:
                pattern_int = int(pattern)
            except (ValueError, TypeError):
                pattern_int = pattern
            
            # Нормализуем список паттернов к int
            patterns_normalized = []
            for p in filters.pattern_list.patterns:
                try:
                    patterns_normalized.append(int(p))
                except (ValueError, TypeError):
                    patterns_normalized.append(p)
            
            logger.info(f"    🔍 ПРОВЕРКА ПАТТЕРНА: pattern={pattern} (нормализован: {pattern_int}), patterns={patterns_normalized}")
            
            if pattern_int not in patterns_normalized:
                logger.info(f"    ❌ Паттерн {pattern} (нормализован: {pattern_int}) не в списке {patterns_normalized}")
                return False
            
            logger.info(f"    ✅ Паттерн {pattern} (нормализован: {pattern_int}) найден в списке")
            return True
        
        # Проверка паттерна (старый формат - диапазон)
        if filters.pattern_range:
            if pattern is None:
                logger.debug(f"    ❌ Паттерн не определен, но требуется фильтр pattern_range")
                return False
            
            if not (filters.pattern_range.min <= pattern <= filters.pattern_range.max):
                logger.debug(f"    ❌ Паттерн {pattern} не в диапазоне")
                return False
            
            logger.debug(f"    ✅ Паттерн {pattern} в диапазоне")
            return True
        
        return True
    
    async def check_stickers(
        self,
        parsed_data: ParsedItemData,
        item: Dict[str, Any],
        filters: SearchFilters
    ) -> bool:
        """
        Проверка наклеек (минимальная стоимость и формула S = D + (P * x)).
        
        ВАЖНО: Если цены наклеек неизвестны и есть фильтр по наклейкам,
        цены будут запрошены через API (с учетом кэширования).
        
        Args:
            parsed_data: Распарсенные данные о предмете
            item: Данные предмета из Steam API
            filters: Параметры фильтрации
            
        Returns:
            True, если наклейки проходят проверку
        """
        if not filters.stickers_filter:
            return True
        
        stickers = parsed_data.stickers if parsed_data.stickers else []
        
        # Проверяем, есть ли цены на наклейках
        has_prices = any(
            hasattr(s, 'price') and s.price is not None and s.price > 0 
            for s in stickers
        )
        
        # Если цены неизвестны и есть фильтр по наклейкам - запрашиваем цены
        if not has_prices and stickers:
            if not self.parser:
                logger.warning(f"    ⚠️ Парсер не установлен, невозможно запросить цены наклеек")
                total_price = 0.0
            else:
                logger.info(f"    🏷️ Цены наклеек неизвестны, запрашиваем через парсер (с учетом кэширования)...")
                
                # Извлекаем названия наклеек
                sticker_names = []
                for s in stickers:
                    # Приоритет: name > wear, но пробуем оба варианта
                    sticker_name = None
                    if hasattr(s, 'name') and s.name:
                        sticker_name = s.name.strip()
                    elif hasattr(s, 'wear') and s.wear:
                        sticker_name = s.wear.strip()
                    
                    if sticker_name:
                        # Нормализуем название: убираем лишние пробелы, проверяем на валидность
                        sticker_name = " ".join(sticker_name.split())  # Убираем множественные пробелы
                        
                        # Фильтруем некорректные названия
                        if len(sticker_name) > 2 and sticker_name.lower() not in ['none', 'null', 'community', 'halo', '']:
                            sticker_names.append(sticker_name)
                        else:
                            logger.warning(f"    ⚠️ Пропущено некорректное название наклейки: '{sticker_name}' (слишком короткое или служебное)")
                    else:
                        logger.warning(f"    ⚠️ Наклейка без названия: position={getattr(s, 'position', None)}, name={getattr(s, 'name', None)}, wear={getattr(s, 'wear', None)}")
                
                if sticker_names:
                    # Используем метод парсера для получения цен
                    prices = await self.parser.get_stickers_prices(sticker_names, delay=0.3)
                    
                    # Обновляем цены наклеек
                    updated_count = 0
                    for sticker in stickers:
                        sticker_name = sticker.name if hasattr(sticker, 'name') and sticker.name else (sticker.wear if hasattr(sticker, 'wear') and sticker.wear else None)
                        if sticker_name and sticker_name in prices and prices[sticker_name] is not None:
                            sticker.price = prices[sticker_name]
                            updated_count += 1
                    
                    # Обновляем общую цену наклеек в parsed_data
                    total_price = sum(s.price for s in stickers if hasattr(s, 'price') and s.price and s.price > 0)
                    parsed_data.total_stickers_price = total_price
                    
                    logger.info(f"    🏷️ Обновлены цены для {updated_count} из {len(stickers)} наклеек, общая цена: ${total_price:.2f}")
                    
                    # Проверяем, сколько наклеек остались без цен
                    failed_count = len(stickers) - updated_count
                    if failed_count > 0:
                        logger.warning(f"    ⚠️ Не удалось получить цены для {failed_count} из {len(stickers)} наклеек")
                        # Логируем названия наклеек без цен для отладки
                        failed_stickers = []
                        for sticker in stickers:
                            sticker_name = sticker.name if hasattr(sticker, 'name') and sticker.name else (sticker.wear if hasattr(sticker, 'wear') and sticker.wear else None)
                            if sticker_name and (not hasattr(sticker, 'price') or not sticker.price or sticker.price <= 0):
                                failed_stickers.append(sticker_name)
                        if failed_stickers:
                            logger.warning(f"    ⚠️ Наклейки без цен: {failed_stickers[:5]}{'...' if len(failed_stickers) > 5 else ''}")
                else:
                    logger.warning(f"    ⚠️ Не удалось извлечь названия наклеек для запроса цен")
                    logger.warning(f"    ⚠️ Всего наклеек: {len(stickers)}, из них:")
                    for idx, s in enumerate(stickers[:5], 1):
                        logger.warning(f"       {idx}. position={getattr(s, 'position', None)}, name={getattr(s, 'name', None)}, wear={getattr(s, 'wear', None)}")
                    total_price = 0.0
        else:
            total_price = parsed_data.total_stickers_price if parsed_data.total_stickers_price else 0.0
        
        current_item_price = parsed_data.item_price
        
        logger.debug(f"    🔍 Проверка наклеек: наклеек={len(stickers)}, общая цена=${total_price:.2f}")
        
        # Получаем цену предмета если нет
        if current_item_price is None:
            price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
            try:
                current_item_price = float(price_text)
                logger.debug(f"    ✅ Цена предмета получена из item: ${current_item_price:.2f}")
            except (ValueError, AttributeError):
                current_item_price = None
                logger.warning(f"    ⚠️ Не удалось получить цену предмета из item")
        
        # Проверка общей цены наклеек (старый формат)
        if filters.stickers_filter.total_stickers_price_min is not None:
            if total_price < filters.stickers_filter.total_stickers_price_min:
                logger.debug(f"    ❌ Общая цена наклеек ${total_price:.2f} меньше минимальной")
                return False
            logger.debug(f"    ✅ Общая цена наклеек ${total_price:.2f} больше минимальной")
        
        if filters.stickers_filter.total_stickers_price_max is not None:
            if total_price > filters.stickers_filter.total_stickers_price_max:
                logger.debug(f"    ❌ Общая цена наклеек ${total_price:.2f} превышает максимальную")
                return False
            logger.debug(f"    ✅ Общая цена наклеек ${total_price:.2f} в пределах максимальной")
        
        # Проверка конкретных наклеек
        if filters.stickers_filter.stickers:
            if len(stickers) < len(filters.stickers_filter.stickers):
                logger.debug(f"    ❌ Количество наклеек {len(stickers)} меньше требуемого")
                return False
            logger.debug(f"    ✅ Количество наклеек {len(stickers)} соответствует требуемому")
        
        # НОВАЯ ЛОГИКА: Проверка формулы S = D + (P * x)
        # ВАЖНО: Если установлен фильтр по наклейкам (min_stickers_price или max_overpay_coefficient),
        # предметы БЕЗ наклеек должны быть отклонены
        if filters.stickers_filter.max_overpay_coefficient is not None or filters.stickers_filter.min_stickers_price is not None:
            # Если наклеек нет, но установлен фильтр - отклоняем предмет
            if len(stickers) == 0:
                logger.info(f"    ❌ Предмет без наклеек, но установлен фильтр по наклейкам (min_stickers_price или max_overpay_coefficient)")
                return False
            
            logger.info(f"    📊 Применяем формулу наклеек: S = D + (P * x)")
            
            # Проверка минимальной цены наклеек
            if filters.stickers_filter.min_stickers_price is not None:
                # Если цена наклеек = 0, это означает, что цены не были получены
                if total_price == 0.0:
                    logger.warning(f"    ⚠️ Цена наклеек равна $0.00 - цены наклеек не были получены")
                    logger.warning(f"    ⚠️ Возможные причины:")
                    logger.warning(f"       - Наклейки не найдены в API")
                    logger.warning(f"       - Ошибка при запросе цен наклеек")
                    logger.warning(f"       - Все прокси заблокированы")
                    logger.info(f"    ❌ Цена наклеек $0.00 меньше минимальной ${filters.stickers_filter.min_stickers_price:.2f}")
                    return False
                
                if total_price < filters.stickers_filter.min_stickers_price:
                    msg = f"Суммарно наклейки стоят ${total_price:.2f}, фильтр ${filters.stickers_filter.min_stickers_price:.2f} - не проходит"
                    logger.info(f"    ❌ {msg}")
                    # Пробуем получить task_logger для детального логирования
                    try:
                        from core.logger import get_task_logger
                        task_logger = get_task_logger()
                        if task_logger:
                            task_logger.info(f"❌ {msg}")
                    except:
                        pass
                    return False
                else:
                    msg = f"Суммарно наклейки стоят ${total_price:.2f}, фильтр ${filters.stickers_filter.min_stickers_price:.2f} - проходит"
                    logger.info(f"    ✅ {msg}")
                    # Пробуем получить task_logger для детального логирования
                    try:
                        from core.logger import get_task_logger
                        task_logger = get_task_logger()
                        if task_logger:
                            task_logger.info(f"✅ {msg}")
                    except:
                        pass
            
            # Проверка коэффициента переплаты
            if filters.stickers_filter.max_overpay_coefficient is not None:
                if not self.base_price_manager:
                    logger.warning(f"    ⚠️ base_price_manager не установлен, пропускаем проверку коэффициента")
                    return False
                
                logger.info(f"    🔍 Получаем базовую цену (D) для предмета: {filters.item_name}")
                
                # Получаем прокси для запроса базовой цены
                proxy_for_request = None
                if self.proxy_manager:
                    proxy_obj = await self.proxy_manager.get_next_proxy(force_refresh=False)
                    if proxy_obj:
                        proxy_for_request = proxy_obj.url
                
                base_price = await self.base_price_manager.get_base_price(
                    filters.item_name,
                    filters.appid,
                    force_update=False,
                    proxy=proxy_for_request,
                    proxy_manager=self.proxy_manager
                )
                
                if base_price is None:
                    logger.warning(f"    ⚠️ Не удалось получить базовую цену (D), пропускаем проверку коэффициента")
                    return False
                
                logger.info(f"    ✅ Базовая цена (D): ${base_price:.2f}")
                
                # Валидация данных перед расчетом
                validation_result = self._validate_prices_for_overpay_calculation(
                    current_item_price, base_price, total_price, filters.item_name
                )
                if not validation_result["valid"]:
                    logger.warning(f"    ⚠️ {validation_result['reason']}")
                    if validation_result.get("should_skip", False):
                        logger.warning(f"    ⚠️ Пропускаем проверку коэффициента из-за подозрительных данных")
                        return False
                
                if base_price is not None and current_item_price is not None and total_price > 0:
                    # Вычисляем коэффициент переплаты
                    overpay_coefficient = self._calculate_overpay_coefficient(
                        current_item_price,  # S
                        base_price,          # D
                        total_price          # P
                    )
                    
                    if overpay_coefficient is not None:
                        logger.info(f"    🧮 Вычислен коэффициент переплаты (x): {overpay_coefficient:.4f} ({overpay_coefficient * 100:.2f}%)")
                        logger.info(f"    📐 Формула: x = (S - D) / P = (${current_item_price:.2f} - ${base_price:.2f}) / ${total_price:.2f} = {overpay_coefficient:.4f}")
                        
                        # Дополнительная проверка на подозрительно большой коэффициент
                        if overpay_coefficient > 100:
                            logger.warning(f"    ⚠️ ПОДОЗРИТЕЛЬНО БОЛЬШОЙ коэффициент переплаты: {overpay_coefficient:.4f}")
                            logger.warning(f"    ⚠️ Возможные причины:")
                            logger.warning(f"       - Базовая цена слишком низкая (D=${base_price:.2f})")
                            logger.warning(f"       - Цена наклеек слишком низкая (P=${total_price:.2f})")
                            logger.warning(f"       - Цена предмета слишком высокая (S=${current_item_price:.2f})")
                            logger.warning(f"    ⚠️ Рекомендуется проверить данные вручную")
                    else:
                        logger.warning(f"    ⚠️ Не удалось вычислить коэффициент переплаты (x)")
                    
                    # Проверка максимального коэффициента переплаты
                    if overpay_coefficient is None or overpay_coefficient > filters.stickers_filter.max_overpay_coefficient:
                        logger.info(f"    ❌ Коэффициент переплаты {overpay_coefficient:.4f} превышает максимальный {filters.stickers_filter.max_overpay_coefficient:.4f}")
                        return False
                    else:
                        logger.info(f"    ✅ Коэффициент переплаты {overpay_coefficient:.4f} в пределах допустимого {filters.stickers_filter.max_overpay_coefficient:.4f}")
        
        return True
    
    def _validate_prices_for_overpay_calculation(
        self,
        current_price: Optional[float],
        base_price: Optional[float],
        stickers_price: float,
        item_name: str
    ) -> dict:
        """
        Валидирует цены перед расчетом коэффициента переплаты.
        
        Args:
            current_price: Текущая цена предмета (S)
            base_price: Базовая цена (D)
            stickers_price: Общая цена наклеек (P)
            item_name: Название предмета для логирования
            
        Returns:
            Словарь с результатом валидации:
            {
                "valid": bool,
                "reason": str,
                "should_skip": bool
            }
        """
        if current_price is None:
            return {
                "valid": False,
                "reason": "Текущая цена предмета не указана",
                "should_skip": True
            }
        
        if base_price is None:
            return {
                "valid": False,
                "reason": "Базовая цена не получена",
                "should_skip": True
            }
        
        if stickers_price <= 0:
            return {
                "valid": False,
                "reason": f"Цена наклеек равна нулю или отрицательна: ${stickers_price:.2f}",
                "should_skip": True
            }
        
        # Проверка на подозрительно низкую базовую цену для дорогих предметов
        if current_price > 100 and base_price < 1.0:
            return {
                "valid": True,
                "reason": f"⚠️ ПОДОЗРИТЕЛЬНО: Базовая цена ${base_price:.2f} слишком низкая для предмета стоимостью ${current_price:.2f}",
                "should_skip": False  # Все равно проверяем, но логируем предупреждение
            }
        
        # Проверка на подозрительно низкую цену наклеек для дорогих предметов
        if current_price > 100 and stickers_price < 0.5:
            return {
                "valid": True,
                "reason": f"⚠️ ПОДОЗРИТЕЛЬНО: Цена наклеек ${stickers_price:.2f} слишком низкая для предмета стоимостью ${current_price:.2f}",
                "should_skip": False
            }
        
        # Проверка на разумность соотношения цен
        if base_price > current_price * 2:
            return {
                "valid": True,
                "reason": f"⚠️ ПОДОЗРИТЕЛЬНО: Базовая цена ${base_price:.2f} больше чем в 2 раза превышает цену предмета ${current_price:.2f}",
                "should_skip": False
            }
        
        return {
            "valid": True,
            "reason": "Данные валидны",
            "should_skip": False
        }
    
    def _calculate_overpay_coefficient(
        self,
        current_price: float,  # S
        base_price: float,      # D
        stickers_price: float   # P
    ) -> Optional[float]:
        """
        Вычисляет коэффициент переплаты x из формулы S = D + (P * x).
        
        Args:
            current_price: Текущая цена предмета (S)
            base_price: Базовая цена (цена первого лота) (D)
            stickers_price: Общая цена наклеек (P)
            
        Returns:
            Коэффициент x или None, если невозможно вычислить
        """
        if stickers_price <= 0:
            return None
        
        if current_price < base_price:
            return 0.0
        
        x = (current_price - base_price) / stickers_price
        return x
    
    def _normalize_item_name(self, name: str, remove_condition: bool = False) -> str:
        """
        Нормализует название предмета для сравнения.
        
        Args:
            name: Название предмета
            remove_condition: Удалить состояние из названия
            
        Returns:
            Нормализованное название
        """
        if not name:
            return ""
        name = name.replace("StatTrak™", "").replace("Souvenir", "").strip()
        
        if remove_condition:
            import re
            name = re.sub(r'\s*\([^)]+\)\s*$', '', name)
        
        name = " ".join(name.split()).lower()
        return name
    
    def check_item_name(
        self,
        item: Dict[str, Any],
        filters: SearchFilters,
        parsed_data: Optional[ParsedItemData] = None
    ) -> bool:
        """
        Проверка соответствия названия предмета.
        
        Args:
            item: Данные предмета из Steam API
            filters: Параметры фильтрации
            parsed_data: Распарсенные данные о предмете (если доступны)
            
        Returns:
            True, если название совпадает
        """
        # Получаем название предмета
        item_name_from_api = item.get('asset_description', {}).get('market_hash_name', '') or item.get('name', '')
        item_name_from_parsed = parsed_data.item_name if parsed_data and parsed_data.item_name else None
        
        if parsed_data and not item_name_from_parsed:
            item_name_from_parsed = item_name_from_api
        
        # Определяем наличие состояния в названиях
        task_has_condition = '(' in filters.item_name and ')' in filters.item_name
        api_has_condition = '(' in item_name_from_api and ')' in item_name_from_api
        parsed_has_condition = item_name_from_parsed and '(' in item_name_from_parsed and ')' in item_name_from_parsed
        
        logger.debug(f"    🔍 Проверка названия предмета:")
        logger.debug(f"       Задача: '{filters.item_name}' (состояние: {task_has_condition})")
        logger.debug(f"       API: '{item_name_from_api}' (состояние: {api_has_condition})")
        if item_name_from_parsed:
            logger.debug(f"       Parsed: '{item_name_from_parsed}' (состояние: {parsed_has_condition})")
        
        # Нормализуем названия
        normalized_task_name = self._normalize_item_name(filters.item_name, remove_condition=True)
        normalized_api_name = self._normalize_item_name(item_name_from_api, remove_condition=True)
        normalized_parsed_name = self._normalize_item_name(item_name_from_parsed, remove_condition=True) if item_name_from_parsed else None
        
        logger.debug(f"       Нормализованная задача: '{normalized_task_name}'")
        logger.debug(f"       Нормализованный API: '{normalized_api_name}'")
        if normalized_parsed_name:
            logger.debug(f"       Нормализованный Parsed: '{normalized_parsed_name}'")
        
        # Проверяем соответствие названия
        name_matches = False
        if normalized_parsed_name:
            name_matches = normalized_parsed_name == normalized_task_name
            if not name_matches:
                logger.debug(f"    ❌ Название не совпадает: '{normalized_parsed_name}' != '{normalized_task_name}' (из parsed_data)")
            else:
                logger.debug(f"    ✅ Название совпадает: '{normalized_parsed_name}' == '{normalized_task_name}' (из parsed_data)")
        else:
            name_matches = normalized_api_name == normalized_task_name
            if not name_matches:
                logger.debug(f"    ❌ Название не совпадает: '{normalized_api_name}' != '{normalized_task_name}' (из API)")
            else:
                logger.debug(f"    ✅ Название совпадает: '{normalized_api_name}' == '{normalized_task_name}' (из API)")
        
        if not name_matches:
            compared_name = normalized_parsed_name if normalized_parsed_name else normalized_api_name
            compared_source = "parsed_data" if normalized_parsed_name else "API"
            logger.warning(
                f"    ⚠️ Предмет '{item_name_from_api}' не соответствует задаче '{filters.item_name}'\n"
                f"       Использовано для сравнения ({compared_source}): '{compared_name}'\n"
                f"       Задача (нормализованная): '{normalized_task_name}'\n"
                f"       API (нормализованная): '{normalized_api_name}'"
                + (f"\n       Parsed (нормализованная): '{normalized_parsed_name}'" if normalized_parsed_name else "")
            )
            return False
        
        logger.info(f"    ✅ Название предмета совпадает: '{item_name_from_api}' соответствует задаче '{filters.item_name}'")
        return True
    
    async def matches_filters(
        self,
        item: Dict[str, Any],
        filters: SearchFilters,
        parsed_data: Optional[ParsedItemData] = None
    ) -> bool:
        """
        Проверяет, соответствует ли предмет заданным фильтрам.
        Полная проверка всех фильтров: название, цена, float, паттерн, наклейки.
        
        Args:
            item: Данные предмета из Steam API
            filters: Параметры фильтрации
            parsed_data: Распарсенные данные о предмете (если доступны)
            
        Returns:
            True, если предмет соответствует всем фильтрам
        """
        logger.info(f"    🔍 Начинаем проверку фильтров для предмета:")
        logger.info(f"       - max_price: {filters.max_price}")
        logger.info(f"       - float_range: {filters.float_range.min if filters.float_range else None}-{filters.float_range.max if filters.float_range else None}")
        logger.info(f"       - pattern_list: {filters.pattern_list.patterns if filters.pattern_list else None} ({filters.pattern_list.item_type if filters.pattern_list else None})")
        logger.info(f"       - pattern_range: {filters.pattern_range.min if filters.pattern_range else None}-{filters.pattern_range.max if filters.pattern_range else None}")
        logger.info(f"       - stickers_filter: {filters.stickers_filter is not None}")
        if parsed_data:
            logger.info(f"       - parsed_data: float={parsed_data.float_value}, pattern={parsed_data.pattern}, stickers={len(parsed_data.stickers) if parsed_data.stickers else 0}")
        else:
            logger.info(f"       - parsed_data: None")
        
        # 1. Проверка названия предмета
        if not self.check_item_name(item, filters, parsed_data):
            return False
        
        # 2. Проверка максимальной цены
        if not self.check_price(item, filters):
            price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
            logger.info(f"    ❌ Предмет не прошел проверку по цене: ${price_text} > ${filters.max_price:.2f}")
            return False
        
        # Если нет распарсенных данных, но они нужны для фильтров
        if parsed_data is None:
            if filters.float_range or filters.pattern_range or filters.pattern_list or filters.stickers_filter:
                required_filters = []
                if filters.float_range:
                    required_filters.append(f"float_range ({filters.float_range.min}-{filters.float_range.max})")
                if filters.pattern_range:
                    required_filters.append(f"pattern_range ({filters.pattern_range.min}-{filters.pattern_range.max})")
                if filters.pattern_list:
                    required_filters.append(f"pattern_list ({len(filters.pattern_list.patterns)} паттернов)")
                if filters.stickers_filter:
                    required_filters.append("stickers_filter")
                logger.debug(f"    ❌ Нет распарсенных данных, но требуются фильтры: {', '.join(required_filters)}")
                return False
            logger.debug(f"    ✅ Нет распарсенных данных, но фильтры не требуют парсинга - предмет проходит")
            return True
        
        # Определяем тип предмета
        item_type = parsed_data.item_type if parsed_data.item_type else None
        if item_type is None:
            item_type = detect_item_type(
                filters.item_name,
                parsed_data.float_value is not None,
                len(parsed_data.stickers) > 0 if parsed_data.stickers else False
            )
            logger.debug(f"    🔍 Определен тип предмета: {item_type}")
        elif item_type:
            logger.debug(f"    🔍 Тип предмета из parsed_data: {item_type}")
        
        # Для брелков: проверяем только паттерн и цену
        if item_type == "keychain":
            if filters.float_range:
                logger.debug(f"    ❌ Брелок не может иметь float, но требуется фильтр float_range")
                return False
            
            if filters.stickers_filter:
                logger.debug(f"    ❌ Брелок не может иметь наклейки, но требуется фильтр stickers_filter")
                return False
            
            # Проверяем паттерн для брелков
            if not self.check_pattern(parsed_data.pattern, filters, item_type):
                return False
            
            logger.debug(f"    ✅ Все фильтры для брелка пройдены успешно")
            return True
        
        # Для скинов: полная проверка всех фильтров
        
        # 3. Проверка float-значения
        if not self.check_float(parsed_data.float_value, filters):
            return False
        
        # 4. Проверка паттерна
        if not self.check_pattern(parsed_data.pattern, filters, item_type):
            return False
        
        # 5. Проверка наклеек
        if not await self.check_stickers(parsed_data, item, filters):
            return False
        
        # Все проверки пройдены
        logger.debug(f"    ✅ Все фильтры пройдены успешно")
        return True

