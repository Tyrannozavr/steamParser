"""
Парсер для извлечения float-значений предметов из HTML страниц Steam Market.
"""
import re
from typing import Optional
from bs4 import BeautifulSoup


class FloatParser:
    """Класс для парсинга float-значений предметов."""

    # Паттерны для поиска float в JavaScript коде
    FLOAT_PATTERNS = [
        # Вариант 1: var g_rgItemInfo = {"wear": 0.123456}
        re.compile(r'["\']wear["\']\s*:\s*([0-9]+\.[0-9]+)', re.IGNORECASE),
        # Вариант 2: "floatvalue": "0.123456"
        re.compile(r'["\']floatvalue["\']\s*:\s*["\']?([0-9]+\.[0-9]+)', re.IGNORECASE),
        # Вариант 3: "float": 0.123456
        re.compile(r'["\']float["\']\s*:\s*([0-9]+\.[0-9]+)', re.IGNORECASE),
        # Вариант 4: g_rgItemInfo = {..., "wear": 0.123456, ...} (многострочный)
        re.compile(r'g_rgItemInfo\s*=\s*\{[^}]*["\']wear["\']\s*:\s*([0-9]+\.[0-9]+)', re.IGNORECASE | re.DOTALL),
        # Вариант 5: В JSON структурах (более широкий поиск)
        re.compile(r'["\']wear["\']\s*:\s*([0-9]+\.[0-9]+)', re.IGNORECASE | re.DOTALL),
        # Вариант 6: В data-атрибутах
        re.compile(r'data-float=["\']([0-9]+\.[0-9]+)', re.IGNORECASE),
        # Вариант 7: В описании предмета
        re.compile(r'Float:\s*([0-9]+\.[0-9]+)', re.IGNORECASE),
        # Вариант 8: В переменных типа var wear = 0.123456
        re.compile(r'(?:var|let|const)\s+\w*[Ww]ear\w*\s*=\s*([0-9]+\.[0-9]+)', re.IGNORECASE),
        # Вариант 9: В объектах типа {wear: 0.123456} или {wear: "0.123456"}
        re.compile(r'\{[^}]*wear\s*:\s*["\']?([0-9]+\.[0-9]+)', re.IGNORECASE | re.DOTALL),
    ]

    @classmethod
    def parse(cls, html: str, soup: Optional[BeautifulSoup] = None) -> Optional[float]:
        """
        Извлекает float-значение из HTML страницы предмета.

        Args:
            html: HTML содержимое страницы
            soup: Опциональный BeautifulSoup объект (если уже создан)

        Returns:
            Float-значение (0.0 - 1.0) или None, если не найдено
        """
        if soup is None:
            soup = BeautifulSoup(html, 'lxml')

        # Поиск в JavaScript коде
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                script_text = script.string
                # Сначала попробуем найти JSON структуры с float
                # Ищем объекты типа g_rgListingInfo или подобные
                json_patterns = [
                    re.compile(r'g_rgListingInfo\s*=\s*(\{.*?\});', re.IGNORECASE | re.DOTALL),
                    re.compile(r'g_rgItemInfo\s*=\s*(\{.*?\});', re.IGNORECASE | re.DOTALL),
                    re.compile(r'Market_LoadOrderSpread\s*\([^)]*(\{.*?\})\)', re.IGNORECASE | re.DOTALL),
                ]
                
                for json_pattern in json_patterns:
                    json_match = json_pattern.search(script_text)
                    if json_match:
                        try:
                            import json
                            json_str = json_match.group(1)
                            # Пытаемся распарсить JSON
                            json_data = json.loads(json_str)
                            float_val = cls.parse_from_json_data(json_data)
                            if float_val is not None:
                                return float_val
                        except (json.JSONDecodeError, AttributeError, IndexError):
                            pass
                
                # Обычный поиск по паттернам
                for pattern in cls.FLOAT_PATTERNS:
                    match = pattern.search(script_text)
                    if match:
                        try:
                            float_value = float(match.group(1))
                            # Проверяем, что значение в допустимом диапазоне
                            if 0.0 <= float_value <= 1.0:
                                return float_value
                        except (ValueError, IndexError):
                            continue

        # Поиск в data-атрибутах элементов
        elements_with_float = soup.find_all(attrs={'data-float': True})
        for element in elements_with_float:
            float_attr = element.get('data-float')
            if float_attr:
                try:
                    float_value = float(float_attr)
                    if 0.0 <= float_value <= 1.0:
                        return float_value
                except ValueError:
                    continue

        # Поиск в тексте страницы (описание предмета)
        description = soup.find('div', class_='market_listing_item_name')
        if description:
            text = description.get_text()
            for pattern in cls.FLOAT_PATTERNS:
                match = pattern.search(text)
                if match:
                    try:
                        float_value = float(match.group(1))
                        if 0.0 <= float_value <= 1.0:
                            return float_value
                    except (ValueError, IndexError):
                        continue

        # Поиск в g_rgAssets descriptions (может быть в некоторых случаях)
        for script in scripts:
            if script.string and 'g_rgAssets' in script.string:
                try:
                    import json
                    match = re.search(r'var g_rgAssets = (\{.*?\});', script.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        # Рекурсивный поиск float в JSON
                        float_val = cls._find_float_in_dict(data)
                        if float_val is not None:
                            return float_val
                except:
                    pass

        return None

    @classmethod
    def _find_float_in_dict(cls, obj, max_depth=5):
        """Рекурсивно ищет float значение в словаре."""
        if max_depth <= 0:
            return None
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ['wear', 'float', 'floatvalue'] and isinstance(value, (int, float, str)):
                    try:
                        float_val = float(value)
                        if 0.0 <= float_val <= 1.0:
                            return float_val
                    except:
                        pass
                if isinstance(value, (dict, list)):
                    result = cls._find_float_in_dict(value, max_depth - 1)
                    if result is not None:
                        return result
        elif isinstance(obj, list):
            for item in obj:
                result = cls._find_float_in_dict(item, max_depth - 1)
                if result is not None:
                    return result
        
        return None

    @classmethod
    def parse_from_json_data(cls, json_data: dict) -> Optional[float]:
        """
        Извлекает float из JSON данных (если доступны).

        Args:
            json_data: Словарь с данными предмета

        Returns:
            Float-значение или None
        """
        # Попробуем различные ключи, которые могут содержать float
        possible_keys = ['wear', 'float', 'floatvalue', 'float_value', 'wear_value']
        
        for key in possible_keys:
            if key in json_data:
                try:
                    value = json_data[key]
                    if isinstance(value, (int, float)):
                        float_value = float(value)
                        if 0.0 <= float_value <= 1.0:
                            return float_value
                    elif isinstance(value, str):
                        float_value = float(value)
                        if 0.0 <= float_value <= 1.0:
                            return float_value
                except (ValueError, TypeError):
                    continue

        return None

