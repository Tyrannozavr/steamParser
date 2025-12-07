#!/usr/bin/env python3
"""
Простой тест извлечения наклеек из реальных данных.
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

async def test_stickers_extraction():
    """Тестируем извлечение наклеек."""
    
    logger.info("🔍 ТЕСТ ИЗВЛЕЧЕНИЯ НАКЛЕЕК")
    logger.info("=" * 40)
    
    redis_service = RedisService()
    await redis_service.connect()
    
    parser = SteamMarketParser(proxy=None, redis_service=redis_service)
    
    # Используем свежие данные, которые мы получили
    try:
        with open('/tmp/fresh_steam_data.json', 'r') as f:
            fresh_data = json.load(f)
        logger.info(f"✅ Загружены свежие данные")
    except Exception as e:
        logger.error(f"❌ Не удалось загрузить свежие данные: {e}")
        await redis_service.disconnect()
        return
    
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
        # Мокаем _fetch_render_api
        original_fetch = parser._fetch_render_api
        
        async def mock_fetch_render_api(appid, hash_name, start=0, count=10):
            logger.info(f"🎭 Возвращаем свежие данные из API")
            return fresh_data
        
        parser._fetch_render_api = mock_fetch_render_api
        
        # Тестируем _parse_all_listings
        logger.info(f"\n🚀 ТЕСТИРУЕМ извлечение наклеек...")
        
        appid = 730
        hash_name = "StatTrak™ AK-47 | Slate (Field-Tested)"
        
        result = await parser._parse_all_listings(appid, hash_name, filters)
        
        if result:
            logger.info(f"✅ Найдено {len(result)} предметов")
            
            # Ищем предметы с наклейками
            found_stickers = False
            for i, item in enumerate(result):
                stickers = getattr(item, 'stickers', []) or []
                if stickers:
                    found_stickers = True
                    logger.info(f"\n🎯 ПРЕДМЕТ С НАКЛЕЙКАМИ [{i+1}]:")
                    logger.info(f"   - listing_id: {getattr(item, 'listing_id', 'N/A')}")
                    logger.info(f"   - pattern: {getattr(item, 'pattern', 'N/A')}")
                    logger.info(f"   - stickers: {len(stickers)} штук")
                    
                    for j, sticker in enumerate(stickers):
                        logger.info(f"      [{j}] {sticker.name}")
            
            if not found_stickers:
                logger.warning(f"⚠️ Предметы с наклейками не найдены")
        else:
            logger.error("❌ Парсинг не вернул результатов")
            
        # Восстанавливаем оригинальную функцию
        parser._fetch_render_api = original_fetch
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    await redis_service.disconnect()
    logger.info("\n🏁 ТЕСТ ЗАВЕРШЕН")

if __name__ == "__main__":
    asyncio.run(test_stickers_extraction())
