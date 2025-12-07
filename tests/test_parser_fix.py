#!/usr/bin/env python3
"""
Тестируем исправленный парсер на существующих данных.
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

async def test_parser_fix():
    """Тестирует исправленный парсер на существующих данных."""
    
    logger.info("🔍 ТЕСТИРОВАНИЕ ИСПРАВЛЕННОГО ПАРСЕРА")
    logger.info("=" * 60)
    
    # Загружаем свежие данные
    try:
        with open('/tmp/fresh_steam_data.json', 'r') as f:
            test_data = json.load(f)
        logger.info(f"✅ Загружены свежие данные из /tmp/fresh_steam_data.json")
        logger.info(f"   Ключи: {list(test_data.keys())}")
    except Exception as e:
        logger.error(f"❌ Не удалось загрузить тестовые данные: {e}")
        return
    
    redis_service = RedisService()
    await redis_service.connect()
    
    # Создаем парсер БЕЗ прокси (не нужен для тестирования)
    parser = SteamMarketParser(proxy=None, redis_service=redis_service)
    
    # Создаем фильтры с наклейками (чтобы система парсила)
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
    
    logger.info(f"📋 Фильтры: {filters.item_name}")
    
    try:
        # Мокаем _fetch_render_api чтобы он возвращал наши тестовые данные
        original_fetch = parser._fetch_render_api
        
        async def mock_fetch_render_api(appid, hash_name, start=0, count=10):
            logger.info(f"🎭 МОКАЕМ _fetch_render_api - возвращаем тестовые данные")
            return test_data
        
        parser._fetch_render_api = mock_fetch_render_api
        
        # Теперь тестируем _parse_all_listings
        logger.info(f"\n🚀 ТЕСТИРУЕМ _parse_all_listings с исправлениями...")
        
        appid = 730
        hash_name = "StatTrak™ AK-47 | Slate (Field-Tested)"
        
        result = await parser._parse_all_listings(appid, hash_name, filters)
        
        if result:
            logger.info(f"✅ Парсинг завершен, найдено {len(result)} предметов")
            
            # Ищем любой предмет с наклейками (целевой уже продан)
            logger.info(f"   🔍 Ищем предметы с наклейками...")
            
            found_with_stickers = False
            for i, item in enumerate(result):
                stickers = getattr(item, 'stickers', []) or []
                if stickers:
                    found_with_stickers = True
                    logger.info(f"\n🎯 НАЙДЕН ПРЕДМЕТ С НАКЛЕЙКАМИ [{i+1}]:")
                    logger.info(f"   - listing_id: {getattr(item, 'listing_id', 'N/A')}")
                    logger.info(f"   - pattern: {getattr(item, 'pattern', 'N/A')}")
                    logger.info(f"   - float: {getattr(item, 'float_value', 'N/A')}")
                    logger.info(f"   - stickers: {len(stickers)} штук")
                    
                    logger.info(f"   🏷️ НАЙДЕННЫЕ НАКЛЕЙКИ:")
                    for j, sticker in enumerate(stickers):
                        sticker_name = sticker.name if hasattr(sticker, 'name') else str(sticker)
                        logger.info(f"      [{j}] {sticker_name}")
                    break
            
            if not found_with_stickers:
                logger.warning(f"⚠️ Предметы с наклейками НЕ найдены")
                # Показываем первые несколько предметов
                for i, item in enumerate(result[:3]):
                    stickers = getattr(item, 'stickers', []) or []
                    logger.info(f"   [{i}] listing_id: {getattr(item, 'listing_id', 'N/A')}, stickers: {len(stickers)}")
            
            # Также ищем старый целевой предмет (если есть)
            target_listing = "746037321908372777"
            for item in result:
                if hasattr(item, 'listing_id') and item.listing_id == target_listing:
                    logger.info(f"\n🎯 НАЙДЕН ЦЕЛЕВОЙ ПРЕДМЕТ:")
                    logger.info(f"   - listing_id: {item.listing_id}")
                    logger.info(f"   - pattern: {item.pattern}")
                    logger.info(f"   - float: {item.float_value}")
                    
                    stickers = item.stickers or []
                    logger.info(f"   - stickers: {len(stickers)} штук")
                    
                    if stickers:
                        logger.info(f"   🏷️ НАЙДЕННЫЕ НАКЛЕЙКИ:")
                        for i, sticker in enumerate(stickers):
                            sticker_name = sticker.name if hasattr(sticker, 'name') else str(sticker)
                            logger.info(f"      [{i}] {sticker_name}")
                        
                        # Проверяем, правильные ли это наклейки
                        queen_found = any('queen' in str(sticker).lower() for sticker in stickers)
                        natus_found = any('natus' in str(sticker).lower() for sticker in stickers)
                        
                        if queen_found:
                            logger.info(f"   ✅ УСПЕХ: Найдены правильные наклейки Queen Of Pain!")
                        elif natus_found:
                            logger.error(f"   ❌ ОШИБКА: Найдены неправильные наклейки Natus Vincere!")
                        else:
                            logger.warning(f"   ⚠️ Неопределенные наклейки")
                    else:
                        logger.error(f"   ❌ НАКЛЕЙКИ НЕ НАЙДЕНЫ!")
                    break
            else:
                logger.warning(f"⚠️ Целевой предмет НЕ найден в результатах")
                if result:
                    logger.info(f"   Найденные предметы:")
                    for i, item in enumerate(result[:3]):
                        logger.info(f"   [{i}] listing_id: {getattr(item, 'listing_id', 'N/A')}")
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
    asyncio.run(test_parser_fix())
