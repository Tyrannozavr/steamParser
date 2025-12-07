"""
Логика фильтрации предметов для Steam Market парсера.
"""
from typing import Dict, Any, Optional
from loguru import logger

from .models import SearchFilters, ParsedItemData
from parsers.item_type_detector import detect_item_type


class SteamFilterMatcher:
    """Класс для проверки соответствия предметов фильтрам."""
    
    @staticmethod
    def matches_price_filter(item: Dict[str, Any], filters: SearchFilters) -> bool:
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
                    return False
            except (ValueError, AttributeError):
                pass
        return True

    @staticmethod
    async def matches_filters(
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
        # Проверка максимальной цены (уже проверено в _matches_price_filter, но для надежности)
        if not SteamFilterMatcher.matches_price_filter(item, filters):
            return False

        # Определяем тип предмета
        item_type = parsed_data.item_type if parsed_data and parsed_data.item_type else None
        if item_type is None and parsed_data:
            item_type = detect_item_type(
                filters.item_name,
                parsed_data.float_value is not None,
                len(parsed_data.stickers) > 0
            )
        
        # Если нет распарсенных данных, но они нужны для фильтров, предмет не проходит фильтр
        if parsed_data is None:
            # Если есть фильтры, требующие парсинга, но данных нет - предмет не проходит
            if filters.float_range or filters.pattern_range or filters.pattern_list or filters.stickers_filter:
                logger.debug(f"    ❌ Нет распарсенных данных, но требуются фильтры")
                return False
            # Если фильтров нет, предмет проходит (но данных не будет в уведомлении)
            return True

        # Для брелков: проверяем только паттерн и цену (нет float и наклеек)
        if item_type == "keychain":
            # Проверка паттерна для брелков
            if filters.pattern_list:
                if parsed_data.pattern is None:
                    return False
                if parsed_data.pattern not in filters.pattern_list.patterns:
                    return False
            elif filters.pattern_range:
                if parsed_data.pattern is None:
                    return False
                if not (filters.pattern_range.min <= parsed_data.pattern <= filters.pattern_range.max):
                    return False
            
            # Для брелков не проверяем float и наклейки
            return True

        # Проверка float-значения
        if filters.float_range:
            if parsed_data.float_value is None:
                return False
            if not (filters.float_range.min <= parsed_data.float_value <= filters.float_range.max):
                return False

        # Проверка паттерна
        if filters.pattern_list:
            if parsed_data.pattern is None:
                return False
            if parsed_data.pattern not in filters.pattern_list.patterns:
                return False
        elif filters.pattern_range:
            if parsed_data.pattern is None:
                return False
            if not (filters.pattern_range.min <= parsed_data.pattern <= filters.pattern_range.max):
                return False

        # Проверка наклеек
        # ВАЖНО: Фильтр по наклейкам применяется только если:
        # 1. У предмета есть наклейки ИЛИ
        # 2. Явно указано минимальное количество наклеек (min_stickers_count > 0)
        # Это позволяет находить предметы с нужным паттерном как с наклейками, так и без них
        if filters.stickers_filter:
            stickers = parsed_data.stickers or []
            has_stickers = len(stickers) > 0
            
            # Проверка минимального количества наклеек
            # Если min_stickers_count указан и > 0, то предметы без наклеек не проходят
            # Если min_stickers_count = 0 или None, предметы без наклеек проходят
            if filters.stickers_filter.min_stickers_count is not None:
                if filters.stickers_filter.min_stickers_count > 0:
                    # Требуется минимум N наклеек
                    if len(stickers) < filters.stickers_filter.min_stickers_count:
                        return False
                # Если min_stickers_count = 0, предметы без наклеек тоже проходят
            
            # Проверка минимальной цены наклеек
            # Применяется только если есть наклейки
            if filters.stickers_filter.min_stickers_price is not None:
                if has_stickers:
                    total_stickers_price = parsed_data.total_stickers_price or 0.0
                    if total_stickers_price < filters.stickers_filter.min_stickers_price:
                        return False
                # Если наклеек нет, но min_stickers_price указан - предмет проходит
                # (так как пользователь может искать предметы с паттерном как с наклейками, так и без)
            
            # Проверка коэффициента переплаты за наклейки
            # Применяется только если есть наклейки
            if filters.stickers_filter.max_overpay_coefficient is not None:
                if has_stickers:
                    logger.warning(
                        "⚠️ SteamFilterMatcher: Фильтр по коэффициенту переплаты требует BasePriceManager. "
                        "Используйте FilterService вместо SteamFilterMatcher для правильной работы фильтра по наклейкам. "
                        "Фильтр пропущен - предмет не прошел проверку."
                    )
                    # SteamFilterMatcher не имеет доступа к BasePriceManager, поэтому не может правильно
                    # вычислить базовую цену. Для правильной работы фильтра по наклейкам необходимо
                    # использовать FilterService, который инициализируется с base_price_manager.
                    return False
                # Если наклеек нет, предмет проходит (так как переплаты за наклейки нет)

        return True

