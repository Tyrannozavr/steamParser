"""
Тестовый скрипт для проверки работы с выбором степени износа и парсинга.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.steam_parser import SteamMarketParser
from core import SearchFilters
from services.redis_service import RedisService
from core.config import Config


async def test_wear_selection():
    """Тестирует выбор степени износа и парсинг."""
    print("=" * 70)
    print("ТЕСТ: Выбор степени износа и парсинг")
    print("=" * 70)
    
    # Инициализация
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        print(f"✅ Redis подключен: {Config.REDIS_URL}")
    
    parser = SteamMarketParser(redis_service=redis_service)
    await parser._ensure_client()
    
    try:
        # Тест 1: Поиск вариантов для предмета без степени износа
        print("\n1️⃣ Тест: Поиск вариантов для 'AK-47 | Slate'")
        print("-" * 70)
        variants = await parser.get_item_variants("AK-47 | Slate")
        print(f"Найдено вариантов: {len(variants)}")
        for i, variant in enumerate(variants[:5], 1):
            name = variant.get('market_hash_name', 'Unknown')
            wear = variant.get('wear_condition', 'N/A')
            print(f"  {i}. {name} (износ: {wear})")
        
        # Тест 2: Проверка конкретного hash_name
        print("\n2️⃣ Тест: Проверка hash_name 'AK-47 | Slate (Minimal Wear)'")
        print("-" * 70)
        is_valid, total_count = await parser.validate_hash_name(appid=730, hash_name="AK-47 | Slate (Minimal Wear)")
        print(f"Валидность: {is_valid}")
        print(f"Всего лотов: {total_count}")
        
        # Тест 3: Парсинг нескольких лотов
        if is_valid and total_count > 0:
            print("\n3️⃣ Тест: Парсинг первых лотов")
            print("-" * 70)
            filters = SearchFilters(item_name="AK-47 | Slate (Minimal Wear)", max_price=100.0)
            
            # Парсим только первые несколько лотов для теста
            parsed_listings = await parser._parse_all_listings(
                appid=730,
                hash_name="AK-47 | Slate (Minimal Wear)",
                filters=filters,
                target_patterns=None
            )
            
            print(f"Парсировано лотов: {len(parsed_listings)}")
            for i, listing in enumerate(parsed_listings[:5], 1):
                print(f"\n  Лот {i}:")
                print(f"    Цена: ${listing.item_price:.2f}" if listing.item_price else "    Цена: N/A")
                print(f"    Float: {listing.float_value:.6f}" if listing.float_value else "    Float: N/A")
                print(f"    Паттерн: {listing.pattern}" if listing.pattern else "    Паттерн: N/A")
                print(f"    Наклеек: {len(listing.stickers)}")
                if listing.stickers:
                    total_stickers_price = sum(s.price for s in listing.stickers if s.price)
                    print(f"    Общая цена наклеек: ${total_stickers_price:.2f}")
                    for j, sticker in enumerate(listing.stickers[:3], 1):
                        sticker_name = sticker.name or sticker.wear or "Unknown"
                        price_str = f"${sticker.price:.2f}" if sticker.price else "N/A"
                        print(f"      {j}. {sticker_name}: {price_str}")
        
        print("\n" + "=" * 70)
        print("✅ Тест завершен успешно!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await parser.close()
        if redis_service:
            await redis_service.close()


if __name__ == "__main__":
    asyncio.run(test_wear_selection())

