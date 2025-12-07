"""
Простой пример для ручного запуска парсинга одного предмета.
Показывает, что именно может спарсить скрипт.
"""
import asyncio
from models import SearchFilters, FloatRange, PatternRange
from steam_parser import SteamMarketParser


async def parse_single_item_example():
    """
    Пример парсинга одного конкретного предмета.
    Показывает все данные, которые можно извлечь.
    """
    # Укажите название предмета, который хотите спарсить
    item_name = "AK-47 | Redline (Field-Tested)"
    
    print("=" * 70)
    print(f"🔍 Парсинг предмета: {item_name}")
    print("=" * 70)
    
    async with SteamMarketParser() as parser:
        # Сначала ищем предмет через API
        filters = SearchFilters(item_name=item_name.split(" (")[0])  # Убираем состояние из названия
        result = await parser.search_items(filters, start=0, count=5)
        
        if not result['success']:
            print(f"❌ Ошибка поиска: {result.get('error')}")
            return
        
        items = result.get('items', [])
        if not items:
            print("❌ Предметы не найдены")
            return
        
        print(f"\n✅ Найдено предметов: {len(items)}")
        print(f"📊 Всего на площадке: {result.get('total_count', 0)}\n")
        
        # Берем первый предмет для детального парсинга
        first_item = items[0]
        hash_name = first_item.get('asset_description', {}).get('market_hash_name')
        
        if not hash_name:
            print("❌ Не удалось получить hash_name предмета")
            print(f"Данные предмета: {first_item}")
            return
        
        print(f"📦 Парсим предмет: {hash_name}")
        print(f"💰 Цена из API: {first_item.get('sell_price_text', 'N/A')}\n")
        
        # Парсим детальную страницу предмета
        print("⏳ Загружаю и парсю HTML страницу предмета...\n")
        parsed_data = await parser.get_item_details(730, hash_name)
        
        if parsed_data is None:
            print("❌ Не удалось распарсить страницу предмета")
            return
        
        # Выводим все распарсенные данные
        print("=" * 70)
        print("📊 РАСПАРСЕННЫЕ ДАННЫЕ:")
        print("=" * 70)
        
        # Float-значение
        if parsed_data.float_value is not None:
            print(f"✅ Float: {parsed_data.float_value:.6f} (получено автоматически через API)")
        else:
            print("⚠️  Float: не найдено")
            print("   (Парсер пытался получить через inspect API, но данные недоступны)")
        
        # Паттерн
        if parsed_data.pattern is not None:
            print(f"✅ Паттерн: {parsed_data.pattern} (получено автоматически через API)")
        else:
            print("⚠️  Паттерн: не найден")
            print("   (Парсер пытался получить через inspect API, но данные недоступны)")
        
        # Наклейки
        stickers = parsed_data.stickers
        if stickers:
            print(f"\n✅ Наклеек найдено: {len(stickers)}")
            print(f"💰 Общая цена наклеек: ${parsed_data.total_stickers_price:.2f}")
            print("\n📋 Детали наклеек:")
            for i, sticker in enumerate(stickers, 1):
                info_parts = []
                if sticker.position is not None:
                    info_parts.append(f"Позиция {sticker.position}")
                if sticker.wear:
                    # wear содержит название наклейки
                    info_parts.append(f"Наклейка: {sticker.wear}")
                if sticker.price is not None and sticker.price > 0:
                    info_parts.append(f"Цена: ${sticker.price:.2f}")
                print(f"  {i}. {', '.join(info_parts) if info_parts else 'Информация недоступна'}")
        else:
            print("\n❌ Наклейки: не найдено")
        
        # Дополнительная информация
        if parsed_data.item_name:
            print(f"\n📝 Название со страницы: {parsed_data.item_name}")
        if parsed_data.item_price:
            print(f"💰 Цена со страницы: ${parsed_data.item_price:.2f}")
        
        # Inspect ссылки
        if parsed_data.inspect_links:
            print(f"\n🔗 Inspect in Game ссылок: {len(parsed_data.inspect_links)}")
            if len(parsed_data.inspect_links) > 0:
                print(f"   Первая ссылка: {parsed_data.inspect_links[0][:100]}...")
                print("   💡 Inspect ссылки работают только при установленной игре CS:GO/CS2")
                print("   💡 Парсер автоматически пытается получить float/паттерн через API")
        
        print("\n" + "=" * 70)
        print("✅ Парсинг завершен!")
        print("=" * 70)
        print("\n💡 ВАЖНО:")
        print("   • Float и паттерн: Парсер автоматически пытается получить через inspect API")
        print("   • Цены наклеек: Получаются через Steam Market API (может быть медленно)")
        print("   • Inspect ссылки: Работают только при установленной игре CS:GO/CS2")


