"""
Модуль с методами фильтрации для SteamMarketParser.
Вынесено из steam_parser.py для улучшения структуры кода.
"""
from typing import Dict, Any, Optional
from loguru import logger
from .models import SearchFilters, ParsedItemData
from parsers.item_type_detector import detect_item_type


class SteamFilterMethods:
    """Миксин с методами фильтрации."""
    
    def _matches_price_filter(self, item: Dict[str, Any], filters: SearchFilters) -> bool:
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
    
    async def _matches_filters(
        self,
        item: Dict[str, Any],
        filters: SearchFilters,
        parsed_data: Optional[ParsedItemData] = None
    ) -> bool:
        """
        Проверяет, соответствует ли предмет заданным фильтрам.

        Args:
            item: Данные предмета из Steam API
            filters: Параметры фильтрации
            parsed_data: Распарсенные данные о предмете (если доступны)

        Returns:
            True, если предмет соответствует фильтрам
        """
        logger.info(f"    🔍 Начинаем проверку фильтров для предмета:")
        logger.info(f"       - max_price: {filters.max_price}")
        logger.info(f"       - float_range: {filters.float_range.min if filters.float_range else None}-{filters.float_range.max if filters.float_range else None}")
        logger.info(f"       - pattern_list: {filters.pattern_list.patterns if filters.pattern_list else None} ({filters.pattern_list.item_type if filters.pattern_list else None})")
        logger.info(f"       - pattern_range: {filters.pattern_range.min if filters.pattern_range else None}-{filters.pattern_range.max if filters.pattern_range else None}")
        logger.info(f"       - stickers_filter: {filters.stickers_filter is not None}")
        if parsed_data:
            logger.info(f"       - parsed_data: float={parsed_data.float_value}, pattern={parsed_data.pattern}, stickers={len(parsed_data.stickers) if parsed_data.stickers else 0}")
            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для паттерна 896
            if parsed_data.pattern == 896:
                logger.info(f"    🎯🎯🎯 ПРОВЕРКА ФИЛЬТРОВ: паттерн 896 обнаружен в parsed_data!")
        else:
            logger.info(f"       - parsed_data: None")
        
        # Нормализация названия для сравнения
        def normalize_item_name(name: str, remove_condition: bool = False) -> str:
            if not name:
                return ""
            name = name.replace("StatTrak™", "").replace("Souvenir", "").strip()
            
            if remove_condition:
                import re
                name = re.sub(r'\s*\([^)]+\)\s*$', '', name)
            
            name = " ".join(name.split()).lower()
            return name
        
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
        normalized_task_name = normalize_item_name(filters.item_name, remove_condition=True)
        normalized_api_name = normalize_item_name(item_name_from_api, remove_condition=True)
        normalized_parsed_name = normalize_item_name(item_name_from_parsed, remove_condition=True) if item_name_from_parsed else None
        
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
        
        # Проверка максимальной цены
        if not self._matches_price_filter(item, filters):
            price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
            logger.info(f"    ❌ Предмет не прошел проверку по цене: ${price_text} > ${filters.max_price:.2f}")
            return False

        # Определяем тип предмета
        item_type = parsed_data.item_type if parsed_data and parsed_data.item_type else None
        if item_type is None and parsed_data:
            item_type = detect_item_type(
                filters.item_name,
                parsed_data.float_value is not None,
                len(parsed_data.stickers) > 0 if parsed_data.stickers else False
            )
            logger.debug(f"    🔍 Определен тип предмета: {item_type}")
        elif item_type:
            logger.debug(f"    🔍 Тип предмета из parsed_data: {item_type}")
        
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

        # Для брелков: проверяем только паттерн и цену
        if item_type == "keychain":
            if filters.float_range:
                logger.debug(f"    ❌ Брелок не может иметь float, но требуется фильтр float_range")
                return False
            
            if filters.stickers_filter:
                logger.debug(f"    ❌ Брелок не может иметь наклейки, но требуется фильтр stickers_filter")
                return False
            
            # Проверяем паттерн для брелков
            if filters.pattern_list:
                if filters.pattern_list.item_type == "skin":
                    logger.debug(f"    ⚠️ Фильтр pattern_list для скинов, но предмет - брелок, пропускаем фильтр по паттерну")
                else:
                    if parsed_data.pattern is None:
                        logger.debug(f"    ❌ Брелок: паттерн не определен")
                        return False
                    if parsed_data.pattern not in filters.pattern_list.patterns:
                        logger.debug(f"    ❌ Брелок: паттерн {parsed_data.pattern} не в списке {filters.pattern_list.patterns}")
                        return False
                    logger.debug(f"    ✅ Брелок: паттерн {parsed_data.pattern} найден в списке")
            
            if filters.pattern_range:
                if parsed_data.pattern is None:
                    logger.debug(f"    ❌ Брелок: паттерн не определен")
                    return False
                pattern = parsed_data.pattern
                if not (filters.pattern_range.min <= pattern <= filters.pattern_range.max):
                    logger.debug(f"    ❌ Брелок: паттерн {pattern} не в диапазоне")
                    return False
                logger.debug(f"    ✅ Брелок: паттерн {pattern} в диапазоне")
            
            logger.debug(f"    ✅ Все фильтры для брелка пройдены успешно")
            return True

        # Для скинов: полная проверка всех фильтров
        
        # Проверка float-значения
        if filters.float_range:
            if parsed_data.float_value is None:
                logger.info(f"    ❌ Float не определен, но требуется фильтр float_range ({filters.float_range.min:.6f}-{filters.float_range.max:.6f})")
                return False
            float_value = parsed_data.float_value
            logger.info(f"    🔍 ПРОВЕРКА FLOAT: float_value={float_value} (тип: {type(float_value).__name__}), диапазон: {filters.float_range.min:.6f}-{filters.float_range.max:.6f}")
            
            # ВАЖНО: Нормализуем float_value к float для корректного сравнения
            try:
                float_value_normalized = float(float_value) if float_value is not None else None
            except (ValueError, TypeError):
                float_value_normalized = float_value
                logger.warning(f"    ⚠️ Не удалось нормализовать float_value {float_value} к float")
            
            # Специальное логирование для float в диапазоне 0.22-0.26
            if float_value_normalized and 0.22 <= float_value_normalized <= 0.26:
                logger.info(f"    🎯🎯🎯 ПРОВЕРКА FLOAT в диапазоне 0.22-0.26:")
                logger.info(f"       float_value={float_value} (тип: {type(float_value).__name__})")
                logger.info(f"       float_value_normalized={float_value_normalized} (тип: {type(float_value_normalized).__name__})")
                logger.info(f"       filters.float_range.min={filters.float_range.min:.6f}")
                logger.info(f"       filters.float_range.max={filters.float_range.max:.6f}")
                logger.info(f"       Проверка: {filters.float_range.min:.6f} <= {float_value_normalized:.6f} <= {filters.float_range.max:.6f}")
                logger.info(f"       Результат: {filters.float_range.min <= float_value_normalized <= filters.float_range.max}")
            
            if not (filters.float_range.min <= float_value_normalized <= filters.float_range.max):
                logger.info(f"    ❌ Float {float_value} (нормализован: {float_value_normalized:.6f}) не в диапазоне {filters.float_range.min:.6f}-{filters.float_range.max:.6f}")
                logger.info(f"       Проверка: {filters.float_range.min:.6f} <= {float_value_normalized:.6f} <= {filters.float_range.max:.6f} = False")
                return False
            logger.info(f"    ✅ Float {float_value} (нормализован: {float_value_normalized:.6f}) в диапазоне {filters.float_range.min:.6f}-{filters.float_range.max:.6f}")

        # Проверка паттерна (новый формат - список)
        if filters.pattern_list:
            if filters.pattern_list.item_type == "keychain":
                logger.debug(f"    ⚠️ Фильтр pattern_list для брелков, но предмет - скин, пропускаем фильтр по паттерну")
            else:
                if parsed_data.pattern is None:
                    logger.info(f"    ❌ Скин: паттерн не определен")
                    return False
                pattern = parsed_data.pattern
                # ВАЖНО: Нормализуем паттерн к int для корректного сравнения
                try:
                    pattern_int = int(pattern) if pattern is not None else None
                except (ValueError, TypeError):
                    pattern_int = pattern
                
                # Нормализуем список паттернов к int
                patterns_normalized = []
                for p in filters.pattern_list.patterns:
                    try:
                        patterns_normalized.append(int(p))
                    except (ValueError, TypeError):
                        patterns_normalized.append(p)
                
                logger.info(f"    🔍 ПРОВЕРКА ПАТТЕРНА: pattern={pattern} (тип: {type(pattern).__name__}, нормализован: {pattern_int}), patterns={filters.pattern_list.patterns} (нормализованы: {patterns_normalized})")
                
                # Специальное логирование для паттерна 142
                if pattern_int == 142 or pattern == 142 or str(pattern) == "142":
                    logger.info(f"    🎯🎯🎯 ПРОВЕРКА ПАТТЕРНА 142:")
                    logger.info(f"       pattern={pattern} (тип: {type(pattern).__name__})")
                    logger.info(f"       pattern_int={pattern_int} (тип: {type(pattern_int).__name__})")
                    logger.info(f"       patterns={filters.pattern_list.patterns}")
                    logger.info(f"       patterns_normalized={patterns_normalized}")
                    logger.info(f"       pattern_int in patterns_normalized: {pattern_int in patterns_normalized}")
                
                if pattern_int not in patterns_normalized:
                    logger.info(f"    ❌ Скин: паттерн {pattern} (нормализован: {pattern_int}, тип: {type(pattern_int).__name__}) не в списке {patterns_normalized} (типы: {[type(p).__name__ for p in patterns_normalized]})")
                    return False
                logger.info(f"    ✅ Скин: паттерн {pattern} (нормализован: {pattern_int}) найден в списке")

        # Проверка паттерна (старый формат - диапазон)
        if filters.pattern_range:
            if parsed_data.pattern is None:
                logger.debug(f"    ❌ Паттерн не определен, но требуется фильтр pattern_range")
                return False
            pattern = parsed_data.pattern
            if not (filters.pattern_range.min <= pattern <= filters.pattern_range.max):
                logger.debug(f"    ❌ Паттерн {pattern} не в диапазоне")
                return False
            logger.debug(f"    ✅ Паттерн {pattern} в диапазоне")

        # Проверка наклеек
        if filters.stickers_filter:
            if parsed_data is None:
                logger.warning(f"    ⚠️ parsed_data is None, но есть фильтр по наклейкам")
                return False
            
            stickers = parsed_data.stickers if parsed_data.stickers else []
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
            if filters.stickers_filter.max_overpay_coefficient is not None or filters.stickers_filter.min_stickers_price is not None:
                logger.info(f"    📊 Применяем формулу наклеек: S = D + (P * x)")
                
                # Проверка минимальной цены наклеек
                if filters.stickers_filter.min_stickers_price is not None:
                    if total_price < filters.stickers_filter.min_stickers_price:
                        logger.info(f"    ❌ Цена наклеек ${total_price:.2f} меньше минимальной ${filters.stickers_filter.min_stickers_price:.2f}")
                        return False
                    else:
                        logger.info(f"    ✅ Цена наклеек ${total_price:.2f} больше минимальной ${filters.stickers_filter.min_stickers_price:.2f}")
                
                # Проверка коэффициента переплаты
                if filters.stickers_filter.max_overpay_coefficient is not None:
                    logger.info(f"    🔍 Получаем базовую цену (D) для предмета: {filters.item_name}")
                    base_price = await self._get_base_price_for_item(
                        filters.item_name,
                        filters.appid
                    )
                    
                    if base_price is None:
                        logger.warning(f"    ⚠️ Не удалось получить базовую цену (D), пропускаем проверку коэффициента")
                        return False
                    
                    logger.info(f"    ✅ Базовая цена (D): ${base_price:.2f}")
                    
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
                        else:
                            logger.warning(f"    ⚠️ Не удалось вычислить коэффициент переплаты (x)")
                        
                        # Проверка максимального коэффициента переплаты
                        if filters.stickers_filter.max_overpay_coefficient is not None:
                            if overpay_coefficient is None or overpay_coefficient > filters.stickers_filter.max_overpay_coefficient:
                                logger.info(f"    ❌ Коэффициент переплаты {overpay_coefficient:.4f} превышает максимальный {filters.stickers_filter.max_overpay_coefficient:.4f}")
                                return False
                            else:
                                logger.info(f"    ✅ Коэффициент переплаты {overpay_coefficient:.4f} в пределах допустимого {filters.stickers_filter.max_overpay_coefficient:.4f}")

        # Все проверки пройдены
        logger.debug(f"    ✅ Все фильтры пройдены успешно")
        return True
    
    async def _get_base_price_for_item(
        self,
        item_name: str,
        appid: int,
        force_update: bool = False
    ) -> Optional[float]:
        """
        Получает базовую цену через менеджер с поддержкой ротации прокси.
        
        Args:
            item_name: Название предмета
            appid: ID приложения
            force_update: Принудительное обновление
            
        Returns:
            Базовая цена в USD или None
        """
        proxy_for_request = self.proxy
        if self.proxy_manager:
            proxy_obj = await self.proxy_manager.get_next_proxy(force_refresh=False)
            if proxy_obj:
                proxy_for_request = proxy_obj.url
        
        return await self.base_price_manager.get_base_price(
            item_name,
            appid,
            force_update=force_update,
            proxy=proxy_for_request,
            proxy_manager=self.proxy_manager
        )
    
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
