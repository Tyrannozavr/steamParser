"""
Утилита для парсинга наклеек из HTML и получения их цен.
"""
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup
from core import StickerInfo
from loguru import logger


class StickerParser:
    """Класс для парсинга наклеек из HTML."""
    
    @staticmethod
    def parse_stickers_from_html(sticker_html: str, max_stickers: int = 5) -> List[StickerInfo]:
        """
        Парсит наклейки из HTML строки.
        
        Args:
            sticker_html: HTML строка с информацией о наклейках
            max_stickers: Максимальное количество наклеек для парсинга (по умолчанию 5)
            
        Returns:
            Список объектов StickerInfo
            
        Example:
            html = '<img title="Sticker: Crown (Foil)" ...>'
            stickers = StickerParser.parse_stickers_from_html(html)
            # [StickerInfo(name='Crown (Foil)', position=0, ...)]
        """
        stickers = []
        
        if not sticker_html:
            return stickers
        
        try:
            sticker_soup = BeautifulSoup(sticker_html, 'lxml')
            images = sticker_soup.find_all('img')
            
            for idx, img in enumerate(images):
                if idx >= max_stickers:
                    break
                
                title = img.get('title', '')
                if title and 'Sticker:' in title:
                    sticker_name = title.replace('Sticker: ', '').strip()
                    # Убираем проверку на дубликаты - одинаковые наклейки должны парситься
                    # (у них разные позиции, поэтому они все нужны)
                    if sticker_name and len(sticker_name) > 3:
                        stickers.append(StickerInfo(
                            position=idx,
                            name=sticker_name,
                            wear=sticker_name,
                            price=None
                        ))
        except Exception as e:
            logger.error(f"❌ Ошибка при парсинге наклеек из HTML: {e}")
        
        return stickers
    
    @staticmethod
    def parse_stickers_from_asset(asset_item: Dict[str, Any], max_stickers: int = 5) -> List[StickerInfo]:
        """
        Парсит наклейки из asset item (из render API).
        
        Args:
            asset_item: Элемент из assets (содержит descriptions)
            max_stickers: Максимальное количество наклеек для парсинга
            
        Returns:
            Список объектов StickerInfo
        """
        stickers = []
        
        if not asset_item or 'descriptions' not in asset_item:
            return stickers
        
        for desc in asset_item['descriptions']:
            if desc.get('name') == 'sticker_info':
                sticker_html = desc.get('value', '')
                if sticker_html:
                    stickers = StickerParser.parse_stickers_from_html(sticker_html, max_stickers)
                    break
        
        return stickers


