#!/usr/bin/env python3
"""
Тестовый скрипт для проверки фильтра наклеек на конкретном предмете.
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from core.models import SearchFilters, StickersFilter, ParsedItemData, StickerInfo
from core.steam_parser import SteamMarketParser
from services.proxy_manager import ProxyManager
from services.redis_service import RedisService
from core.database import DatabaseManager
from core.config import Config

async def test_sticker_filter_on_item():
    """Тестирует фильтр наклеек на конкретном предмете."""
    
    # Создаем тестовый фильтр
    stickers_filter = StickersFilter(
        min_stickers_price=0.1,
        max_overpay_coefficient=0.5
    )
    
    filters = SearchFilters(
        item_name='MP9 | Starlight Protector (Field-Tested)',
        max_price=95.0,
        stickers_filter=stickers_filter,
        appid=730,
        currency=1
    )
    
    # Инициализируем сервисы
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    proxy_manager = ProxyManager(session)
    redis_service = RedisService(Config.REDIS_URL)
    await redis_service.connect()
    
    parser = SteamMarketParser(
        proxy_manager=proxy_manager,
        redis_service=redis_service
    )
    
    try:
        # Парсим предметы
        result = await parser.search_items(filters, start=0, count=10)
        
        print(f'\n=== Результат парсинга ===')
        print(f'success={result.get("success")}, items={len(result.get("items", []))}')
        
        if result.get('items'):
            for idx, item in enumerate(result.get('items', [])[:3], 1):
                parsed_data_dict = item.get('parsed_data', {})
                print(f'\n--- Предмет #{idx} ---')
                print(f'Название: {item.get("name")}')
                print(f'Цена: ${parsed_data_dict.get("item_price", 0):.2f}')
                
                stickers = parsed_data_dict.get('stickers', [])
                total_stickers_price = parsed_data_dict.get('total_stickers_price', 0)
                print(f'Наклеек: {len(stickers)}, Общая цена: ${total_stickers_price:.2f}')
                
                if stickers:
                    print('Наклейки:')
                    for s in stickers[:5]:
                        name = s.get('name') or s.get('wear', 'Unknown')
                        price = s.get('price', 0)
                        print(f'  - {name}: ${price:.2f}')
                
                # Тестируем фильтр вручную
                print(f'\n--- Тест фильтра для предмета #{idx} ---')
                
                # Создаем ParsedItemData из словаря
                parsed_data = ParsedItemData(
                    item_name=parsed_data_dict.get('item_name', item.get('name')),
                    item_price=parsed_data_dict.get('item_price'),
                    float_value=parsed_data_dict.get('float_value'),
                    pattern=parsed_data_dict.get('pattern'),
                    stickers=[StickerInfo(**s) if isinstance(s, dict) else s for s in stickers],
                    total_stickers_price=total_stickers_price,
                    listing_id=parsed_data_dict.get('listing_id')
                )
                
                # Проверяем фильтр
                matches = await parser._matches_filters(item, filters, parsed_data)
                print(f'Результат проверки фильтра: {matches}')
                
        else:
            print('\n⚠️ Предметы не найдены')
            
    finally:
        await parser.close()
        await redis_service.disconnect()
        await session.close()
        await db_manager.close()

if __name__ == '__main__':
    asyncio.run(test_sticker_filter_on_item())












