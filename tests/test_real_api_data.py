#!/usr/bin/env python3
"""
Тестируем парсер на РЕАЛЬНЫХ данных из API.
"""
import asyncio
import json
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from core.steam_parser import SteamMarketParser
from core.models import SearchFilters, StickersFilter
from services.redis_service import RedisService
from loguru import logger

# РЕАЛЬНЫЕ ДАННЫЕ ИЗ API
REAL_API_DATA = {
    "success": True,
    "start": 0,
    "pagesize": 10,
    "total_count": 242,
    "listinginfo": {
        "757296320982207707": {
            "listingid": "757296320982207707",
            "price": 1400,
            "asset": {
                "currency": 0,
                "appid": 730,
                "contextid": "2",
                "id": "44785176489",
                "amount": "1"
            }
        }
    },
    "assets": {
        "730": {
            "2": {
                "44785176489": {
                    "currency": 0,
                    "appid": 730,
                    "contextid": "2",
                    "id": "44785176489",
                    "classid": "4428793733",
                    "instanceid": "7774715126",
                    "amount": "1",
                    "descriptions": [
                        {
                            "type": "html",
                            "value": "Exterior: Field-Tested",
                            "name": "exterior_wear"
                        },
                        {
                            "type": "html",
                            "value": "<br><div id=\"sticker_info\" class=\"sticker_info\" style=\"border: 2px solid rgb(102, 102, 102); border-radius: 6px; width=100; margin:4px; padding:8px;\"><center><img width=64 height=48 src=\"https://cdn.steamstatic.com/apps/730/icons/econ/stickers/aus2025/sig_torzsi_gold.56dda9d6ba9e035c1e961ae236373b4fd813028c.png\" title=\"Sticker: torzsi (Gold) | Austin 2025\"><img width=64 height=48 src=\"https://cdn.steamstatic.com/apps/730/icons/econ/stickers/aus2025/mouz_foil.9046e8d856e30f0360c0dd85339a4aef3e409043.png\" title=\"Sticker: MOUZ (Foil) | Austin 2025\"><img width=64 height=48 src=\"https://cdn.steamstatic.com/apps/730/icons/econ/stickers/sha2024/mouz.0c0aafbb4ce61e9fbc0012fd09940dd5bdb83d89.png\" title=\"Sticker: MOUZ | Shanghai 2024\"><br>Sticker: torzsi (Gold) | Austin 2025, MOUZ (Foil) | Austin 2025, MOUZ | Shanghai 2024</center></div>",
                            "name": "sticker_info"
                        }
                    ],
                    "name": "StatTrak™ AK-47 | Slate",
                    "market_hash_name": "StatTrak™ AK-47 | Slate (Field-Tested)",
                    "asset_properties": [
                        {
                            "propertyid": 2,
                            "float_value": "0.237694263458251953"
                        },
                        {
                            "propertyid": 1,
                            "int_value": "566"
                        }
                    ]
                }
            }
        }
    }
}

async def test_real_api_data():
    """Тестируем парсер на реальных данных из API."""
    
    logger.info("🔍 ТЕСТИРОВАНИЕ НА РЕАЛЬНЫХ ДАННЫХ ИЗ API")
    logger.info("=" * 60)
    
    redis_service = RedisService()
    await redis_service.connect()
    
    parser = SteamMarketParser(proxy=None, redis_service=redis_service)
    
    # Создаем фильтры
    filters = SearchFilters(
        item_name="StatTrak™ AK-47 | Slate (Field-Tested)",
        max_price=25.0,
        appid=730,
        currency=1,
        auto_update_base_price=False,
        stickers_filter=StickersFilter(
            min_stickers_count=1,
            required_stickers=[]
        )
    )
    
    try:
        # Мокаем _fetch_render_api чтобы он возвращал реальные данные
        original_fetch = parser._fetch_render_api
        
        async def mock_fetch_render_api(appid, hash_name, start=0, count=10):
            logger.info(f"🎭 МОКАЕМ _fetch_render_api - возвращаем РЕАЛЬНЫЕ данные из API")
            return REAL_API_DATA
        
        parser._fetch_render_api = mock_fetch_render_api
        
        # Тестируем _parse_all_listings
        logger.info(f"\n🚀 ТЕСТИРУЕМ _parse_all_listings на РЕАЛЬНЫХ данных...")
        
        appid = 730
        hash_name = "StatTrak™ AK-47 | Slate (Field-Tested)"
        
        result = await parser._parse_all_listings(appid, hash_name, filters)
        
        if result:
            logger.info(f"✅ Парсинг завершен, найдено {len(result)} предметов")
            
            # Проверяем каждый предмет
            for i, item in enumerate(result):
                logger.info(f"\n🎯 ПРЕДМЕТ [{i+1}]:")
                logger.info(f"   - listing_id: {getattr(item, 'listing_id', 'N/A')}")
                logger.info(f"   - pattern: {getattr(item, 'pattern', 'N/A')}")
                logger.info(f"   - float: {getattr(item, 'float_value', 'N/A')}")
                
                stickers = getattr(item, 'stickers', []) or []
                logger.info(f"   - stickers: {len(stickers)} штук")
                
                if stickers:
                    logger.info(f"   🏷️ НАЙДЕННЫЕ НАКЛЕЙКИ:")
                    for j, sticker in enumerate(stickers):
                        sticker_name = sticker.name if hasattr(sticker, 'name') else str(sticker)
                        logger.info(f"      [{j}] {sticker_name}")
                    
                    # Проверяем, правильные ли наклейки
                    torzsi_found = any('torzsi' in str(sticker).lower() for sticker in stickers)
                    mouz_found = any('mouz' in str(sticker).lower() for sticker in stickers)
                    
                    if torzsi_found and mouz_found:
                        logger.info(f"   ✅ УСПЕХ: Найдены правильные наклейки torzsi и MOUZ!")
                    else:
                        logger.error(f"   ❌ ОШИБКА: Наклейки не соответствуют ожидаемым!")
                else:
                    logger.error(f"   ❌ НАКЛЕЙКИ НЕ НАЙДЕНЫ! ЭТО БАГ!")
                    
                    # Показываем, что должно было быть
                    logger.error(f"   🔍 ОЖИДАЛИСЬ НАКЛЕЙКИ:")
                    logger.error(f"      - torzsi (Gold) | Austin 2025")
                    logger.error(f"      - MOUZ (Foil) | Austin 2025") 
                    logger.error(f"      - MOUZ | Shanghai 2024")
        else:
            logger.error("❌ Парсинг не вернул результатов")
            
        # Восстанавливаем оригинальную функцию
        parser._fetch_render_api = original_fetch
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    await redis_service.disconnect()
    logger.info("\n🏁 ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")

if __name__ == "__main__":
    asyncio.run(test_real_api_data())
