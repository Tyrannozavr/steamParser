"""
Парсер для извлечения паттернов (pattern index) предметов из HTML страниц Steam Market.
"""
import re
from typing import Optional
from bs4 import BeautifulSoup


class PatternParser:
    """Класс для парсинга паттернов предметов."""

    # Паттерны для поиска pattern index в JavaScript коде
    PATTERN_PATTERNS = [
        # Вариант 1: var g_rgItemInfo = {"paintseed": 123}
        re.compile(r'["\']paintseed["\']\s*:\s*([0-9]+)', re.IGNORECASE),
        # Вариант 2: "pattern": 123
        re.compile(r'["\']pattern["\']\s*:\s*([0-9]+)', re.IGNORECASE),
        # Вариант 3: "patternindex": 123
        re.compile(r'["\']patternindex["\']\s*:\s*([0-9]+)', re.IGNORECASE),
        # Вариант 4: g_rgItemInfo = {..., "paintseed": 123, ...}
        re.compile(r'g_rgItemInfo\s*=\s*\{[^}]*["\']paintseed["\']\s*:\s*([0-9]+)', re.IGNORECASE | re.DOTALL),
        # Вариант 5: В data-атрибутах
        re.compile(r'data-pattern=["\']([0-9]+)', re.IGNORECASE),
        re.compile(r'data-paintseed=["\']([0-9]+)', re.IGNORECASE),
        # Вариант 6: В описании предмета
        re.compile(r'Pattern:\s*#?([0-9]+)', re.IGNORECASE),  # Поддержка формата "Pattern: #460"
        re.compile(r'Paint Seed:\s*([0-9]+)', re.IGNORECASE),
    ]

    @classmethod
    def parse(cls, html: str, soup: Optional[BeautifulSoup] = None) -> Optional[int]:
        """
        Извлекает паттерн (pattern index) из HTML страницы предмета.

        Args:
            html: HTML содержимое страницы
            soup: Опциональный BeautifulSoup объект (если уже создан)

        Returns:
            Pattern index (0-999 для скинов, 0-99999 для брелков) или None
        """
        if soup is None:
            soup = BeautifulSoup(html, 'lxml')

        # Поиск в JavaScript коде
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                script_text = script.string
                # Сначала попробуем найти JSON структуры с паттерном
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
                            pattern_val = cls.parse_from_json_data(json_data)
                            if pattern_val is not None:
                                return pattern_val
                        except (json.JSONDecodeError, AttributeError, IndexError):
                            pass
                
                # Обычный поиск по паттернам
                for pattern in cls.PATTERN_PATTERNS:
                    match = pattern.search(script_text)
                    if match:
                        try:
                            pattern_value = int(match.group(1))
                            # Проверяем, что значение в допустимом диапазоне
                            if 0 <= pattern_value <= 99999:
                                return pattern_value
                        except (ValueError, IndexError):
                            continue

        # Поиск в data-атрибутах элементов
        for attr_name in ['data-pattern', 'data-paintseed', 'data-pattern-index']:
            elements = soup.find_all(attrs={attr_name: True})
            for element in elements:
                pattern_attr = element.get(attr_name)
                if pattern_attr:
                    try:
                        pattern_value = int(pattern_attr)
                        if 0 <= pattern_value <= 99999:
                            return pattern_value
                    except ValueError:
                        continue

        # Поиск в элементе cs2-pattern-copyable (расширение браузера)
        pattern_element = soup.find('div', class_='cs2-pattern-copyable')
        if pattern_element:
            text = pattern_element.get_text()
            # Ищем паттерн в формате "Pattern: #460" или "Pattern: 460"
            pattern_match = re.search(r'Pattern:\s*#?(\d+)', text, re.IGNORECASE)
            if pattern_match:
                try:
                    pattern_value = int(pattern_match.group(1))
                    if 0 <= pattern_value <= 99999:
                        return pattern_value
                except (ValueError, IndexError):
                    pass

        # Поиск в тексте страницы (описание предмета)
        description = soup.find('div', class_='market_listing_item_name')
        if description:
            text = description.get_text()
            for pattern in cls.PATTERN_PATTERNS:
                match = pattern.search(text)
                if match:
                    try:
                        pattern_value = int(match.group(1))
                        if 0 <= pattern_value <= 99999:
                            return pattern_value
                    except (ValueError, IndexError):
                        continue

        # Поиск в g_rgAssets (может быть в некоторых случаях)
        for script in scripts:
            if script.string and 'g_rgAssets' in script.string:
                try:
                    import json
                    match = re.search(r'var g_rgAssets = (\{.*?\});', script.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        # Рекурсивный поиск паттерна в JSON
                        pattern_val = cls._find_pattern_in_dict(data)
                        if pattern_val is not None:
                            return pattern_val
                except:
                    pass

        return None

    @classmethod
    def _find_pattern_in_dict(cls, obj, max_depth=5):
        """Рекурсивно ищет паттерн в словаре."""
        if max_depth <= 0:
            return None
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ['paintseed', 'pattern', 'patternindex'] and isinstance(value, (int, str)):
                    try:
                        pattern_val = int(value)
                        if 0 <= pattern_val <= 99999:
                            return pattern_val
                    except:
                        pass
                if isinstance(value, (dict, list)):
                    result = cls._find_pattern_in_dict(value, max_depth - 1)
                    if result is not None:
                        return result
        elif isinstance(obj, list):
            for item in obj:
                result = cls._find_pattern_in_dict(item, max_depth - 1)
                if result is not None:
                    return result
        
        return None

    @classmethod
    def parse_from_json_data(cls, json_data: dict) -> Optional[int]:
        """
        Извлекает паттерн из JSON данных (если доступны).

        Args:
            json_data: Словарь с данными предмета

        Returns:
            Pattern index или None
        """
        # Попробуем различные ключи, которые могут содержать паттерн
        possible_keys = ['paintseed', 'pattern', 'patternindex', 'pattern_index', 'paint_seed']
        
        for key in possible_keys:
            if key in json_data:
                try:
                    value = json_data[key]
                    if isinstance(value, (int, str)):
                        pattern_value = int(value)
                        if 0 <= pattern_value <= 99999:
                            return pattern_value
                except (ValueError, TypeError):
                    continue

        return None

