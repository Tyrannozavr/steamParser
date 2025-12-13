"""
Парсинг данных страницы для параллельного парсинга лотов.
"""
from typing import Dict, List, Optional
from parsers import ItemPageParser
from core.utils.sticker_parser import StickerParser


def extract_assets_data(render_data: dict, worker_id: int, page_num: int, log_func) -> Dict[str, dict]:
    """
    Извлекает данные из assets (паттерны, float, наклейки).
    
    Args:
        render_data: Данные от Steam API
        worker_id: ID воркера
        page_num: Номер страницы
        log_func: Функция для логирования
        
    Returns:
        Словарь {itemid: {pattern, float_value, stickers, contextid, itemid}}
    """
    assets_data_map = {}
    
    if 'assets' in render_data and '730' in render_data['assets']:
        app_assets = render_data['assets']['730']
        for contextid, items in app_assets.items():
            for itemid, item in items.items():
                itemid = str(itemid)
                pattern = None
                float_value = None
                stickers = []
                
                # Парсим asset_properties для паттерна и float
                if 'asset_properties' in item:
                    props = item['asset_properties']
                    for prop in props:
                        prop_id = prop.get('propertyid')
                        # propertyid=1 для скинов, propertyid=3 для брелков
                        # Проверяем оба, но не перезаписываем, если паттерн уже найден
                        if (prop_id == 1 or prop_id == 3) and pattern is None:
                            pattern = prop.get('int_value')
                            try:
                                pattern = int(pattern) if pattern is not None else None
                            except (ValueError, TypeError):
                                pattern = None
                        elif prop_id == 2:
                            float_value_raw = prop.get('float_value')
                            try:
                                float_value = float(float_value_raw) if float_value_raw is not None else None
                            except (ValueError, TypeError):
                                float_value = None
                
                # Парсим descriptions для наклеек используя StickerParser
                if 'descriptions' in item:
                    parsed_stickers = StickerParser.parse_stickers_from_asset(item, max_stickers=5)
                    stickers.extend(parsed_stickers)
                
                # Сохраняем данные
                if pattern is not None or float_value is not None or stickers:
                    # Сохраняем по itemid (это ID из assets)
                    assets_data_map[itemid] = {
                        'pattern': pattern,
                        'float_value': float_value,
                        'stickers': stickers,
                        'contextid': contextid,
                        'itemid': itemid  # Сохраняем для отладки
                    }
                    if stickers:
                        log_func("debug", f"    💾 Воркер {worker_id}, страница {page_num}: Сохранены наклейки для itemid={itemid}: {[s.name for s in stickers[:3]]}")
    
    return assets_data_map


def parse_page_listings(render_data: dict, worker_id: int, page_num: int, log_func) -> List[dict]:
    """
    Парсит HTML из results_html и возвращает список лотов.
    
    Args:
        render_data: Данные от Steam API
        worker_id: ID воркера
        page_num: Номер страницы
        log_func: Функция для логирования
        
    Returns:
        Список лотов
    """
    results_html = render_data.get('results_html', '')
    if not results_html:
        log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: results_html пуст")
        return []
    
    parser_obj = ItemPageParser(results_html)
    return parser_obj.get_all_listings()


