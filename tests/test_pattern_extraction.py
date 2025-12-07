"""
Тест извлечения паттернов из реального API ответа Steam Market.
Проверяет корректность обработки данных из /render/ endpoint.
"""
import json
import sys
import logging
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def extract_pattern_from_asset_properties(asset_properties):
    """
    Извлекает паттерн из asset_properties (propertyid=1).
    Это та же логика, что используется в steam_parser.py
    """
    pattern = None
    
    if not asset_properties:
        logger.warning("    ⚠️ Нет asset_properties")
        return None
    
    logger.info(f"    🔍 Найдено {len(asset_properties)} свойств в asset_properties")
    
    for prop in asset_properties:
        prop_id = prop.get('propertyid')
        logger.info(f"       propertyid={prop_id}, keys={list(prop.keys())}, values={prop}")
        
        if prop_id == 1:
            pattern = prop.get('int_value')
            logger.info(f"    ✅ Найден паттерн (propertyid=1): {pattern} (тип: {type(pattern).__name__})")
            
            # Преобразуем в int
            if pattern is not None:
                try:
                    pattern = int(pattern)
                    logger.info(f"    ✅ Паттерн преобразован в int: {pattern}")
                except (ValueError, TypeError) as e:
                    logger.error(f"    ❌ Ошибка преобразования паттерна в int: {e}, значение={pattern}")
                    pattern = None
            break
    
    return pattern


def test_api_response():
    """Тестирует обработку реального API ответа."""
    
    # Реальный JSON ответ из API (из веб-поиска)
    api_response = {
        "success": True,
        "start": 0,
        "pagesize": 10,
        "total_count": 194,
        "assets": {
            "730": {
                "2": {
                    "48106224934": {
                        "currency": 0,
                        "appid": 730,
                        "contextid": "2",
                        "id": "48106224934",
                        "asset_properties": [
                            {
                                "propertyid": 2,
                                "float_value": "0.357310503721237183"
                            },
                            {
                                "propertyid": 1,
                                "int_value": "896"
                            },
                            {
                                "propertyid": 6,
                                "string_value": "6A7ACC9080F0D96B726D4AF068426F5A63528D88B19F692AEA6D226A3ACF6B086F62687AE37A02E0EAEAEA661A620879436E"
                            }
                        ]
                    },
                    "47911217959": {
                        "currency": 0,
                        "appid": 730,
                        "contextid": "2",
                        "id": "47911217959",
                        "asset_properties": [
                            {
                                "propertyid": 2,
                                "float_value": "0.351651132106781006"
                            },
                            {
                                "propertyid": 1,
                                "int_value": "797"
                            },
                            {
                                "propertyid": 6,
                                "string_value": "E7F740310B5A55E6FFE0C77DE5CFE2D7EEDF79703712E4A77AE1AFE7B7ED85E2EFE5F76BD985E2EFE7F76BD985E2EFE4F76BD985E2EFE6F76BD98FE997EF90E8397B"
                            }
                        ]
                    }
                }
            }
        },
        "listinginfo": {
            "747163221828673397": {
                "listingid": "747163221828673397",
                "asset": {
                    "id": "48106224934",
                    "contextid": "2"
                }
            },
            "728022923409624541": {
                "listingid": "728022923409624541",
                "asset": {
                    "id": "47911217959",
                    "contextid": "2"
                }
            }
        }
    }
    
    logger.info("=" * 80)
    logger.info("🧪 ТЕСТ ИЗВЛЕЧЕНИЯ ПАТТЕРНОВ ИЗ API ОТВЕТА")
    logger.info("=" * 80)
    
    # Тест 1: Извлечение паттерна из asset_properties
    logger.info("\n📋 ТЕСТ 1: Извлечение паттерна из asset_properties")
    logger.info("-" * 80)
    
    assets = api_response.get('assets', {}).get('730', {}).get('2', {})
    
    for asset_id, asset_data in assets.items():
        logger.info(f"\n🔍 Обрабатываем asset_id={asset_id}")
        asset_properties = asset_data.get('asset_properties', [])
        
        pattern = extract_pattern_from_asset_properties(asset_properties)
        
        if pattern is not None:
            logger.info(f"    ✅ РЕЗУЛЬТАТ: Паттерн={pattern} (тип: {type(pattern).__name__})")
            
            # Проверяем паттерн 896
            if pattern == 896:
                logger.info(f"    🎯 УСПЕХ! Паттерн 896 найден для asset_id={asset_id}!")
            else:
                logger.info(f"    ℹ️ Паттерн {pattern} (не 896)")
        else:
            logger.error(f"    ❌ ОШИБКА: Паттерн не извлечен для asset_id={asset_id}")
    
    # Тест 2: Связывание listing_id с asset_id
    logger.info("\n📋 ТЕСТ 2: Связывание listing_id с asset_id")
    logger.info("-" * 80)
    
    listinginfo = api_response.get('listinginfo', {})
    assets_data_map = {}
    
    # Сначала извлекаем все паттерны в assets_data_map
    for asset_id, asset_data in assets.items():
        asset_properties = asset_data.get('asset_properties', [])
        pattern = extract_pattern_from_asset_properties(asset_properties)
        
        if pattern is not None:
            assets_data_map[asset_id] = {
                'pattern': pattern,
                'float_value': None,
                'stickers': []
            }
            logger.info(f"    💾 Сохранено в assets_data_map[{asset_id}]: pattern={pattern}")
    
    # Теперь связываем listing_id с asset_id
    for listing_id, listing_data in listinginfo.items():
        logger.info(f"\n🔍 Обрабатываем listing_id={listing_id}")
        
        if 'asset' in listing_data:
            asset_info = listing_data['asset']
            asset_id = str(asset_info.get('id'))
            
            logger.info(f"    📊 listing_id={listing_id} -> asset_id={asset_id}")
            
            if asset_id in assets_data_map:
                pattern = assets_data_map[asset_id]['pattern']
                logger.info(f"    ✅ Найден паттерн для listing_id={listing_id}: {pattern}")
                
                if pattern == 896:
                    logger.info(f"    🎯 УСПЕХ! Паттерн 896 связан с listing_id={listing_id}, asset_id={asset_id}")
            else:
                logger.error(f"    ❌ ОШИБКА: asset_id={asset_id} не найден в assets_data_map")
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    logger.info("=" * 80)


if __name__ == "__main__":
    test_api_response()

