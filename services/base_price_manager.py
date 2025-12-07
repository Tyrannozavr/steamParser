"""
Менеджер для управления кэшированием и обновлением базовых цен.
"""
import asyncio
from typing import Optional, Dict
from datetime import datetime, timedelta
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import ItemBasePrice
from parsers.base_price import BasePriceAPI


class BasePriceManager:
    """Управляет кэшированием и обновлением базовых цен."""
    
    DEFAULT_CACHE_TTL = 300  # 5 минут по умолчанию
    
    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL):
        """
        Инициализация менеджера.
        
        Args:
            cache_ttl: Время жизни кэша в секундах (по умолчанию 5 минут)
        """
        self._cache: Dict[str, ItemBasePrice] = {}
        self._cache_ttl = cache_ttl
    
    def _get_cache_key(self, item_name: str, appid: int) -> str:
        """Генерирует ключ кэша."""
        return f"{appid}:{item_name}"
    
    async def get_base_price(
        self,
        item_name: str,
        appid: int = 730,
        force_update: bool = False,
        proxy: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        proxy_manager=None
    ) -> Optional[float]:
        """
        Получает базовую цену с кэшированием.
        
        Args:
            item_name: Название предмета
            appid: ID приложения
            force_update: Принудительное обновление (игнорировать кэш)
            proxy: Прокси-сервер
            cache_ttl: Время жизни кэша в секундах (переопределяет значение по умолчанию)
            proxy_manager: ProxyManager для ротации прокси при 429 ошибках (опционально)
            
        Returns:
            Базовая цена в USD или None
        """
        cache_key = self._get_cache_key(item_name, appid)
        ttl = cache_ttl or self._cache_ttl
        
        # Проверяем кэш
        if not force_update and cache_key in self._cache:
            cached = self._cache[cache_key]
            # Проверяем, не устарела ли цена
            age = (datetime.now() - cached.last_updated).total_seconds()
            if age < ttl:
                return cached.base_price
        
        # Обновляем цену с поддержкой ротации прокси
        new_price = await BasePriceAPI.get_base_price(
            item_name,
            appid=appid,
            proxy=proxy,
            proxy_manager=proxy_manager  # Передаем proxy_manager для ротации при 429
        )
        
        if new_price is not None:
            self._cache[cache_key] = ItemBasePrice(
                item_name=item_name,
                base_price=new_price,
                last_updated=datetime.now(),
                appid=appid
            )
        
        return new_price
    
    def get_cached_price(
        self,
        item_name: str,
        appid: int = 730
    ) -> Optional[float]:
        """
        Получает базовую цену из кэша без запроса к API.
        
        Args:
            item_name: Название предмета
            appid: ID приложения
            
        Returns:
            Базовая цена из кэша или None
        """
        cache_key = self._get_cache_key(item_name, appid)
        if cache_key in self._cache:
            return self._cache[cache_key].base_price
        return None
    
    def clear_cache(self, item_name: Optional[str] = None, appid: Optional[int] = None):
        """
        Очищает кэш.
        
        Args:
            item_name: Если указано, очищает только для этого предмета
            appid: Если указано, очищает только для этого appid
        """
        if item_name and appid:
            cache_key = self._get_cache_key(item_name, appid)
            self._cache.pop(cache_key, None)
        else:
            self._cache.clear()
    
    def get_cache_info(self) -> Dict[str, any]:
        """Возвращает информацию о кэше."""
        return {
            "cached_items": len(self._cache),
            "cache_ttl": self._cache_ttl,
            "items": [
                {
                    "item_name": item.item_name,
                    "appid": item.appid,
                    "base_price": item.base_price,
                    "last_updated": item.last_updated.isoformat(),
                    "age_seconds": (datetime.now() - item.last_updated).total_seconds()
                }
                for item in self._cache.values()
            ]
        }

