"""
Тестовый скрипт для проверки новых фильтров:
- PatternList (список паттернов)
- StickersFilter с формулой S = D + (P * x)
- Определение типа предмета (скин/брелок)
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import SearchFilters, FloatRange, PatternList, StickersFilter, SteamMarketParser
import pytest

pytest_plugins = ('pytest_asyncio',)


async def test_pattern_list_filter():
    """Тест фильтра паттернов (список)."""
    print("=" * 70)
    print("🧪 ТЕСТ: Фильтр паттернов (список)")
    print("=" * 70)
    
    filters = SearchFilters(
        item_name="AK-47 | Redline",
        pattern_list=PatternList(
            patterns=[372, 48, 289, 2, 993],
            item_type="skin"
        ),
        max_price=40.0
    )
    
    async with SteamMarketParser() as parser:
        print(f"🔍 Поиск: {filters.item_name}")
        print(f"📋 Паттерны: {filters.pattern_list.patterns}")
        print(f"💰 Максимальная цена: ${filters.max_price}")
        
        result = await parser.search_items(filters, start=0, count=10)
        
        print(f"\n📊 Результаты:")
        print(f"  - Успешно: {result['success']}")
        if result['success']:
            print(f"  - Всего найдено: {result.get('total_count', 0)}")
            print(f"  - После фильтрации: {result.get('filtered_count', 0)}")
            
            if result.get('items'):
                print(f"\n🎯 Найденные предметы:")
                for i, item in enumerate(result['items'][:3], 1):
                    name = item.get('name', 'Unknown')
                    price = item.get('sell_price_text', 'N/A')
                    parsed = item.get('parsed_data', {})
                    pattern = parsed.get('pattern')
                    print(f"  {i}. {name} - {price}")
                    if pattern is not None:
                        print(f"     Паттерн: {pattern}")
        else:
            print(f"  - Ошибка: {result.get('error', 'Unknown')}")
    
    print("\n")


async def test_float_filter():
    """Тест фильтра float."""
    print("=" * 70)
    print("🧪 ТЕСТ: Фильтр float")
    print("=" * 70)
    
    filters = SearchFilters(
        item_name="AK-47 | Redline",
        float_range=FloatRange(min=0.15, max=0.1934),
        max_price=37.6
    )
    
    async with SteamMarketParser() as parser:
        print(f"🔍 Поиск: {filters.item_name}")
        print(f"📋 Float: {filters.float_range.min} - {filters.float_range.max}")
        print(f"💰 Максимальная цена: ${filters.max_price}")
        
        result = await parser.search_items(filters, start=0, count=10)
        
        print(f"\n📊 Результаты:")
        print(f"  - Успешно: {result['success']}")
        if result['success']:
            print(f"  - Всего найдено: {result.get('total_count', 0)}")
            print(f"  - После фильтрации: {result.get('filtered_count', 0)}")
            
            if result.get('items'):
                print(f"\n🎯 Найденные предметы:")
                for i, item in enumerate(result['items'][:3], 1):
                    name = item.get('name', 'Unknown')
                    price = item.get('sell_price_text', 'N/A')
                    parsed = item.get('parsed_data', {})
                    float_val = parsed.get('float_value')
                    print(f"  {i}. {name} - {price}")
                    if float_val is not None:
                        print(f"     Float: {float_val}")
        else:
            print(f"  - Ошибка: {result.get('error', 'Unknown')}")
    
    print("\n")


async def test_stickers_formula_filter():
    """Тест фильтра наклеек с формулой S = D + (P * x)."""
    print("=" * 70)
    print("🧪 ТЕСТ: Фильтр наклеек с формулой S = D + (P * x)")
    print("=" * 70)
    
    filters = SearchFilters(
        item_name="AK-47 | Redline",
        stickers_filter=StickersFilter(
            max_overpay_coefficient=0.08,  # Максимальная переплата 8%
            min_stickers_price=100.0       # Минимальная цена наклеек $100
        )
    )
    
    async with SteamMarketParser() as parser:
        print(f"🔍 Поиск: {filters.item_name}")
        print(f"📋 Максимальная переплата: {filters.stickers_filter.max_overpay_coefficient * 100}%")
        print(f"📋 Минимальная цена наклеек: ${filters.stickers_filter.min_stickers_price}")
        
        # Получаем базовую цену для демонстрации
        base_price = await parser._get_base_price_for_item(filters.item_name, filters.appid)
        if base_price:
            print(f"💰 Базовая цена (D): ${base_price:.2f}")
        
        result = await parser.search_items(filters, start=0, count=10)
        
        print(f"\n📊 Результаты:")
        print(f"  - Успешно: {result['success']}")
        if result['success']:
            print(f"  - Всего найдено: {result.get('total_count', 0)}")
            print(f"  - После фильтрации: {result.get('filtered_count', 0)}")
            
            if result.get('items'):
                print(f"\n🎯 Найденные предметы:")
                for i, item in enumerate(result['items'][:3], 1):
                    name = item.get('name', 'Unknown')
                    price = item.get('sell_price_text', 'N/A')
                    parsed = item.get('parsed_data', {})
                    stickers_price = parsed.get('total_stickers_price', 0)
                    item_price = parsed.get('item_price')
                    
                    print(f"  {i}. {name} - {price}")
                    if stickers_price > 0:
                        print(f"     Цена наклеек (P): ${stickers_price:.2f}")
                        if item_price and base_price:
                            overpay = parser._calculate_overpay_coefficient(
                                item_price, base_price, stickers_price
                            )
                            if overpay is not None:
                                print(f"     Коэффициент переплаты (x): {overpay:.4f} ({overpay * 100:.2f}%)")
        else:
            print(f"  - Ошибка: {result.get('error', 'Unknown')}")
    
    print("\n")


async def test_combined_filters():
    """Тест комбинированных фильтров."""
    print("=" * 70)
    print("🧪 ТЕСТ: Комбинированные фильтры")
    print("=" * 70)
    
    filters = SearchFilters(
        item_name="AK-47 | Redline",
        pattern_list=PatternList(
            patterns=[372, 48, 289],
            item_type="skin"
        ),
        float_range=FloatRange(min=0.15, max=0.20),
        max_price=40.0
    )
    
    async with SteamMarketParser() as parser:
        print(f"🔍 Поиск: {filters.item_name}")
        print(f"📋 Паттерны: {filters.pattern_list.patterns}")
        print(f"📋 Float: {filters.float_range.min} - {filters.float_range.max}")
        print(f"💰 Максимальная цена: ${filters.max_price}")
        
        result = await parser.search_items(filters, start=0, count=10)
        
        print(f"\n📊 Результаты:")
        print(f"  - Успешно: {result['success']}")
        if result['success']:
            print(f"  - Всего найдено: {result.get('total_count', 0)}")
            print(f"  - После фильтрации: {result.get('filtered_count', 0)}")
            
            if result.get('items'):
                print(f"\n🎯 Найденные предметы:")
                for i, item in enumerate(result['items'][:3], 1):
                    name = item.get('name', 'Unknown')
                    price = item.get('sell_price_text', 'N/A')
                    parsed = item.get('parsed_data', {})
                    print(f"  {i}. {name} - {price}")
                    if parsed.get('pattern') is not None:
                        print(f"     Паттерн: {parsed.get('pattern')}")
                    if parsed.get('float_value') is not None:
                        print(f"     Float: {parsed.get('float_value')}")
        else:
            print(f"  - Ошибка: {result.get('error', 'Unknown')}")
    
    print("\n")


async def test_base_price_manager():
    """Тест менеджера базовых цен."""
    print("=" * 70)
    print("🧪 ТЕСТ: Менеджер базовых цен")
    print("=" * 70)
    
    async with SteamMarketParser() as parser:
        item_name = "AK-47 | Redline"
        
        print(f"🔍 Получение базовой цены для: {item_name}")
        
        # Первый запрос - должен получить цену
        base_price1 = await parser._get_base_price_for_item(item_name, 730)
        print(f"💰 Базовая цена (первый запрос): ${base_price1:.2f}" if base_price1 else "❌ Не удалось получить")
        
        # Второй запрос - должен использовать кэш
        base_price2 = await parser._get_base_price_for_item(item_name, 730)
        print(f"💰 Базовая цена (из кэша): ${base_price2:.2f}" if base_price2 else "❌ Не удалось получить")
        
        # Информация о кэше
        cache_info = parser.base_price_manager.get_cache_info()
        print(f"\n📊 Информация о кэше:")
        print(f"  - Кэшированных предметов: {cache_info['cached_items']}")
        print(f"  - TTL кэша: {cache_info['cache_ttl']} секунд")
    
    print("\n")


async def main():
    """Запуск всех тестов."""
    print("\n" + "=" * 70)
    print("🚀 ЗАПУСК ТЕСТОВ НОВЫХ ФИЛЬТРОВ")
    print("=" * 70 + "\n")
    
    try:
        # Тест менеджера базовых цен
        await test_base_price_manager()
        
        # Тест фильтра паттернов
        await test_pattern_list_filter()
        
        # Тест фильтра float
        await test_float_filter()
        
        # Тест фильтра наклеек с формулой
        await test_stickers_formula_filter()
        
        # Тест комбинированных фильтров
        await test_combined_filters()
        
        print("=" * 70)
        print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ ОШИБКА ПРИ ВЫПОЛНЕНИИ ТЕСТОВ: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

