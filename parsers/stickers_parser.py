"""
Парсер для извлечения информации о наклейках из HTML страниц Steam Market.
"""
import re
from typing import Optional, List
from bs4 import BeautifulSoup

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import StickerInfo


class StickersParser:
    """Класс для парсинга информации о наклейках."""

    @classmethod
    def parse(cls, html: str, soup: Optional[BeautifulSoup] = None) -> List[StickerInfo]:
        """
        Извлекает информацию о наклейках из HTML страницы предмета.

        Args:
            html: HTML содержимое страницы
            soup: Опциональный BeautifulSoup объект (если уже создан)

        Returns:
            Список StickerInfo объектов с информацией о наклейках
        """
        if soup is None:
            soup = BeautifulSoup(html, 'lxml')

        stickers = []

        # ПРИОРИТЕТ 1: Ищем в g_rgAssets descriptions (там полные названия в title!)
        # Это основной источник полных названий наклеек
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and 'g_rgAssets' in script.string:
                try:
                    import json
                    patterns = [
                        re.compile(r'var g_rgAssets\s*=\s*(\{.*?\});', re.DOTALL),
                        re.compile(r'g_rgAssets\s*=\s*(\{.*?\});', re.DOTALL),
                        re.compile(r'\"g_rgAssets\"\s*:\s*(\{.*?\})', re.DOTALL),
                    ]
                    
                    data = None
                    for pattern in patterns:
                        match = pattern.search(script.string)
                        if match:
                            try:
                                data = json.loads(match.group(1))
                                break
                            except:
                                continue
                    
                    if data and '730' in data:
                        for contextid, items in data['730'].items():
                            for itemid, item in items.items():
                                if 'descriptions' in item:
                                    for desc in item['descriptions']:
                                        if desc.get('name') == 'sticker_info':
                                            sticker_html = desc.get('value', '')
                                            if sticker_html:
                                                sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                                images = sticker_soup.find_all('img')
                                                for idx, img in enumerate(images):
                                                    if idx < 5:
                                                        title = img.get('title', '')
                                                        if title and 'Sticker:' in title:
                                                            sticker_name = title.replace('Sticker: ', '').strip()
                                                            if sticker_name and len(sticker_name) > 3:
                                                                stickers.append(StickerInfo(
                                                                    position=idx,
                                                                    name=sticker_name,
                                                                    wear=sticker_name,
                                                                    price=None
                                                                ))
                                                if stickers:
                                                    break
                                    if stickers:
                                        break
                                if stickers:
                                    break
                            if stickers:
                                break
                        if stickers:
                            break
                except Exception as e:
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent.parent))
                    try:
                        from loguru import logger
                        logger.debug(f"Ошибка при парсинге g_rgAssets: {e}")
                    except:
                        pass
                if stickers:
                    break
        
        # ПРИОРИТЕТ 2: Поиск наклеек в sticker_info блоках HTML (если не нашли в g_rgAssets)
        if not stickers:
            sticker_info_blocks = soup.find_all('div', id='sticker_info') + soup.find_all('div', class_='sticker_info')
            for block in sticker_info_blocks:
                # Ищем все изображения наклеек в блоке
                images = block.find_all('img')
                for idx, img in enumerate(images):
                    if idx < 5:  # Максимум 5 позиций
                        # Пробуем получить полное название из title (основной источник)
                        title = img.get('title', '')
                        if 'Sticker:' in title:
                            sticker_name = title.replace('Sticker: ', '').strip()
                        else:
                            # Если нет title, пробуем alt
                            sticker_name = img.get('alt', '').strip()
                            # Если все еще нет, пробуем из src (извлекаем название из пути)
                            if not sticker_name and img.get('src'):
                                src = img.get('src', '')
                                # Пытаемся извлечь полное название из пути
                                # Формат может быть: .../stickers/tournament/team/year...
                                match = re.search(r'stickers/([^/]+)/([^/]+)', src, re.IGNORECASE)
                                if match:
                                    # Комбинируем tournament и team для полного названия
                                    tournament = match.group(1)
                                    team = match.group(2)
                                    sticker_name = f"{team} | {tournament}"
                                else:
                                    # Пробуем другой формат
                                    match = re.search(r'stickers/([^/]+)', src, re.IGNORECASE)
                                    if match:
                                        sticker_name = match.group(1)
                        
                        # Фильтруем слишком короткие или некорректные названия
                        if sticker_name and len(sticker_name) > 2 and sticker_name.lower() not in ['community', 'halo', 'none', 'null']:
                            stickers.append(StickerInfo(
                                position=idx,
                                name=sticker_name,  # Сохраняем полное название в name
                                wear=sticker_name,  # Используем полное название как wear
                                price=None  # Цена наклеек обычно не указана на странице
                            ))
        
        # Если не нашли в g_rgAssets и sticker_info блоках, ищем другими способами
        if not stickers:
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'g_rgAssets' in script.string:
                    try:
                        import json
                        # Ищем g_rgAssets более гибко (может быть в разных форматах)
                        patterns = [
                            re.compile(r'var g_rgAssets\s*=\s*(\{.*?\});', re.DOTALL),
                            re.compile(r'g_rgAssets\s*=\s*(\{.*?\});', re.DOTALL),
                            re.compile(r'\"g_rgAssets\"\s*:\s*(\{.*?\})', re.DOTALL),
                        ]
                        
                        data = None
                        for pattern in patterns:
                            match = pattern.search(script.string)
                            if match:
                                try:
                                    data = json.loads(match.group(1))
                                    break
                                except:
                                    continue
                        
                        if data and '730' in data:
                            # Ищем sticker_info в descriptions
                            for contextid, items in data['730'].items():
                                for itemid, item in items.items():
                                    if 'descriptions' in item:
                                        for desc in item['descriptions']:
                                            if desc.get('name') == 'sticker_info':
                                                # Парсим HTML из value
                                                sticker_html = desc.get('value', '')
                                                if sticker_html:
                                                    sticker_soup = BeautifulSoup(sticker_html, 'lxml')
                                                    # Ищем все изображения - ОБЯЗАТЕЛЬНО используем title для полных названий
                                                    images = sticker_soup.find_all('img')
                                                    for idx, img in enumerate(images):
                                                        if idx < 5:  # Максимум 5 позиций
                                                            sticker_name = None
                                                            
                                                            # КРИТИЧЕСКИ ВАЖНО: Используем ТОЛЬКО title - там полные названия!
                                                            # НЕ используем src, так как там неполные названия
                                                            title = img.get('title', '')
                                                            if title and 'Sticker:' in title:
                                                                # Извлекаем полное название после "Sticker: "
                                                                sticker_name = title.replace('Sticker: ', '').strip()
                                                                
                                                                # Фильтруем некорректные названия
                                                                invalid_names = {'community', 'halo', 'none', 'null', '', 'n/a', 'unknown', 'na'}
                                                                if sticker_name and len(sticker_name) > 3 and sticker_name.lower() not in invalid_names:
                                                                    # Проверяем, что это не путь к файлу
                                                                    if '.' in sticker_name and len(sticker_name.split('.')[-1]) <= 5:
                                                                        continue  # Пропускаем пути к файлам
                                                                    
                                                                    stickers.append(StickerInfo(
                                                                        position=idx,
                                                                        name=sticker_name,
                                                                        wear=sticker_name,  # Используем полное название из title
                                                                        price=None
                                                                    ))
                                                    if stickers:
                                                        break
                                        if stickers:
                                            break
                                    if stickers:
                                        break
                                if stickers:
                                    break
                    except Exception as e:
                        # Логируем ошибку для отладки
                        import sys
                        from pathlib import Path
                        sys.path.insert(0, str(Path(__file__).parent.parent))
                        try:
                            from loguru import logger
                            logger.debug(f"Ошибка при парсинге g_rgAssets: {e}")
                        except:
                            pass
                    if stickers:
                        break

        # Если не нашли через sticker_info, ищем другими способами
        if not stickers:
            # Поиск наклеек в HTML структуре
            sticker_elements = soup.find_all(['div', 'span'], class_=re.compile(r'sticker', re.IGNORECASE))
            
            for idx, element in enumerate(sticker_elements):
                if idx < 5:  # Максимум 5 позиций
                    sticker_info = cls._parse_sticker_element(element, idx)
                    if sticker_info:
                        stickers.append(sticker_info)

        # Альтернативный поиск: в JavaScript данных
        if not stickers:
            stickers = cls._parse_from_scripts(soup)

        # Поиск в data-атрибутах (используем только если не нашли другими способами)
        if not stickers:
            stickers = cls._parse_from_data_attributes(soup)
        
        # Фильтруем наклейки с некорректными названиями
        filtered_stickers = []
        invalid_names = {'community', 'halo', 'none', 'null', '', 'n/a', 'unknown', 'na'}
        for sticker in stickers:
            wear_value = sticker.wear or sticker.name if hasattr(sticker, 'name') else None
            if wear_value and wear_value.lower() not in invalid_names and len(wear_value) > 2:
                # Убеждаемся, что wear содержит полное название
                if not sticker.wear or len(sticker.wear) <= 2:
                    sticker.wear = wear_value
                filtered_stickers.append(sticker)
        
        return filtered_stickers

    @classmethod
    def _parse_sticker_element(cls, element: BeautifulSoup, position: int) -> Optional[StickerInfo]:
        """
        Парсит информацию о наклейке из HTML элемента.

        Args:
            element: BeautifulSoup элемент с наклейкой
            position: Позиция наклейки (0-4)

        Returns:
            StickerInfo или None
        """
        try:
            # Извлечение названия наклейки из title атрибута img
            img = element.find('img')
            sticker_name = None
            if img:
                sticker_name = img.get('title', '').replace('Sticker: ', '').strip()
            
            # Если не нашли в img, ищем в тексте
            if not sticker_name:
                name_elem = element.find(['span', 'div'], class_=re.compile(r'name|title', re.IGNORECASE))
                sticker_name = name_elem.get_text(strip=True) if name_elem else None

            # Извлечение потертости
            wear_elem = element.find(['span', 'div'], class_=re.compile(r'wear|condition', re.IGNORECASE))
            wear = wear_elem.get_text(strip=True) if wear_elem else None

            # Извлечение цены из data-атрибутов или текста
            price = None
            price_attr = element.get('data-price')
            if price_attr:
                try:
                    price = float(price_attr)
                except (ValueError, TypeError):
                    pass

            if not price:
                price_elem = element.find(['span', 'div'], class_=re.compile(r'price', re.IGNORECASE))
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    # Попытка извлечь число из текста
                    price_match = re.search(r'[\d.]+', price_text.replace(',', ''))
                    if price_match:
                        try:
                            price = float(price_match.group())
                        except ValueError:
                            pass

            # Если есть хотя бы название или позиция, создаем объект
            if sticker_name or position is not None:
                return StickerInfo(
                    position=position if position < 5 else None,
                    wear=wear or sticker_name,  # Используем название как wear, если wear не найдено
                    price=price
                )

        except Exception:
            # Игнорируем ошибки парсинга отдельных элементов
            pass

        return None

    @classmethod
    def _parse_from_scripts(cls, soup: BeautifulSoup) -> List[StickerInfo]:
        """
        Парсит наклейки из JavaScript кода на странице.

        Args:
            soup: BeautifulSoup объект страницы

        Returns:
            Список StickerInfo объектов
        """
        stickers = []
        scripts = soup.find_all('script')

        # Паттерн для поиска массивов наклеек в JavaScript
        sticker_patterns = [
            re.compile(r'["\']stickers["\']\s*:\s*\[(.*?)\]', re.IGNORECASE | re.DOTALL),
            re.compile(r'g_rgStickers\s*=\s*\[(.*?)\]', re.IGNORECASE | re.DOTALL),
        ]

        for script in scripts:
            if not script.string:
                continue

            for pattern in sticker_patterns:
                match = pattern.search(script.string)
                if match:
                    # Попытка извлечь данные о наклейках
                    stickers_data = match.group(1)
                    # Простой парсинг JSON-подобных структур
                    sticker_items = re.findall(r'\{[^}]+\}', stickers_data)
                    for idx, item in enumerate(sticker_items[:5]):  # Максимум 5 наклеек
                        sticker_info = cls._parse_sticker_json_like(item, idx)
                        if sticker_info:
                            stickers.append(sticker_info)

        return stickers

    @classmethod
    def _parse_sticker_json_like(cls, json_like: str, position: int) -> Optional[StickerInfo]:
        """
        Парсит информацию о наклейке из JSON-подобной строки.

        Args:
            json_like: JSON-подобная строка с данными наклейки
            position: Позиция наклейки

        Returns:
            StickerInfo или None
        """
        try:
            # Извлечение wear
            wear_match = re.search(r'["\']wear["\']\s*:\s*["\']?([^,"\']+)', json_like, re.IGNORECASE)
            wear = wear_match.group(1) if wear_match else None

            # Извлечение цены
            price_match = re.search(r'["\']price["\']\s*:\s*([0-9.]+)', json_like, re.IGNORECASE)
            price = None
            if price_match:
                try:
                    price = float(price_match.group(1))
                except ValueError:
                    pass

            if wear or price is not None:
                return StickerInfo(
                    position=position if position < 5 else None,
                    wear=wear,
                    price=price
                )

        except Exception:
            pass

        return None

    @classmethod
    def _parse_from_data_attributes(cls, soup: BeautifulSoup) -> List[StickerInfo]:
        """
        Парсит наклейки из data-атрибутов элементов.

        Args:
            soup: BeautifulSoup объект страницы

        Returns:
            Список StickerInfo объектов
        """
        stickers = []
        elements = soup.find_all(attrs={'data-sticker': True})

        for idx, element in enumerate(elements[:5]):  # Максимум 5 наклеек
            try:
                wear = element.get('data-sticker-wear')
                price_attr = element.get('data-sticker-price')
                price = None
                if price_attr:
                    try:
                        price = float(price_attr)
                    except ValueError:
                        pass

                if wear or price is not None:
                    stickers.append(StickerInfo(
                        position=idx if idx < 5 else None,
                        wear=wear,
                        price=price
                    ))
            except Exception:
                continue

        return stickers

    @classmethod
    def calculate_total_price(cls, stickers: List[StickerInfo]) -> float:
        """
        Вычисляет общую цену всех наклеек.

        Args:
            stickers: Список наклеек

        Returns:
            Общая цена наклеек
        """
        total = 0.0
        for sticker in stickers:
            if sticker.price is not None:
                total += sticker.price
        return total