class StickerPriceResolver:
    """Класс для получения цен наклеек с гибким сопоставлением."""
    
    def __init__(self, sticker_prices_api, redis_service=None, proxy_manager=None):
        """
        Args:
            sticker_prices_api: Экземпляр StickerPricesAPI или функция для получения цен
            redis_service: Сервис Redis для кэширования
            proxy_manager: Менеджер прокси
        """
        self.sticker_prices_api = sticker_prices_api
        self.redis_service = redis_service
        self.proxy_manager = proxy_manager
    
    async def get_stickers_prices(
        self,
        sticker_names: List[str],
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        delay: float = 0.3,
        use_fuzzy_matching: bool = True
    ) -> Dict[str, Optional[float]]:
        """
        Получает цены для списка наклеек с гибким сопоставлением.
        
        Args:
            sticker_names: Список названий наклеек
            appid: ID приложения
            currency: Валюта
            proxy: Прокси URL
            delay: Задержка между запросами
            use_fuzzy_matching: Использовать ли гибкое сопоставление для сопоставления результатов
            
        Returns:
            Словарь {название_наклейки: цена} или {название_наклейки: None} если цена не найдена
            
        Example:
            resolver = StickerPriceResolver(StickerPricesAPI)
            prices = await resolver.get_stickers_prices(['Crown (Foil)', 'Bosh (Holo)'])
            # {'Crown (Foil)': 540.50, 'Bosh (Holo)': 3.94}
        """
        if not sticker_names:
            return {}
        
        # Убираем дубликаты, сохраняя порядок
        unique_stickers = list(dict.fromkeys(sticker_names))
        
        # Получаем цены через API
        if hasattr(self.sticker_prices_api, 'get_stickers_prices_batch'):
            prices = await self.sticker_prices_api.get_stickers_prices_batch(
                unique_stickers,
                appid=appid,
                currency=currency,
                proxy=proxy,
                delay=delay,
                redis_service=self.redis_service,
                proxy_manager=self.proxy_manager
            )
        else:
            # Fallback: если передан callable
            prices = await self.sticker_prices_api(
                unique_stickers,
                appid=appid,
                currency=currency,
                proxy=proxy,
                delay=delay
            )
        
        # Если нужно гибкое сопоставление, применяем его для всех наклеек
        if use_fuzzy_matching:
            from core.utils.sticker_name_matcher import find_best_match
            
            # Создаем финальный словарь с ценами для всех наклеек (включая дубликаты)
            final_prices = {}
            valid_prices = {k: v for k, v in prices.items() if v is not None}
            
            for sticker_name in sticker_names:
                # Сначала проверяем точное совпадение
                if sticker_name in prices and prices[sticker_name] is not None:
                    final_prices[sticker_name] = prices[sticker_name]
                elif valid_prices:
                    # Пробуем гибкое сопоставление
                    match_result = find_best_match(sticker_name, valid_prices, min_similarity=0.7)
                    if match_result:
                        matched_name, similarity = match_result
                        final_prices[sticker_name] = valid_prices[matched_name]
                        logger.debug(f"✅ Найдено совпадение ({int(similarity*100)}%): '{sticker_name}' -> '{matched_name}'")
                    else:
                        # Пробуем более низкий порог
                        match_result = find_best_match(sticker_name, valid_prices, min_similarity=0.5)
                        if match_result:
                            matched_name, similarity = match_result
                            final_prices[sticker_name] = valid_prices[matched_name]
                            logger.debug(f"⚠️ Слабое совпадение ({int(similarity*100)}%): '{sticker_name}' -> '{matched_name}'")
                        else:
                            final_prices[sticker_name] = None
                else:
                    final_prices[sticker_name] = None
            
            return final_prices
        
        # Без гибкого сопоставления - просто возвращаем результаты для всех наклеек
        final_prices = {}
        for sticker_name in sticker_names:
            if sticker_name in prices:
                final_prices[sticker_name] = prices[sticker_name]
            else:
                final_prices[sticker_name] = None
        
        return final_prices
    
    async def calculate_total_stickers_price(
        self,
        stickers: List[StickerInfo],
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        delay: float = 0.3
    ) -> float:
        """
        Вычисляет общую цену наклеек, запрашивая цены для тех, у кого их нет.
        
        Args:
            stickers: Список объектов StickerInfo
            appid: ID приложения
            currency: Валюта
            proxy: Прокси URL
            delay: Задержка между запросами
            
        Returns:
            Общая цена всех наклеек
        """
        if not stickers:
            return 0.0
        
        # Собираем названия наклеек, для которых нет цен
        sticker_names_to_fetch = []
        for sticker in stickers:
            sticker_name = sticker.name if hasattr(sticker, 'name') and sticker.name else (sticker.wear if hasattr(sticker, 'wear') and sticker.wear else None)
            if sticker_name and (not sticker.price or sticker.price == 0):
                sticker_names_to_fetch.append(sticker_name)
        
        # Получаем цены
        if sticker_names_to_fetch:
            prices = await self.get_stickers_prices(
                sticker_names_to_fetch,
                appid=appid,
                currency=currency,
                proxy=proxy,
                delay=delay
            )
            
            # Обновляем цены в объектах наклеек
            for sticker in stickers:
                sticker_name = sticker.name if hasattr(sticker, 'name') and sticker.name else (sticker.wear if hasattr(sticker, 'wear') and sticker.wear else None)
                if sticker_name and sticker_name in prices and prices[sticker_name] is not None:
                    sticker.price = prices[sticker_name]
        
        # Вычисляем общую цену
        total_price = 0.0
        for sticker in stickers:
            if hasattr(sticker, 'price') and sticker.price and sticker.price > 0:
                total_price += sticker.price
        
        return total_price




