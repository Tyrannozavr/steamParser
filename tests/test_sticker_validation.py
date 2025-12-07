"""
Простой тест валидации наклеек без pytest.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from services.filter_service import FilterService
from unittest.mock import Mock


def test_validation():
    """Тестирует валидацию цен."""
    print("=" * 70)
    print("🧪 ТЕСТИРОВАНИЕ ВАЛИДАЦИИ ЦЕН НАКЛЕЕК")
    print("=" * 70)
    
    filter_service = FilterService(
        base_price_manager=Mock(),
        proxy_manager=Mock(),
        redis_service=Mock()
    )
    
    # Тест 1: Подозрительно низкая базовая цена
    print("\n📋 Тест 1: Подозрительно низкая базовая цена")
    result = filter_service._validate_prices_for_overpay_calculation(
        current_price=442.88,
        base_price=0.24,  # Подозрительно низкая
        stickers_price=0.18,
        item_name="AK-47 | Redline (Minimal Wear)"
    )
    print(f"   Результат: valid={result['valid']}, reason={result['reason']}")
    assert not result['should_skip'], "Должно быть предупреждение, но не пропускать"
    assert "ПОДОЗРИТЕЛЬНО" in result['reason'], "Должно быть предупреждение о подозрительности"
    print("   ✅ Тест пройден")
    
    # Тест 2: Подозрительно низкая цена наклеек
    print("\n📋 Тест 2: Подозрительно низкая цена наклеек")
    result = filter_service._validate_prices_for_overpay_calculation(
        current_price=1289.05,
        base_price=50.0,
        stickers_price=0.18,  # Подозрительно низкая
        item_name="AK-47 | Redline (Minimal Wear)"
    )
    print(f"   Результат: valid={result['valid']}, reason={result['reason']}")
    assert "ПОДОЗРИТЕЛЬНО" in result['reason'], "Должно быть предупреждение"
    print("   ✅ Тест пройден")
    
    # Тест 3: Нормальные цены
    print("\n📋 Тест 3: Нормальные цены")
    result = filter_service._validate_prices_for_overpay_calculation(
        current_price=100.0,
        base_price=50.0,
        stickers_price=20.0,
        item_name="AK-47 | Redline (Minimal Wear)"
    )
    print(f"   Результат: valid={result['valid']}, reason={result['reason']}")
    assert result['valid'], "Должно быть валидно"
    assert "Данные валидны" in result['reason'], "Должно быть сообщение о валидности"
    print("   ✅ Тест пройден")
    
    # Тест 4: Расчет коэффициента переплаты
    print("\n📋 Тест 4: Расчет коэффициента переплаты")
    x = filter_service._calculate_overpay_coefficient(
        current_price=442.88,
        base_price=0.24,
        stickers_price=0.18
    )
    print(f"   Коэффициент: {x:.4f}")
    assert abs(x - 2459.1111) < 0.01, f"Ожидалось ~2459.1111, получено {x}"
    print("   ✅ Тест пройден")
    
    # Тест 5: Нулевая цена наклеек
    print("\n📋 Тест 5: Нулевая цена наклеек")
    result = filter_service._validate_prices_for_overpay_calculation(
        current_price=100.0,
        base_price=50.0,
        stickers_price=0.0,
        item_name="AK-47 | Redline (Minimal Wear)"
    )
    print(f"   Результат: valid={result['valid']}, should_skip={result['should_skip']}")
    assert result['should_skip'], "Должно пропускать при нулевой цене наклеек"
    print("   ✅ Тест пройден")
    
    print("\n" + "=" * 70)
    print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_validation()
    except AssertionError as e:
        print(f"\n❌ ОШИБКА ТЕСТА: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ НЕОЖИДАННАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

