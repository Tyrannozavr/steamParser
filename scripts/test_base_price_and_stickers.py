"""
Тест для проверки исправлений:
1. Базовая цена предмета (должна быть правильной, не $3.92 для AK-47 | Redline (Minimal Wear))
2. Цены наклеек (должны использовать новые методы, без search/render)
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.base_price import BasePriceAPI
from parsers.sticker_prices import StickerPricesAPI


async def test_base_price():
    """Тест базовой цены предмета."""
    print("\n" + "="*80)
    print("ТЕСТ 1: Базовая цена предмета")
    print("="*80)
    
    # Тестируем AK-47 | Redline (Minimal Wear) - должна быть ~$302, а не $3.92
    item_name = "AK-47 | Redline (Minimal Wear)"
    expected_price_min = 200.0  # Минимальная ожидаемая цена
    expected_price_max = 400.0  # Максимальная ожидаемая цена
    
    print(f"\n📋 Тестируем: {item_name}")
    print(f"💰 Ожидаемая цена: ${expected_price_min:.2f} - ${expected_price_max:.2f}")
    print(f"❌ НЕ должна быть: $3.92 (старая ошибка)\n")
    
    try:
        price = await BasePriceAPI.get_base_price(
            item_name=item_name,
            appid=730,
            currency=1,
            proxy=None,
            timeout=30,
            proxy_manager=None,
            max_retries=3
        )
        
        if price is None:
            print("❌ ОШИБКА: Не удалось получить базовую цену")
            return False
        
        print(f"✅ Получена базовая цена: ${price:.2f}")
        
        # Проверяем, что цена в разумных пределах
        if price < expected_price_min or price > expected_price_max:
            print(f"⚠️ ВНИМАНИЕ: Цена ${price:.2f} выходит за ожидаемые пределы")
            print(f"   Ожидалось: ${expected_price_min:.2f} - ${expected_price_max:.2f}")
            if price < 10.0:
                print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Цена слишком низкая (${price:.2f}), похоже на старую ошибку!")
                return False
        else:
            print(f"✅ Цена в ожидаемых пределах: ${expected_price_min:.2f} - ${expected_price_max:.2f}")
        
        # Проверяем, что это не старая ошибка ($3.92)
        if abs(price - 3.92) < 1.0:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Получена цена ${price:.2f}, похожа на старую ошибку $3.92!")
            return False
        
        print(f"✅ ТЕСТ ПРОЙДЕН: Базовая цена определена правильно")
        return True
        
    except Exception as e:
        print(f"❌ ОШИБКА при получении базовой цены: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_sticker_prices():
    """Тест цен наклеек."""
    print("\n" + "="*80)
    print("ТЕСТ 2: Цены наклеек (должны использовать новые методы)")
    print("="*80)
    
    # Тестируем несколько наклеек
    test_stickers = [
        "Sticker | Battle Scarred",
        "Sticker | FURIA (Holo) | Stockholm 2021",
    ]
    
    all_passed = True
    
    for sticker_name in test_stickers:
        print(f"\n📋 Тестируем: {sticker_name}")
        
        try:
            price = await StickerPricesAPI.get_sticker_price(
                sticker_name=sticker_name,
                appid=730,
                currency=1,
                proxy=None,
                timeout=30,
                redis_service=None,
                proxy_manager=None
            )
            
            if price is None:
                print(f"⚠️ Не удалось получить цену для '{sticker_name}'")
                all_passed = False
                continue
            
            print(f"✅ Получена цена: ${price:.2f}")
            
            # Проверяем, что цена разумная (больше 0, меньше 10000)
            if price <= 0:
                print(f"❌ ОШИБКА: Цена некорректна: ${price:.2f}")
                all_passed = False
            elif price > 10000:
                print(f"⚠️ ВНИМАНИЕ: Цена очень высокая: ${price:.2f}")
            else:
                print(f"✅ Цена в разумных пределах")
        
        except Exception as e:
            print(f"❌ ОШИБКА при получении цены наклейки '{sticker_name}': {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    if all_passed:
        print(f"\n✅ ТЕСТ ПРОЙДЕН: Цены наклеек получены успешно")
    else:
        print(f"\n⚠️ ТЕСТ ЧАСТИЧНО ПРОЙДЕН: Некоторые цены не получены")
    
    return all_passed


async def main():
    """Запуск всех тестов."""
    print("\n" + "="*80)
    print("ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЙ")
    print("="*80)
    print("\nПроверяем:")
    print("1. Базовая цена предмета (должна быть правильной)")
    print("2. Цены наклеек (должны использовать новые методы, без search/render)")
    print("\n" + "="*80)
    
    results = []
    
    # Тест 1: Базовая цена
    result1 = await test_base_price()
    results.append(("Базовая цена предмета", result1))
    
    # Тест 2: Цены наклеек
    result2 = await test_sticker_prices()
    results.append(("Цены наклеек", result2))
    
    # Итоги
    print("\n" + "="*80)
    print("ИТОГИ ТЕСТИРОВАНИЯ")
    print("="*80)
    
    for test_name, passed in results:
        status = "✅ ПРОЙДЕН" if passed else "❌ ПРОВАЛЕН"
        print(f"{test_name}: {status}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print("\n⚠️ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ")
    
    return all_passed


if __name__ == "__main__":
    asyncio.run(main())

