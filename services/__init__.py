"""
Сервисы приложения.
"""
# Импортируем без циклических зависимостей
from .proxy_manager import ProxyManager
from .base_price_manager import BasePriceManager
from .parsing_service import ParsingService
from .results_processor_service import ResultsProcessorService

__all__ = [
    'MonitoringService',
    'ProxyManager',
    'BasePriceManager',
    'ParsingService',
    'ResultsProcessorService',
]

# Ленивый импорт MonitoringService, так как он импортирует core
def __getattr__(name):
    if name == 'MonitoringService':
        from .monitoring_service import MonitoringService
        return MonitoringService
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

