#!/usr/bin/env python3
"""
Тестовый скрипт для проверки парсинга цены наклейки из HTML.
Использует пример HTML из реальной страницы Steam Market.
"""
import sys
from pathlib import Path
import re
from bs4 import BeautifulSoup

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

# Пример HTML с реальной страницы Steam Market для наклейки
# Источник: https://steamcommunity.com/market/listings/730/Sticker%20%7C%20HellRaisers%20(Holo)%20%7C%20Katowice%202015
TEST_HTML = """
<div class="market_commodity_order_summary" id="market_commodity_forsale">
    <span class="market_commodity_orders_header_promote">6</span> for sale starting at 
    <span class="market_commodity_orders_header_promote">$323.33</span>
</div>
"""

def test_price_extraction(html: str, expected_price: float = None):
    """Тестирует извлечение цены из HTML."""
    print("=" * 80)
    print("🧪 Тестируем извлечение цены из HTML")
    print("=" * 80)
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Ищем элемент с ценой
    price_element = soup.find('div', {'id': 'market_commodity_forsale', 'class': 'market_commodity_order_summary'})
    
    if not price_element:
        print("❌ Элемент market_commodity_forsale не найден")
        # Пробуем альтернативный селектор
        price_element = soup.find('div', class_='market_commodity_order_summary')
        if price_element:
            print("✅ Найден элемент через альтернативный селектор")
    
    if not price_element:
        print("❌ Элемент не найден ни одним способом")
        return None
    
    # Извлекаем текст
    price_text = price_element.get_text(strip=True)
    print(f"📄 Текст элемента: '{price_text}'")
    
    # Ищем цену в формате $XXX.XX
    price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
    
    if price_match:
        price_str = price_match.group(1).replace(',', '')
        try:
            price = float(price_str)
            print(f"✅ Цена извлечена: ${price:.2f}")
            
            if expected_price:
                if abs(price - expected_price) < 0.01:
                    print(f"✅ Цена совпадает с ожидаемой: ${expected_price:.2f}")
                else:
                    print(f"⚠️ Цена не совпадает: ожидалось ${expected_price:.2f}, получено ${price:.2f}")
            
            return price
        except ValueError as e:
            print(f"❌ Ошибка парсинга цены '{price_str}': {e}")
            return None
    else:
        print(f"❌ Не удалось найти цену в тексте: '{price_text}'")
        return None


def test_multiple_formats():
    """Тестирует различные форматы HTML."""
    test_cases = [
        {
            'name': 'Стандартный формат',
            'html': '<div class="market_commodity_order_summary" id="market_commodity_forsale"><span class="market_commodity_orders_header_promote">6</span> for sale starting at <span class="market_commodity_orders_header_promote">$323.33</span></div>',
            'expected': 323.33
        },
        {
            'name': 'Формат с запятой',
            'html': '<div class="market_commodity_order_summary" id="market_commodity_forsale">10 for sale starting at $1,234.56</div>',
            'expected': 1234.56
        },
        {
            'name': 'Формат без пробелов',
            'html': '<div class="market_commodity_order_summary" id="market_commodity_forsale">1 for sale starting at $99.99</div>',
            'expected': 99.99
        },
        {
            'name': 'Только класс без id',
            'html': '<div class="market_commodity_order_summary">5 for sale starting at $50.00</div>',
            'expected': 50.00
        },
    ]
    
    print("\n" + "=" * 80)
    print("🧪 Тестируем различные форматы HTML")
    print("=" * 80 + "\n")
    
    success_count = 0
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nТест {i}: {test_case['name']}")
        print("-" * 80)
        price = test_price_extraction(test_case['html'], test_case['expected'])
        if price is not None and abs(price - test_case['expected']) < 0.01:
            success_count += 1
            print("✅ ТЕСТ ПРОЙДЕН")
        else:
            print("❌ ТЕСТ НЕ ПРОЙДЕН")
    
    print("\n" + "=" * 80)
    print(f"📊 ИТОГИ: {success_count}/{len(test_cases)} тестов пройдено")
    print("=" * 80)


if __name__ == "__main__":
    # Тест 1: Базовый пример
    print("\n" + "=" * 80)
    print("ТЕСТ 1: Базовый пример из реальной страницы")
    print("=" * 80)
    test_price_extraction(TEST_HTML, expected_price=323.33)
    
    # Тест 2: Различные форматы
    test_multiple_formats()
    
    print("\n✅ Все тесты завершены!")

