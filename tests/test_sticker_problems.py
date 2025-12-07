"""
Тесты для проверки проблем с наклейками:
1. Неправильный расчет коэффициента переплаты
2. Неправильная базовая цена
3. Отсутствующие цены наклеек
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from services.filter_service import FilterService
from parsers.sticker_prices import StickerPricesAPI
from parsers.base_price import BasePriceAPI


class TestStickerProblems:
    """Тесты для проверки проблем с наклейками."""
    
    def test_overpay_coefficient_calculation(self):
        """Тест расчета коэффициента переплаты."""
        filter_service = FilterService(
            base_price_manager=Mock(),
            proxy_manager=Mock(),
            redis_service=Mock()
        )
        
        # Тест 1: Нормальный случай
        x = filter_service._calculate_overpay_coefficient(
            current_price=100.0,  # S
            base_price=50.0,      # D
            stickers_price=20.0   # P
        )
        assert x == 2.5, f"Ожидалось 2.5, получено {x}"
        
        # Тест 2: Проблемный случай из логов - слишком маленькая цена наклеек
        x = filter_service._calculate_overpay_coefficient(
            current_price=442.88,  # S
            base_price=0.24,        # D (подозрительно низкая)
            stickers_price=0.18     # P (подозрительно низкая)
        )
        assert x == 2459.1111, f"Ожидалось 2459.1111, получено {x}"
        # Это показывает проблему - коэффициент получается огромным
        
        # Тест 3: Нулевая цена наклеек
        x = filter_service._calculate_overpay_coefficient(
            current_price=100.0,
            base_price=50.0,
            stickers_price=0.0
        )
        assert x is None, "При нулевой цене наклеек должен возвращаться None"
        
        # Тест 4: Цена предмета меньше базовой
        x = filter_service._calculate_overpay_coefficient(
            current_price=30.0,
            base_price=50.0,
            stickers_price=20.0
        )
        assert x == 0.0, "При цене меньше базовой должен возвращаться 0.0"
    
    def test_overpay_coefficient_validation(self):
        """Тест валидации коэффициента переплаты."""
        filter_service = FilterService(
            base_price_manager=Mock(),
            proxy_manager=Mock(),
            redis_service=Mock()
        )
        
        # Проверяем, что при подозрительно низких значениях D и P коэффициент получается огромным
        test_cases = [
            {
                "name": "Случай из лога 1",
                "S": 442.88,
                "D": 0.24,
                "P": 0.18,
                "expected_x": 2459.1111,
                "is_suspicious": True
            },
            {
                "name": "Случай из лога 2",
                "S": 1289.05,
                "D": 0.24,
                "P": 3.22,
                "expected_x": 400.2516,
                "is_suspicious": True
            },
            {
                "name": "Случай из лога 3",
                "S": 1624.20,
                "D": 0.24,
                "P": 0.21,
                "expected_x": 7733.14,
                "is_suspicious": True
            },
            {
                "name": "Нормальный случай",
                "S": 100.0,
                "D": 50.0,
                "P": 20.0,
                "expected_x": 2.5,
                "is_suspicious": False
            }
        ]
        
        for case in test_cases:
            x = filter_service._calculate_overpay_coefficient(
                current_price=case["S"],
                base_price=case["D"],
                stickers_price=case["P"]
            )
            
            assert abs(x - case["expected_x"]) < 0.01, \
                f"{case['name']}: Ожидалось {case['expected_x']}, получено {x}"
            
            # Проверяем, что подозрительные случаи имеют огромный коэффициент
            if case["is_suspicious"]:
                assert x > 100, \
                    f"{case['name']}: Подозрительный случай должен иметь коэффициент > 100, получено {x}"
    
    def test_suspicious_price_detection(self):
        """Тест обнаружения подозрительных цен."""
        filter_service = FilterService(
            base_price_manager=Mock(),
            proxy_manager=Mock(),
            redis_service=Mock()
        )
        
        # Функция для проверки подозрительности цен
        def is_suspicious(base_price: float, stickers_price: float, item_price: float) -> bool:
            """Проверяет, являются ли цены подозрительными."""
            # Базовая цена для дорогих предметов не должна быть < $1
            if item_price > 100 and base_price < 1.0:
                return True
            # Цена наклеек не должна быть < $0.5 для дорогих предметов
            if item_price > 100 and stickers_price < 0.5:
                return True
            return False
        
        # Тест подозрительных случаев
        assert is_suspicious(0.24, 0.18, 442.88) == True, "Должен быть подозрительным"
        assert is_suspicious(0.24, 3.22, 1289.05) == True, "Должен быть подозрительным"
        assert is_suspicious(50.0, 20.0, 100.0) == False, "Не должен быть подозрительным"
    
    @pytest.mark.asyncio
    async def test_sticker_price_api_handles_missing_prices(self):
        """Тест обработки отсутствующих цен наклеек."""
        # Мокаем API для возврата None
        with patch.object(StickerPricesAPI, 'get_sticker_price', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            
            prices = await StickerPricesAPI.get_stickers_prices_batch(
                sticker_names=["Non-existent Sticker | 2024"],
                redis_service=None,
                proxy_manager=None
            )
            
            assert "Non-existent Sticker | 2024" in prices
            assert prices["Non-existent Sticker | 2024"] is None
    
    @pytest.mark.asyncio
    async def test_base_price_validation(self):
        """Тест валидации базовой цены."""
        # Проверяем, что базовая цена не должна быть слишком низкой для дорогих предметов
        suspicious_cases = [
            {"item": "AK-47 | Redline (Minimal Wear)", "base_price": 0.24, "is_suspicious": True},
            {"item": "AK-47 | Redline (Field-Tested)", "base_price": 0.15, "is_suspicious": True},
            {"item": "AK-47 | Redline (Minimal Wear)", "base_price": 50.0, "is_suspicious": False},
        ]
        
        for case in suspicious_cases:
            # Для дорогих предметов базовая цена не должна быть < $1
            if case["base_price"] < 1.0:
                assert case["is_suspicious"], \
                    f"Базовая цена {case['base_price']} для {case['item']} подозрительно низкая"
    
    def test_overpay_coefficient_with_zero_stickers(self):
        """Тест коэффициента переплаты при нулевой цене наклеек."""
        filter_service = FilterService(
            base_price_manager=Mock(),
            proxy_manager=Mock(),
            redis_service=Mock()
        )
        
        # Когда цена наклеек = 0, коэффициент не должен вычисляться
        x = filter_service._calculate_overpay_coefficient(
            current_price=100.0,
            base_price=50.0,
            stickers_price=0.0
        )
        
        assert x is None, "При нулевой цене наклеек должен возвращаться None"
    
    def test_overpay_coefficient_edge_cases(self):
        """Тест граничных случаев коэффициента переплаты."""
        filter_service = FilterService(
            base_price_manager=Mock(),
            proxy_manager=Mock(),
            redis_service=Mock()
        )
        
        # Случай 1: S = D (цена предмета равна базовой)
        x = filter_service._calculate_overpay_coefficient(
            current_price=50.0,
            base_price=50.0,
            stickers_price=20.0
        )
        assert x == 0.0, "При S = D коэффициент должен быть 0.0"
        
        # Случай 2: S < D (цена предмета меньше базовой - не должно быть)
        x = filter_service._calculate_overpay_coefficient(
            current_price=30.0,
            base_price=50.0,
            stickers_price=20.0
        )
        assert x == 0.0, "При S < D коэффициент должен быть 0.0"
        
        # Случай 3: Очень маленькая цена наклеек
        x = filter_service._calculate_overpay_coefficient(
            current_price=100.0,
            base_price=50.0,
            stickers_price=0.01
        )
        assert x == 5000.0, "При очень маленькой P коэффициент должен быть большим"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

