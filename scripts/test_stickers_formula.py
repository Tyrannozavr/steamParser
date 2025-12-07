"""
Скрипт для тестирования формулы наклеек S = D + (P * x)
Получает данные предмета и вычисляет все параметры для создания задачи.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import SearchFilters, SteamMarketParser
from services import BasePriceManager
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


async def test_stickers_formula(item_name: str = "AK-47 | Redline"):
    """
    Тестирует формулу наклеек для предмета.
    
    Args:
        item_name: Название предмета для тестирования
    """
    print("=" * 80)
    print(f"🧪 ТЕСТИРОВАНИЕ ФОРМУЛЫ НАКЛЕЕК: S = D + (P * x)")
    print("=" * 80)
    print(f"📦 Предмет: {item_name}\n")
    
    # Инициализируем парсер (без прокси для теста)
    parser = SteamMarketParser()
    await parser._ensure_client()
    
    try:
        # 1. Ищем предмет через API
        print("🔍 Шаг 1: Поиск предмета через Steam API...")
        filters = SearchFilters(item_name=item_name, max_price=100.0)
        result = await parser.search_items(filters, start=0, count=5)
        
        if not result['success']:
            print(f"❌ Ошибка поиска: {result.get('error')}")
            return
        
        items = result.get('items', [])
        if not items:
            print("❌ Предметы не найдены")
            return
        
        print(f"✅ Найдено предметов: {len(items)}")
        print(f"📊 Всего на площадке: {result.get('total_count', 0)}\n")
        
        # 2. Берем первый предмет с наклейками (уже распарсенный)
        print("🔍 Шаг 2: Поиск предмета с наклейками...")
        item_with_stickers = None
        for item in items:
            parsed_data = item.get('parsed_data')
            if parsed_data and parsed_data.get('stickers'):
                total_stickers_price = parsed_data.get('total_stickers_price', 0)
                if total_stickers_price > 0:
                    item_with_stickers = item
                    print(f"✅ Найден предмет с наклейками: {item.get('name', 'Unknown')}")
                    break
        
        if not item_with_stickers:
            print("⚠️ Не найдено предметов с наклейками в распарсенных результатах")
            print("💡 Попробуйте запустить с прокси или подождите, пока парсер обработает больше предметов")
            print("\n📊 Показываю данные первого предмета (если есть):")
            if items:
                first_item = items[0]
                parsed_data = first_item.get('parsed_data')
                if parsed_data:
                    print(f"   Предмет: {first_item.get('name', 'Unknown')}")
                    print(f"   Наклеек: {len(parsed_data.get('stickers', []))}")
                    print(f"   Цена наклеек: ${parsed_data.get('total_stickers_price', 0):.2f}")
            return
        
        # 3. Получаем данные предмета
        parsed_data = item_with_stickers.get('parsed_data', {})
        item_name_full = item_with_stickers.get('name', item_name)
        current_price = parsed_data.get('item_price') or item_with_stickers.get('sell_price_text', '0').replace('$', '').replace(' USD', '').strip()
        
        # Преобразуем цену в число
        try:
            if isinstance(current_price, str):
                current_price = float(current_price.replace(',', ''))
            else:
                current_price = float(current_price)
        except:
            # Пробуем получить из sell_price
            sell_price = item_with_stickers.get('sell_price', 0)
            current_price = sell_price / 100.0 if sell_price else 0
        
        stickers = parsed_data.get('stickers', [])
        total_stickers_price = parsed_data.get('total_stickers_price', 0.0)
        float_value = parsed_data.get('float_value')
        pattern = parsed_data.get('pattern')
        
        print("=" * 80)
        print("📊 ДАННЫЕ ПРЕДМЕТА:")
        print("=" * 80)
        print(f"📦 Название: {item_name_full}")
        print(f"💰 Текущая цена (S): ${current_price:.2f}")
        if float_value is not None:
            print(f"🎯 Float: {float_value:.6f}")
        if pattern is not None:
            print(f"🔢 Паттерн: {pattern}")
        print(f"🏷️ Наклеек: {len(stickers)}")
        print(f"💰 Общая цена наклеек (P): ${total_stickers_price:.2f}")
        
        if stickers:
            print(f"\n📋 Детали наклеек:")
            for i, sticker in enumerate(stickers[:5], 1):
                sticker_name = sticker.get('name', 'Unknown')
                sticker_price = sticker.get('price', 0)
                sticker_position = sticker.get('position')
                print(f"  {i}. Поз. {sticker_position}: {sticker_name} - ${sticker_price:.2f}")
            if len(stickers) > 5:
                print(f"  ... и еще {len(stickers) - 5} наклеек")
        
        # 4. Получаем базовую цену (D)
        print("\n" + "=" * 80)
        print("🔍 Шаг 3: Получение базовой цены (D)...")
        print("=" * 80)
        
        base_price_manager = BasePriceManager()
        base_price = await base_price_manager.get_base_price(
            item_name,
            730,  # CS2 appid
            force_update=False,
            proxy=None
        )
        
        if base_price is None:
            print("⚠️ Не удалось получить базовую цену автоматически")
            print("💡 Вы можете указать базовую цену вручную при создании задачи")
        else:
            print(f"✅ Базовая цена (D): ${base_price:.2f}")
        
        # 5. Вычисляем коэффициент переплаты (x)
        print("\n" + "=" * 80)
        print("🧮 ВЫЧИСЛЕНИЕ ФОРМУЛЫ: S = D + (P * x)")
        print("=" * 80)
        
        if base_price and total_stickers_price > 0:
            # x = (S - D) / P
            overpay_coefficient = (current_price - base_price) / total_stickers_price
            
            print(f"📐 Формула: x = (S - D) / P")
            print(f"📐 Расчет: x = (${current_price:.2f} - ${base_price:.2f}) / ${total_stickers_price:.2f}")
            print(f"📐 Результат: x = ${current_price - base_price:.2f} / ${total_stickers_price:.2f}")
            print(f"✅ Коэффициент переплаты (x): {overpay_coefficient:.4f} ({overpay_coefficient * 100:.2f}%)")
            
            # Проверяем формулу
            calculated_price = base_price + (total_stickers_price * overpay_coefficient)
            print(f"\n✅ Проверка: S = D + (P * x)")
            print(f"   ${base_price:.2f} + (${total_stickers_price:.2f} * {overpay_coefficient:.4f}) = ${calculated_price:.2f}")
            print(f"   Фактическая цена: ${current_price:.2f}")
            print(f"   Разница: ${abs(current_price - calculated_price):.2f}")
        else:
            print("⚠️ Невозможно вычислить коэффициент переплаты:")
            if not base_price:
                print("   - Базовая цена не получена")
            if total_stickers_price <= 0:
                print("   - Нет наклеек или цена наклеек = 0")
            overpay_coefficient = None
        
        # 6. Рекомендации для создания задачи
        print("\n" + "=" * 80)
        print("📋 РЕКОМЕНДАЦИИ ДЛЯ СОЗДАНИЯ ЗАДАЧИ В TELEGRAM БОТЕ:")
        print("=" * 80)
        print(f"\n📦 Название предмета: {item_name}")
        print(f"💰 Максимальная цена: ${current_price * 1.1:.2f} (текущая цена + 10%)")
        
        if float_value is not None:
            float_min = max(0.0, float_value - 0.05)
            float_max = min(1.0, float_value + 0.05)
            print(f"🎯 Float диапазон: {float_min:.3f} - {float_max:.3f}")
        
        if pattern is not None:
            print(f"🔢 Паттерн: {pattern}")
        
        if overpay_coefficient is not None:
            # Рекомендуем коэффициент немного больше текущего
            recommended_coefficient = min(1.0, overpay_coefficient * 1.2)
            print(f"\n📊 ПАРАМЕТРЫ ФОРМУЛЫ НАКЛЕЕК:")
            print(f"   Максимальный коэффициент переплаты (x): {recommended_coefficient:.4f} ({recommended_coefficient * 100:.2f}%)")
            print(f"   Текущий коэффициент: {overpay_coefficient:.4f} ({overpay_coefficient * 100:.2f}%)")
            print(f"   Минимальная цена наклеек (P): ${total_stickers_price * 0.8:.2f} (80% от текущей)")
        
        print("\n" + "=" * 80)
        print("✅ Тестирование завершено!")
        print("=" * 80)
        
    finally:
        await parser.close()


if __name__ == "__main__":
    # Можно указать другой предмет
    item_name = sys.argv[1] if len(sys.argv) > 1 else "AK-47 | Redline"
    asyncio.run(test_stickers_formula(item_name))