def link_listings_with_assets(
    page_listings: List[dict],
    render_data: dict,
    assets_data_map: Dict[str, dict],
    worker_id: int,
    page_num: int,
    log_func
) -> None:
    """
    Связывает listing_id с данными из assets через listinginfo.
    Модифицирует page_listings на месте, добавляя pattern, float_value, stickers.
    
    Args:
        page_listings: Список лотов (будет модифицирован)
        render_data: Данные от Steam API
        assets_data_map: Словарь с данными assets
        worker_id: ID воркера
        page_num: Номер страницы
        log_func: Функция для логирования
    """
    if 'listinginfo' not in render_data:
        return
    
    listinginfo = render_data['listinginfo']
    for listing in page_listings:
        listing_id = listing.get('listing_id')
        if listing_id:
            listing_id = str(listing_id)
        else:
            continue
        
        if listing_id in listinginfo:
            listing_data = listinginfo[listing_id]
            if 'asset' in listing_data:
                asset_info = listing_data['asset']
                asset_id = asset_info.get('id')
                asset_contextid = asset_info.get('contextid')
                if asset_id:
                    asset_id = str(asset_id)
                    
                    # Ищем данные в assets_data_map
                    found_asset_data = None
                    if asset_id in assets_data_map:
                        found_asset_data = assets_data_map[asset_id]
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по asset_id={asset_id}")
                    elif listing_id in assets_data_map:
                        found_asset_data = assets_data_map[listing_id]
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по listing_id={listing_id}")
                    else:
                        # Fallback: ищем по itemid из сохраненных данных
                        for key, data in assets_data_map.items():
                            if data.get('itemid') == asset_id:
                                found_asset_data = data
                                log_func("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по itemid={asset_id} (ключ в map: {key})")
                                break
                        
                        if not found_asset_data:
                            # Fallback 1: ищем по всем ключам, сравнивая itemid
                            for key, data in assets_data_map.items():
                                stored_itemid = data.get('itemid')
                                if stored_itemid and str(stored_itemid) == str(asset_id):
                                    found_asset_data = data
                                    log_func("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по itemid={asset_id} (ключ в map: {key})")
                                    break
                            
                            if not found_asset_data:
                                # Fallback 2: единственный asset с наклейками на странице
                                assets_with_stickers = {k: v for k, v in assets_data_map.items() if v.get('stickers')}
                                if len(assets_with_stickers) == 1:
                                    found_asset_data = list(assets_with_stickers.values())[0]
                                    log_func("info", f"    ⚠️ Воркер {worker_id}, страница {page_num}: Использован fallback (единственный asset с наклейками) для listing_id={listing_id}, asset_id={asset_id}")
                                elif len(assets_with_stickers) > 1:
                                    # Если несколько assets с наклейками, пробуем найти по контексту
                                    if asset_contextid:
                                        matching_by_context = [v for k, v in assets_with_stickers.items() if v.get('contextid') == asset_contextid]
                                        if len(matching_by_context) == 1:
                                            found_asset_data = matching_by_context[0]
                                            log_func("info", f"    ✅ Воркер {worker_id}, страница {page_num}: Найден asset по contextid={asset_contextid} для listing_id={listing_id}")
                                    else:
                                        log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: НЕ НАЙДЕН asset для listing_id={listing_id}, asset_id={asset_id}")
                                        log_func("warning", f"       assets_data_map содержит {len(assets_data_map)} записей")
                                        log_func("warning", f"       assets_with_stickers: {len(assets_with_stickers)} записей")
                                        if assets_data_map:
                                            log_func("warning", f"       Примеры ключей в assets_data_map: {list(assets_data_map.keys())[:5]}")
                                            sample_itemids = [v.get('itemid') for v in list(assets_data_map.values())[:5] if v.get('itemid')]
                                            if sample_itemids:
                                                log_func("warning", f"       Примеры itemid в данных: {sample_itemids}")
                                else:
                                    log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: НЕ НАЙДЕН asset для listing_id={listing_id}, asset_id={asset_id}")
                    
                    if found_asset_data:
                        stickers_count = len(found_asset_data.get('stickers', []))
                        listing['pattern'] = found_asset_data.get('pattern')
                        listing['float_value'] = found_asset_data.get('float_value')
                        listing['stickers'] = found_asset_data.get('stickers', [])
                        log_func("debug", f"    ✅ Воркер {worker_id}, страница {page_num}: Связаны данные для listing_id={listing_id}: наклеек={stickers_count}, pattern={found_asset_data.get('pattern')}, float={found_asset_data.get('float_value')}")
                    else:
                        log_func("warning", f"    ⚠️ Воркер {worker_id}, страница {page_num}: НЕ СВЯЗАНЫ данные для listing_id={listing_id}, asset_id={asset_id} - наклейки будут пустыми")

