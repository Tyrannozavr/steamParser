"""
Основной парсер для извлечения всех данных о предмете из HTML страницы Steam Market.
"""
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

from .float_parser import FloatParser
from .pattern_parser import PatternParser
from .stickers_parser import StickersParser
from .sticker_prices import StickerPricesAPI
from .item_prices import ItemPricesAPI
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import StickerInfo


class ItemPageParser:
    """Основной класс для парсинга страницы предмета Steam Market."""

    def __init__(self, html: str):
        """
        Инициализация парсера.

        Args:
            html: HTML содержимое страницы предмета
        """
        self.html = html
        self.soup = BeautifulSoup(html, 'lxml')
        self._cached_data: Optional[Dict[str, Any]] = None

    async def parse_all(
        self,
        fetch_sticker_prices: bool = False,
        fetch_item_price: bool = False,
        proxy: Optional[str] = None,
        redis_service=None,
        proxy_manager=None
    ) -> Dict[str, Any]:
        """
        Парсит все доступные данные о предмете.

        Args:
            fetch_sticker_prices: Если True, получает цены наклеек через API
            fetch_item_price: Если True, получает цену предмета через API
            proxy: Опциональный прокси для запросов API

        Returns:
            Словарь с данными:
            - float_value: Optional[float] - float-значение
            - pattern: Optional[int] - паттерн предмета
            - stickers: List[StickerInfo] - список наклеек
            - total_stickers_price: float - общая цена наклеек
            - item_price_from_api: Optional[float] - цена предмета из API
        """
        if self._cached_data is not None:
            return self._cached_data

        float_value = FloatParser.parse(self.html, self.soup)
        pattern = PatternParser.parse(self.html, self.soup)
        stickers = StickersParser.parse(self.html, self.soup)
        
        # Если нужно получить цены наклеек через API
        from loguru import logger
        if fetch_sticker_prices and stickers:
            # Используем name или wear для получения названия наклейки
            sticker_names = [s.name or s.wear for s in stickers if s.name or s.wear]
            logger.info(f"🔍 ItemPageParser: Найдено {len(stickers)} наклеек, названий: {len(sticker_names)}")
            if sticker_names:
                logger.info(f"🔍 ItemPageParser: Получаем цены для {len(sticker_names)} наклеек: {sticker_names[:3]}...")
                prices = await StickerPricesAPI.get_stickers_prices_batch(
                    sticker_names, proxy=proxy, delay=0.3, redis_service=redis_service, proxy_manager=proxy_manager
                )
                logger.debug(f"📊 ItemPageParser: Получено цен: {len(prices)}, примеры: {dict(list(prices.items())[:2]) if prices else 'нет'}")
                # Обновляем цены наклеек
                updated_count = 0
                for sticker in stickers:
                    sticker_name = sticker.name or sticker.wear
                    if sticker_name and sticker_name in prices:
                        if prices[sticker_name] is not None:
                            sticker.price = prices[sticker_name]
                            updated_count += 1
                            logger.debug(f"    💰 Наклейка '{sticker_name}': ${prices[sticker_name]:.2f}")
                logger.info(f"✅ ItemPageParser: Обновлено цен для {updated_count} из {len(stickers)} наклеек")
            else:
                logger.warning(f"⚠️ ItemPageParser: Нет названий наклеек для получения цен (наклеек: {len(stickers)})")
        
        total_stickers_price = StickersParser.calculate_total_price(stickers)
        from loguru import logger
        logger.info(f"💰 ItemPageParser: Общая цена наклеек: ${total_stickers_price:.2f} (наклеек: {len(stickers)})")
        
        # Получаем цену предмета через API, если нужно
        item_price_from_api = None
        if fetch_item_price:
            item_name = self.get_item_name()
            if item_name:
                # Очищаем название от лишнего
                clean_name = item_name.split(">")[-1].strip()
                prices_data = await ItemPricesAPI.get_item_price(clean_name, proxy=proxy)
                if prices_data:
                    # Используем цену со Steam или самую низкую
                    item_price_from_api = ItemPricesAPI.get_steam_price(prices_data)
                    if item_price_from_api is None:
                        item_price_from_api = ItemPricesAPI.get_lowest_price(prices_data)

        self._cached_data = {
            'float_value': float_value,
            'pattern': pattern,
            'stickers': stickers,
            'total_stickers_price': total_stickers_price,
            'item_price_from_api': item_price_from_api,
        }

        return self._cached_data

    def parse_float(self) -> Optional[float]:
        """
        Парсит только float-значение.

        Returns:
            Float-значение или None
        """
        return FloatParser.parse(self.html, self.soup)

    def parse_pattern(self) -> Optional[int]:
        """
        Парсит только паттерн.

        Returns:
            Pattern index или None
        """
        return PatternParser.parse(self.html, self.soup)

    def parse_stickers(self) -> list[StickerInfo]:
        """
        Парсит только информацию о наклейках.

        Returns:
            Список StickerInfo объектов
        """
        return StickersParser.parse(self.html, self.soup)

    def get_item_name(self) -> Optional[str]:
        """
        Извлекает название предмета со страницы.

        Returns:
            Название предмета или None
        """
        # Поиск в различных местах страницы
        name_selectors = [
            'div.market_listing_item_name',
            'h1.market_listing_item_name',
            'div.item_name',
            'h1.item_name',
            'div.market_listing_nav',
        ]

        for selector in name_selectors:
            element = self.soup.select_one(selector)
            if element:
                name = element.get_text(strip=True)
                if name:
                    return name

        return None

    def is_stattrak(self) -> bool:
        """
        Определяет, является ли предмет StatTrak по названию.
        
        Returns:
            True, если предмет является StatTrak
        """
        item_name = self.get_item_name()
        if not item_name:
            return False
        
        # StatTrak определяется по наличию "StatTrak" или "StatTrak™" в названии
        # Также может быть символ ★ (звездочка) перед StatTrak
        import re
        stat_trak_patterns = [
            r'StatTrak',
            r'StatTrak™',
            r'★\s*StatTrak',
            r'StatTrak\s*™',
        ]
        
        for pattern in stat_trak_patterns:
            if re.search(pattern, item_name, re.IGNORECASE):
                return True
        
        return False

    def get_item_price(self) -> Optional[float]:
        """
        Извлекает цену предмета со страницы.
        Ищет цену конкретного лота, а не общую цену предмета.

        Returns:
            Цена предмета или None
        """
        import re

        # Поиск цены в различных местах страницы
        # ПРИОРИТЕТ: цена с комиссией (market_listing_price_with_fee) - это цена, которую видит пользователь
        price_selectors = [
            # Цена с комиссией (приоритет) - это цена, которую видит пользователь
            'div.market_listing_row .market_listing_price_with_fee',
            'div.market_listing_largeimage .market_listing_price_with_fee',
            'span.market_listing_price_with_fee',
            'div.market_listing_price_with_fee',
            # Цена конкретного лота (в списке лотов) - fallback
            'div.market_listing_row .market_listing_price',
            'div.market_listing_row .normal_price',
            # Цена на странице конкретного предмета - fallback
            'div.market_listing_largeimage .market_listing_price',
            # Общие селекторы (fallback)
            'span.market_listing_price',
            'div.market_listing_price',
            'span.normal_price',
            'div.normal_price',
        ]

        for selector in price_selectors:
            elements = self.soup.select(selector)
            # Если найдено несколько элементов, берем первый (обычно это цена конкретного лота)
            if elements:
                element = elements[0]
                price_text = element.get_text(strip=True)
                # Извлечение числа из текста (может быть формат "$36.60" или "36.60 USD")
                # Убираем все нечисловые символы кроме точки
                price_match = re.search(r'[\d.]+', price_text.replace(',', '').replace('$', '').replace('USD', ''))
                if price_match:
                    try:
                        price = float(price_match.group())
                        # Проверяем, что цена разумная (больше 0 и меньше 100000)
                        if 0 < price < 100000:
                            from loguru import logger
                            logger.debug(f"    💰 ItemPageParser.get_item_price: найдена цена ${price:.2f} через селектор '{selector}'")
                            return price
                    except ValueError:
                        continue

        return None

    def get_inspect_links(self) -> list[str]:
        """
        Извлекает все inspect in game ссылки со страницы.

        Returns:
            Список inspect ссылок
        """
        import re
        from loguru import logger
        links = []
        
        # Ищем все ссылки с csgo_econ_action_preview
        inspect_elements = self.soup.find_all('a', href=re.compile(r'csgo_econ_action_preview'))
        for element in inspect_elements:
            href = element.get('href')
            if href:
                links.append(href)
        
        # Также ищем в JavaScript коде (часто inspect ссылки там)
        script_tags = self.soup.find_all('script')
        for script in script_tags:
            if script.string:
                # Ищем steam://rungame ссылки
                matches = re.findall(r'steam://rungame/\d+/\d+/\+csgo_econ_action_preview[^\s"\']+', script.string)
                links.extend(matches)
        
        # Удаляем дубликаты
        links = list(dict.fromkeys(links))
        
        if links:
            logger.info(f"    📎 ItemPageParser: Найдено {len(links)} inspect ссылок")
            logger.debug(f"    📎 Первая ссылка: {links[0][:100]}...")
        else:
            logger.warning(f"    ⚠️ ItemPageParser: Inspect ссылки не найдены на странице")
        
        return links

    def get_all_listings(self) -> list[Dict[str, Any]]:
        """
        Извлекает все лоты со страницы с их ценами и inspect ссылками.
        Каждый лот имеет свою цену и inspect ссылку.

        Returns:
            Список словарей с данными о каждом лоте:
            - price: float - цена лота
            - inspect_link: str - inspect ссылка лота
            - listing_id: Optional[str] - ID лота (если удалось извлечь)
            - row_element: BeautifulSoup - элемент строки лота (для дополнительного парсинга)
        """
        import re
        from loguru import logger
        
        listings = []
        
        # Ищем все строки с лотами на странице
        listing_rows = self.soup.find_all('div', class_='market_listing_row')
        
        if not listing_rows:
            # Если нет строк с лотами, возможно это страница одного предмета
            # Пробуем найти цену и inspect ссылку на странице
            price = self.get_item_price()
            inspect_links = self.get_inspect_links()
            if price and inspect_links:
                # Извлекаем listing_id из inspect ссылки
                listing_id = None
                if inspect_links:
                    from parsers.inspect_parser import InspectLinkParser
                    inspect_params = InspectLinkParser.parse_inspect_link(inspect_links[0])
                    listing_id = inspect_params.get('listingid') if inspect_params else None
                
                listings.append({
                    'price': price,
                    'inspect_link': inspect_links[0],
                    'listing_id': listing_id,
                    'row_element': None
                })
                logger.info(f"    📋 ItemPageParser: Найден 1 лот на странице предмета (цена: ${price:.2f})")
            return listings
        
        logger.info(f"    📋 ItemPageParser: Найдено {len(listing_rows)} лотов на странице")
        
        # Для каждой строки лота извлекаем цену и inspect ссылку
        for idx, row in enumerate(listing_rows):
            # Извлекаем цену из строки лота
            # ПРИОРИТЕТ: цена с комиссией (market_listing_price_with_fee) - это цена, которую видит пользователь
            price = None
            # Сначала ищем цену с комиссией (это цена, которую видит пользователь)
            price_with_fee = row.select_one('.market_listing_price_with_fee')
            if price_with_fee:
                price_text = price_with_fee.get_text(strip=True)
                price_match = re.search(r'[\d.]+', price_text.replace(',', '').replace('$', '').replace('USD', ''))
                if price_match:
                    try:
                        price = float(price_match.group())
                        if 0 < price < 100000:
                            logger.debug(f"    💰 Лот [{idx + 1}]: найдена цена с комиссией: ${price:.2f}")
                    except ValueError:
                        pass
            
            # Если не нашли цену с комиссией, пробуем другие варианты
            if price is None:
                price_elements = row.select('.market_listing_price, .normal_price')
                for price_elem in price_elements:
                    price_text = price_elem.get_text(strip=True)
                    price_match = re.search(r'[\d.]+', price_text.replace(',', '').replace('$', '').replace('USD', ''))
                    if price_match:
                        try:
                            price = float(price_match.group())
                            if 0 < price < 100000:
                                logger.debug(f"    💰 Лот [{idx + 1}]: найдена цена (fallback): ${price:.2f}")
                                break
                        except ValueError:
                            continue
            
            # Извлекаем inspect ссылку из строки лота
            inspect_link = None
            inspect_elem = row.find('a', href=re.compile(r'csgo_econ_action_preview'))
            if inspect_elem:
                inspect_link = inspect_elem.get('href')
            else:
                # Пробуем найти в JavaScript коде внутри строки
                scripts = row.find_all('script')
                for script in scripts:
                    if script.string:
                        matches = re.findall(r'steam://rungame/\d+/\d+/\+csgo_econ_action_preview[^\s"\']+', script.string)
                        if matches:
                            inspect_link = matches[0]
                            break
            
            # Извлекаем listing_id из inspect ссылки
            listing_id = None
            if inspect_link:
                from parsers.inspect_parser import InspectLinkParser
                inspect_params = InspectLinkParser.parse_inspect_link(inspect_link)
                listing_id = inspect_params.get('listingid') if inspect_params else None
            
            # Если не нашли в inspect ссылке, пробуем извлечь из атрибута id элемента
            if not listing_id:
                row_id = row.get('id', '')
                if row_id and row_id.startswith('listing_'):
                    listing_id = row_id.replace('listing_', '')
                    logger.debug(f"    📋 Лот [{idx + 1}]: listing_id извлечен из атрибута id: {listing_id}")
                else:
                    # Пробуем извлечь из класса (формат: listing_733651971153157038)
                    row_classes = row.get('class', [])
                    for class_name in row_classes:
                        if class_name.startswith('listing_'):
                            listing_id = class_name.replace('listing_', '')
                            logger.debug(f"    📋 Лот [{idx + 1}]: listing_id извлечен из класса: {listing_id}")
                            break
            
            # Добавляем лот, если есть цена И (inspect ссылка ИЛИ listing_id)
            # Это позволяет обрабатывать лоты с listing_id, но без inspect ссылки
            # (паттерн можно будет получить со страницы лота)
            if price and (inspect_link or listing_id):
                listings.append({
                    'price': price,
                    'inspect_link': inspect_link,  # Может быть None
                    'listing_id': listing_id,
                    'row_element': row
                })
                logger.debug(f"    📋 Лот [{idx + 1}]: цена ${price:.2f}, listing_id={listing_id}, inspect={bool(inspect_link)}")
            else:
                logger.warning(f"    ⚠️ Лот [{idx + 1}]: не удалось извлечь цену или (inspect ссылку/listing_id) (цена={price}, inspect={bool(inspect_link)}, listing_id={listing_id})")
        
        logger.info(f"    ✅ ItemPageParser: Извлечено {len(listings)} лотов с полными данными из {len(listing_rows)} строк")
        return listings
    
    def get_total_listings_count(self) -> Optional[int]:
        """
        Определяет общее количество лотов на всех страницах.
        Ищет текст типа "Showing 1-10 of 114 results" на странице.
        
        Returns:
            Общее количество лотов или None, если не удалось определить
        """
        import re
        from loguru import logger
        
        # Ищем текст с количеством результатов
        # Варианты: "Showing 1-10 of 114 results", "Показано 1-10 из 114 результатов"
        patterns = [
            r'Showing\s+\d+-\d+\s+of\s+(\d+)\s+results',
            r'Показано\s+\d+-\d+\s+из\s+(\d+)\s+результатов',
            r'of\s+(\d+)\s+results',
            r'из\s+(\d+)\s+результатов',
        ]
        
        page_text = self.soup.get_text()
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                total_count = int(match.group(1))
                logger.debug(f"    📊 ItemPageParser: Найдено общее количество лотов: {total_count}")
                return total_count
        
        # Если не нашли в тексте, проверяем количество найденных лотов
        # Если на странице 10 лотов, возможно есть еще страницы
        listings = self.get_all_listings()
        if len(listings) == 10:
            # На странице ровно 10 лотов - возможно есть еще страницы
            logger.debug(f"    📊 ItemPageParser: На странице 10 лотов, возможно есть еще страницы")
            return None  # Не знаем точное количество, но есть пагинация
        
        logger.debug(f"    📊 ItemPageParser: Не удалось определить общее количество лотов")
        return None

