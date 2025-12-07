"""
Основные модули приложения.
"""
# Импортируем только базовые модули без циклических зависимостей
from .config import Config
from .database import DatabaseManager, Proxy, MonitoringTask, FoundItem, AppSettings
from .models import (
    SearchFilters, FloatRange, PatternList, PatternRange,
    StickersFilter, StickerInfo, ParsedItemData, ItemBasePrice
)

# SteamMarketParser импортируем лениво, чтобы избежать циклических импортов
__all__ = [
    'Config',
    'DatabaseManager',
    'Proxy',
    'MonitoringTask',
    'FoundItem',
    'AppSettings',
    'SearchFilters',
    'FloatRange',
    'PatternList',
    'PatternRange',
    'StickersFilter',
    'StickerInfo',
    'ParsedItemData',
    'ItemBasePrice',
    'SteamMarketParser',
]

# Ленивый импорт для избежания циклических зависимостей
def _lazy_import_steam_parser():
    from .steam_parser import SteamMarketParser
    return SteamMarketParser

# Добавляем в глобальное пространство имен при первом обращении
def __getattr__(name):
    if name == 'SteamMarketParser':
        return _lazy_import_steam_parser()
    if name == 'test_single_request':
        # Функция test_single_request была удалена, возвращаем None
        return None
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

