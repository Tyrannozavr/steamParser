"""
Сервис для парсинга данных предметов Steam Market.
Извлекает float, pattern, stickers и другие данные из HTML и JavaScript.
"""
import re
import json
from typing import List, Dict, Any, Optional, NamedTuple
from bs4 import BeautifulSoup
from loguru import logger


class ParsedItemData(NamedTuple):
    """Данные распарсенного предмета."""
    listing_id: str
    price: float
    float_value: Optional[float] = None
    pattern: Optional[int] = None
    stickers: Optional[List[Dict[str, Any]]] = None
    market_hash_name: Optional[str] = None
    asset_id: Optional[str] = None


class ItemDataParser:
    """Парсер данных предметов Steam Market."""
    
    def parse_from_full_page(self, html: str) -> List[ParsedItemData]:
        """
        Парсит данные предметов с полной страницы Steam Market.
        Извлекает JavaScript переменные g_rgAssets и g_rgListingInfo.
        
        Args:
            html: HTML код полной страницы Steam Market
            
        Returns:
            Список распарсенных предметов
        """
        try:
            # Извлекаем JavaScript данные
            assets_data = self._extract_js_variable(html, 'g_rgAssets')
            listing_data = self._extract_js_variable(html, 'g_rgListingInfo')
            
            if not assets_data or not listing_data:
                logger.warning("⚠️ Не найдены JavaScript данные g_rgAssets или g_rgListingInfo")
                return []
            
            logger.info(f"✅ Извлечены данные: {len(listing_data)} лотов, {self._count_assets(assets_data)} предметов")
            
            # Парсим данные
            parsed_items = []
            
            for listing_id, listing_info in listing_data.items():
                try:
                    # Основные данные лота
                    price = listing_info.get('price', 0) / 100.0  # Цена в центах
                    asset_info = listing_info.get('asset', {})
                    asset_id = asset_info.get('id')
                    
                    if not asset_id:
                        continue
                    
                    # Ищем соответствующий asset
                    asset_data = self._find_asset_by_id(assets_data, asset_id)
                    if not asset_data:
                        logger.debug(f"⚠️ Asset {asset_id} не найден для лота {listing_id}")
                        continue
                    
                    # Извлекаем данные предмета
                    float_value, pattern, stickers = self._parse_asset_data(asset_data)
                    market_hash_name = asset_data.get('market_hash_name')
                    
                    # Создаем ParsedItemData
                    parsed_item = ParsedItemData(
                        listing_id=listing_id,
                        price=price,
                        float_value=float_value,
                        pattern=pattern,
                        stickers=stickers,
                        market_hash_name=market_hash_name,
                        asset_id=asset_id
                    )
                    
                    parsed_items.append(parsed_item)
                    
                    # Логируем найденные данные
                    if float_value is not None or pattern is not None:
                        logger.info(f"✅ Лот {listing_id}: Price=${price:.2f}, Float={float_value}, Pattern={pattern}")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка парсинга лота {listing_id}: {e}")
                    continue
            
            logger.info(f"📊 Успешно распарсено {len(parsed_items)} лотов")
            return parsed_items
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга страницы: {e}")
            return []
    
    def parse_from_render_api(self, html: str, assets: Dict[str, Any], listinginfo: Optional[Dict[str, Any]] = None) -> List[ParsedItemData]:
        """
        Парсит данные из render API (HTML + assets).
        Используется для пагинации.
        
        Args:
            html: HTML строка с лотами
            assets: Словарь assets из API (формат: assets['730'][contextid][asset_id])
            listinginfo: Словарь listinginfo из API (формат: listinginfo[listing_id]['asset']['id'])
            
        Returns:
            Список распарсенных предметов
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            listing_rows = soup.find_all('div', class_='market_listing_row')
            logger.info(f"🔍 Найдено {len(listing_rows)} лотов в HTML")
            
            # Создаем карту asset_id -> данные для быстрого поиска
            assets_data_map = {}
            if assets and '730' in assets:
                app_assets = assets['730']
                for contextid, items in app_assets.items():
                    for asset_id, item in items.items():
                        asset_id_str = str(asset_id)
                        # Парсим данные из asset
                        float_value, pattern, stickers = self._parse_asset_data_from_render(item)
                        market_hash_name = item.get('market_hash_name')
                        
                        assets_data_map[asset_id_str] = {
                            'float_value': float_value,
                            'pattern': pattern,
                            'stickers': stickers,
                            'market_hash_name': market_hash_name,
                            'contextid': contextid
                        }
            
            logger.info(f"📊 Создана карта assets: {len(assets_data_map)} записей")
            
            parsed_items = []
            
            for i, row in enumerate(listing_rows):
                try:
                    # Извлекаем ID лота
                    listing_id = row.get('id', '').replace('listing_', '')
                    if not listing_id:
                        continue
                    
                    # Извлекаем цену
                    price = self._extract_price_from_html(row)
                    
                    # Ищем данные в assets через listinginfo
                    float_value, pattern, stickers = None, None, None
                    market_hash_name = None
                    asset_id = None
                    
                    # Связываем listing_id с asset_id через listinginfo
                    if listinginfo and listing_id in listinginfo:
                        listing_data = listinginfo[listing_id]
                        if 'asset' in listing_data:
                            asset_info = listing_data['asset']
                            asset_id = asset_info.get('id')
                            if asset_id:
                                asset_id = str(asset_id)
                                
                                # Ищем данные в assets_data_map
                                if asset_id in assets_data_map:
                                    asset_data = assets_data_map[asset_id]
                                    float_value = asset_data.get('float_value')
                                    pattern = asset_data.get('pattern')
                                    stickers = asset_data.get('stickers')
                                    market_hash_name = asset_data.get('market_hash_name')
                                    logger.debug(f"✅ Лот {listing_id}: Найдены данные через asset_id={asset_id}")
                                else:
                                    logger.debug(f"⚠️ Лот {listing_id}: asset_id={asset_id} не найден в assets_data_map")
                    else:
                        logger.debug(f"⚠️ Лот {listing_id}: не найден в listinginfo")
                    
                    parsed_item = ParsedItemData(
                        listing_id=listing_id,
                        price=price,
                        float_value=float_value,
                        pattern=pattern,
                        stickers=stickers,
                        market_hash_name=market_hash_name,
                        asset_id=asset_id
                    )
                    
                    parsed_items.append(parsed_item)
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка парсинга лота {i+1}: {e}")
                    continue
            
            logger.info(f"📊 Успешно распарсено {len(parsed_items)} лотов из render API")
            return parsed_items
            
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга render API: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _extract_js_variable(self, html: str, var_name: str) -> Optional[Dict[str, Any]]:
        """Извлекает JavaScript переменную из HTML."""
        try:
            pattern = rf'{var_name}\s*=\s*({{.*?}});'
            match = re.search(pattern, html, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return None
        except (json.JSONDecodeError, AttributeError) as e:
            logger.error(f"❌ Ошибка извлечения {var_name}: {e}")
            return None
    
    def _count_assets(self, assets_data: Dict[str, Any]) -> int:
        """Подсчитывает общее количество assets."""
        total = 0
        for app_data in assets_data.values():
            for context_data in app_data.values():
                total += len(context_data)
        return total
    
    def _find_asset_by_id(self, assets_data: Dict[str, Any], asset_id: str) -> Optional[Dict[str, Any]]:
        """Находит asset по ID."""
        for app_data in assets_data.values():
            for context_data in app_data.values():
                if asset_id in context_data:
                    return context_data[asset_id]
        return None
    
    def _parse_asset_data(self, asset_data: Dict[str, Any]) -> tuple[Optional[float], Optional[int], Optional[List[Dict[str, Any]]]]:
        """
        Парсит данные asset для извлечения float, pattern и stickers.
        Используется для полной страницы (g_rgAssets).
        
        Returns:
            Tuple (float_value, pattern, stickers)
        """
        float_value = None
        pattern = None
        stickers = []
        
        descriptions = asset_data.get('descriptions', [])
        
        for desc in descriptions:
            desc_value = desc.get('value', '')
            
            # Поиск float значения
            float_match = re.search(r'Float Value:\s*([\d.]+)', desc_value)
            if float_match:
                float_value = float(float_match.group(1))
            
            # Поиск pattern
            pattern_match = re.search(r'Pattern:\s*(\d+)', desc_value)
            if pattern_match:
                pattern = int(pattern_match.group(1))
            
            # Поиск stickers
            if 'sticker' in desc_value.lower():
                sticker_info = self._parse_sticker_info(desc_value)
                if sticker_info:
                    stickers.append(sticker_info)
        
        return float_value, pattern, stickers if stickers else None
    
    def _parse_asset_data_from_render(self, asset_data: Dict[str, Any]) -> tuple[Optional[float], Optional[int], Optional[List[Dict[str, Any]]]]:
        """
        Парсит данные asset из render API для извлечения float, pattern и stickers.
        Используется для render API (assets из JSON ответа).
        
        Args:
            asset_data: Данные asset из render API (содержит asset_properties и descriptions)
            
        Returns:
            Tuple (float_value, pattern, stickers)
        """
        float_value = None
        pattern = None
        stickers = []
        
        # Парсим asset_properties для паттерна и float
        if 'asset_properties' in asset_data:
            props = asset_data['asset_properties']
            for prop in props:
                prop_id = prop.get('propertyid')
                # propertyid=1 для скинов, propertyid=3 для брелков
                if (prop_id == 1 or prop_id == 3) and pattern is None:
                    pattern = prop.get('int_value')
                    if pattern is not None:
                        try:
                            pattern = int(pattern)
                        except (ValueError, TypeError):
                            pass
                elif prop_id == 2:
                    float_value_raw = prop.get('float_value')
                    if float_value_raw is not None:
                        try:
                            float_value = float(float_value_raw)
                        except (ValueError, TypeError):
                            pass
        
        # Парсим descriptions для наклеек
        if 'descriptions' in asset_data:
            for desc in asset_data['descriptions']:
                desc_name = desc.get('name', '')
                if desc_name == 'sticker_info':
                    sticker_html = desc.get('value', '')
                    if sticker_html:
                        sticker_info = self._parse_sticker_info_from_html(sticker_html)
                        if sticker_info:
                            stickers.extend(sticker_info)
        
        return float_value, pattern, stickers if stickers else None
    
    def _parse_sticker_info(self, sticker_html: str) -> Optional[Dict[str, Any]]:
        """Парсит информацию о стикере из HTML (для полной страницы)."""
        try:
            # Простой парсинг названия стикера
            name_match = re.search(r'Sticker:\s*([^<]+)', sticker_html)
            if name_match:
                return {
                    'name': name_match.group(1).strip(),
                    'html': sticker_html
                }
        except Exception as e:
            logger.debug(f"Ошибка парсинга стикера: {e}")
        return None
    
    def _parse_sticker_info_from_html(self, sticker_html: str) -> List[Dict[str, Any]]:
        """Парсит информацию о наклейках из HTML (для render API)."""
        stickers = []
        try:
            soup = BeautifulSoup(sticker_html, 'html.parser')
            images = soup.find_all('img')
            
            for img in images:
                title = img.get('title', '')
                if title and 'Sticker:' in title:
                    sticker_name = title.replace('Sticker:', '').strip()
                    if sticker_name:
                        stickers.append({
                            'name': sticker_name,
                            'html': str(img)
                        })
        except Exception as e:
            logger.debug(f"Ошибка парсинга наклеек из HTML: {e}")
        return stickers
    
    def _extract_price_from_html(self, row_element) -> float:
        """Извлекает цену из HTML элемента лота."""
        try:
            price_elem = row_element.find('span', class_='market_table_value')
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                if price_match:
                    return float(price_match.group())
        except Exception as e:
            logger.debug(f"Ошибка извлечения цены: {e}")
        return 0.0
