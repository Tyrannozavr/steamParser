"""
Модуль для определения типа предмета (скин или брелок).
"""
from typing import Optional


def detect_item_type(
    item_name: str,
    has_float: bool = False,
    has_stickers: bool = False
) -> str:
    """
    Определяет тип предмета: скин или брелок.
    
    Правила:
    - Если есть float или наклейки → скин
    - Если в названии есть "keychain" или "key chain" → брелок
    - Если нет float и нет наклеек → вероятно брелок
    - По умолчанию считаем скином
    
    Args:
        item_name: Название предмета
        has_float: Есть ли float-значение
        has_stickers: Есть ли наклейки
        
    Returns:
        "skin" или "keychain"
    """
    item_name_lower = item_name.lower()
    
    # Явные признаки брелка
    if "keychain" in item_name_lower or "key chain" in item_name_lower or "charm" in item_name_lower:
        return "keychain"
    
    # Если есть float или наклейки - точно скин
    if has_float or has_stickers:
        return "skin"
    
    # Если нет float и нет наклеек - проверяем дополнительные признаки брелка
    # Брелки обычно имеют паттерны больше 999 (0-99999)
    # Но без парсинга паттерна мы не можем это определить точно
    
    # Если нет float и нет наклеек - вероятно брелок
    # Но по умолчанию считаем скином (на всякий случай)
    # ВАЖНО: Для точного определения нужен паттерн, который парсится позже
    return "skin"


def is_keychain(item_name: str, has_float: bool = False, has_stickers: bool = False) -> bool:
    """
    Проверяет, является ли предмет брелком.
    
    Args:
        item_name: Название предмета
        has_float: Есть ли float-значение
        has_stickers: Есть ли наклейки
        
    Returns:
        True если предмет - брелок
    """
    return detect_item_type(item_name, has_float, has_stickers) == "keychain"


def is_skin(item_name: str, has_float: bool = False, has_stickers: bool = False) -> bool:
    """
    Проверяет, является ли предмет скином.
    
    Args:
        item_name: Название предмета
        has_float: Есть ли float-значение
        has_stickers: Есть ли наклейки
        
    Returns:
        True если предмет - скин
    """
    return detect_item_type(item_name, has_float, has_stickers) == "skin"