async def search_with_filters_example():
    """
    Пример поиска с фильтрами (float, паттерн, цена).
    """
    print("\n" + "=" * 70)
    print("🔍 ПРИМЕР ПОИСКА С ФИЛЬТРАМИ")
    print("=" * 70)
    
    filters = SearchFilters(
        item_name="AK-47 | Redline",
        float_range=FloatRange(min=0.10, max=0.25),  # Float от 0.10 до 0.25
        pattern_range=PatternRange(min=0, max=999, item_type="skin"),  # Любой паттерн
        max_price=50.0  # Максимальная цена $50
    )
    
    print(f"\n📋 Параметры поиска:")
    print(f"  - Предмет: {filters.item_name}")
    print(f"  - Float: {filters.float_range.min} - {filters.float_range.max}")
    print(f"  - Паттерн: {filters.pattern_range.min} - {filters.pattern_range.max}")
    print(f"  - Макс. цена: ${filters.max_price}\n")
    
    async with SteamMarketParser() as parser:
        result = await parser.search_items(filters, start=0, count=10)
        
        if not result['success']:
            print(f"❌ Ошибка: {result.get('error')}")
            return
        
        print(f"📊 Результаты:")
        print(f"  - Всего найдено на площадке: {result.get('total_count', 0)}")
        print(f"  - После фильтрации: {result.get('filtered_count', 0)}")
        print(f"  - В ответе: {len(result.get('items', []))}\n")
        
        items = result.get('items', [])
        if items:
            print("🎯 Найденные предметы (первые 5):")
            for i, item in enumerate(items[:5], 1):
                name = item.get('name', 'Unknown')
                price = item.get('sell_price_text', 'N/A')
                parsed = item.get('parsed_data', {})
                
                print(f"\n  {i}. {name} - {price}")
                if parsed:
                    if parsed.get('float_value') is not None:
                        print(f"     Float: {parsed['float_value']:.6f}")
                    if parsed.get('pattern') is not None:
                        print(f"     Паттерн: {parsed['pattern']}")
                    if parsed.get('stickers'):
                        print(f"     Наклеек: {len(parsed['stickers'])}")


async def main():
    """Главная функция - выберите, что хотите запустить."""
    print("\n" + "=" * 70)
    print("🧪 ПРИМЕРЫ ПАРСИНГА STEAM MARKET")
    print("=" * 70)
    print("\nЧто может спарсить скрипт:")
    print("  ✅ Float-значение предмета (0.0 - 1.0)")
    print("  ✅ Паттерн предмета (0-999 для скинов, 0-99999 для брелков)")
    print("  ✅ Информация о наклейках (позиция, потертость, цена)")
    print("  ✅ Название и цена предмета")
    print("  ✅ Фильтрация по всем параметрам")
    print("\n" + "=" * 70)
    
    # Пример 1: Парсинг одного предмета
    await parse_single_item_example()
    
    # Пример 2: Поиск с фильтрами (раскомментируйте, если нужно)
    # await search_with_filters_example()


if __name__ == "__main__":
    asyncio.run(main())

