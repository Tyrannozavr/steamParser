"""
Тест реального запроса к Steam Market API /render/ endpoint.
Проверяет, что данные корректно обрабатываются из реального ответа.
"""
import asyncio
import sys
import logging
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))

from core.steam_http_client import SteamHTTPClient
from core.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def test_real_api_request():
    """Тестирует реальный запрос к API."""
    
    logger.info("=" * 80)
    logger.info("🧪 ТЕСТ РЕАЛЬНОГО ЗАПРОСА К STEAM MARKET API")
    logger.info("=" * 80)
    
    # Параметры запроса
    appid = 730
    hash_name = "StatTrak™ AK-47 | Redline (Field-Tested)"
    start = 0
    count = 10
    
    logger.info(f"\n📋 Параметры запроса:")
    logger.info(f"   appid: {appid}")
    logger.info(f"   hash_name: {hash_name}")
    logger.info(f"   start: {start}")
    logger.info(f"   count: {count}")
    
    # Создаем HTTP клиент
    client = SteamHTTPClient()
    
    try:
        # Формируем URL
        base_url = f"https://steamcommunity.com/market/listings/{appid}/{quote(hash_name)}/render/"
        params = {
            "query": "",
            "start": start,
            "count": count,
            "country": "BY",
            "language": "english",
            "currency": 1
        }
        url = base_url + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        
        logger.info(f"\n🌐 URL: {url}")
        
        # Выполняем запрос
        logger.info("\n📡 Выполняем запрос к API...")
        response = await client.get(url)
        
        if not response:
            logger.error("❌ ОШИБКА: Пустой ответ от API")
            return
        
        logger.info(f"✅ Получен ответ от API (размер: {len(str(response))} символов)")
        
        # Извлекаем assets
        if 'assets' in response and '730' in response['assets']:
            app_assets = response['assets']['730']
            logger.info(f"\n📊 Найдено {len(app_assets)} контекстов в assets")
            
            for contextid, items in app_assets.items():
                logger.info(f"\n🔍 Контекст {contextid}: найдено {len(items)} items")
                
                for itemid, item in items.items():
                    itemid = str(itemid)
                    logger.info(f"\n   📦 Asset ID: {itemid}")
                    
                    # Извлекаем паттерн
                    if 'asset_properties' in item:
                        props = item['asset_properties']
                        logger.info(f"      🔍 Найдено {len(props)} свойств в asset_properties")
                        
                        pattern = None
                        for prop in props:
                            prop_id = prop.get('propertyid')
                            if prop_id == 1:
                                pattern = prop.get('int_value')
                                logger.info(f"      ✅ Найден паттерн (propertyid=1): {pattern} (тип: {type(pattern).__name__})")
                                
                                # Преобразуем в int
                                if pattern is not None:
                                    try:
                                        pattern = int(pattern)
                                        logger.info(f"      ✅ Паттерн преобразован в int: {pattern}")
                                        
                                        if pattern == 896:
                                            logger.info(f"      🎯 УСПЕХ! Паттерн 896 найден для asset_id={itemid}!")
                                    except (ValueError, TypeError) as e:
                                        logger.error(f"      ❌ Ошибка преобразования: {e}")
                                
                                break
                        
                        if pattern is None:
                            logger.warning(f"      ⚠️ Паттерн не найден для asset_id={itemid}")
                    else:
                        logger.warning(f"      ⚠️ Нет asset_properties для asset_id={itemid}")
        else:
            logger.error("❌ ОШИБКА: Нет assets в ответе")
        
        # Проверяем listinginfo
        if 'listinginfo' in response:
            listinginfo = response['listinginfo']
            logger.info(f"\n📋 Найдено {len(listinginfo)} записей в listinginfo")
            
            # Ищем listing_id для asset_id=48106224934
            target_asset_id = "48106224934"
            for listing_id, listing_data in listinginfo.items():
                if 'asset' in listing_data:
                    asset_info = listing_data['asset']
                    asset_id = str(asset_info.get('id'))
                    
                    if asset_id == target_asset_id:
                        logger.info(f"\n🎯 НАЙДЕН listing_id={listing_id} для asset_id={target_asset_id}")
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}", exc_info=True)
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(test_real_api_request())

