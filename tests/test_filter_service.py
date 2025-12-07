"""
Тесты для FilterService.
Покрывают проверку паттерна и float на основе реальных данных из логов.
"""
import pytest
from core.models import SearchFilters, FloatRange, PatternList
from services.filter_service import FilterService


class TestFilterServiceFloat:
    """Тесты для проверки float-значений."""
    
    def setup_method(self):
        """Настройка перед каждым тестом."""
        self.filter_service = FilterService()
    
    def test_float_in_range(self):
        """Тест: float в диапазоне должен проходить проверку."""
        # Данные из логов: Float: 0.350107, диапазон: 0.35 - 0.36
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float(0.350107, filters)
        assert result is True, "Float 0.350107 должен проходить проверку в диапазоне 0.35-0.36"
    
    def test_float_at_min_boundary(self):
        """Тест: float на минимальной границе должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float(0.35, filters)
        assert result is True, "Float 0.35 (минимальная граница) должен проходить"
    
    def test_float_at_max_boundary(self):
        """Тест: float на максимальной границе должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float(0.36, filters)
        assert result is True, "Float 0.36 (максимальная граница) должен проходить"
    
    def test_float_below_min(self):
        """Тест: float ниже минимального значения не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float(0.349999, filters)
        assert result is False, "Float 0.349999 должен не проходить (ниже минимума)"
    
    def test_float_above_max(self):
        """Тест: float выше максимального значения не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float(0.360001, filters)
        assert result is False, "Float 0.360001 должен не проходить (выше максимума)"
    
    def test_float_none_without_filter(self):
        """Тест: float None без фильтра должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)"
        )
        
        result = self.filter_service.check_float(None, filters)
        assert result is True, "Float None без фильтра должен проходить"
    
    def test_float_none_with_filter(self):
        """Тест: float None с фильтром не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float(None, filters)
        assert result is False, "Float None с фильтром не должен проходить"
    
    def test_float_string_conversion(self):
        """Тест: float как строка должен нормализоваться."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        result = self.filter_service.check_float("0.350107", filters)
        assert result is True, "Float как строка '0.350107' должен нормализоваться и проходить"
    
    def test_float_precision(self):
        """Тест: проверка точности float значений."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36)
        )
        
        # Тестируем различные значения с разной точностью
        test_cases = [
            (0.350000, True, "Минимум"),
            (0.350001, True, "Чуть выше минимума"),
            (0.355000, True, "Середина диапазона"),
            (0.359999, True, "Чуть ниже максимума"),
            (0.360000, True, "Максимум"),
            (0.349999, False, "Ниже минимума"),
            (0.360001, False, "Выше максимума"),
        ]
        
        for float_value, expected, description in test_cases:
            result = self.filter_service.check_float(float_value, filters)
            assert result == expected, f"{description}: float {float_value} должен {'проходить' if expected else 'не проходить'}"


class TestFilterServicePattern:
    """Тесты для проверки паттернов."""
    
    def setup_method(self):
        """Настройка перед каждым тестом."""
        self.filter_service = FilterService()
    
    def test_pattern_in_list(self):
        """Тест: паттерн в списке должен проходить проверку."""
        # Данные из логов: Паттерн: 522, фильтр: [522]
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        result = self.filter_service.check_pattern(522, filters, item_type="skin")
        assert result is True, "Паттерн 522 должен проходить проверку в списке [522]"
    
    def test_pattern_not_in_list(self):
        """Тест: паттерн не в списке не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        result = self.filter_service.check_pattern(523, filters, item_type="skin")
        assert result is False, "Паттерн 523 не должен проходить (не в списке [522])"
    
    def test_pattern_multiple_patterns(self):
        """Тест: паттерн в списке с несколькими паттернами."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_list=PatternList(patterns=[522, 523, 524], item_type="skin")
        )
        
        test_cases = [
            (522, True, "Первый паттерн в списке"),
            (523, True, "Второй паттерн в списке"),
            (524, True, "Третий паттерн в списке"),
            (525, False, "Паттерн не в списке"),
        ]
        
        for pattern, expected, description in test_cases:
            result = self.filter_service.check_pattern(pattern, filters, item_type="skin")
            assert result == expected, f"{description}: паттерн {pattern} должен {'проходить' if expected else 'не проходить'}"
    
    def test_pattern_none_without_filter(self):
        """Тест: паттерн None без фильтра должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)"
        )
        
        result = self.filter_service.check_pattern(None, filters)
        assert result is True, "Паттерн None без фильтра должен проходить"
    
    def test_pattern_none_with_filter(self):
        """Тест: паттерн None с фильтром не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        result = self.filter_service.check_pattern(None, filters, item_type="skin")
        assert result is False, "Паттерн None с фильтром не должен проходить"
    
    def test_pattern_string_conversion(self):
        """Тест: паттерн как строка должен нормализоваться."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        result = self.filter_service.check_pattern("522", filters, item_type="skin")
        assert result is True, "Паттерн как строка '522' должен нормализоваться и проходить"
    
    def test_pattern_skin_vs_keychain(self):
        """Тест: фильтр для скинов не должен применяться к брелкам."""
        filters = SearchFilters(
            item_name="Keychain",
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        # Брелок с паттерном 522, но фильтр для скинов - должен проходить (пропускаем фильтр)
        result = self.filter_service.check_pattern(522, filters, item_type="keychain")
        assert result is True, "Брелок должен проходить проверку, если фильтр для скинов"
    
    def test_pattern_keychain_vs_skin(self):
        """Тест: фильтр для брелков не должен применяться к скинам."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_list=PatternList(patterns=[1000], item_type="keychain")
        )
        
        # Скин с паттерном 522, но фильтр для брелков - должен проходить (пропускаем фильтр)
        result = self.filter_service.check_pattern(522, filters, item_type="skin")
        assert result is True, "Скин должен проходить проверку, если фильтр для брелков"
    
    def test_pattern_range(self):
        """Тест: проверка паттерна в диапазоне (старый формат)."""
        from core.models import PatternRange
        
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            pattern_range=PatternRange(min=520, max=525, item_type="skin")
        )
        
        test_cases = [
            (520, True, "Минимум диапазона"),
            (522, True, "Внутри диапазона"),
            (525, True, "Максимум диапазона"),
            (519, False, "Ниже минимума"),
            (526, False, "Выше максимума"),
        ]
        
        for pattern, expected, description in test_cases:
            result = self.filter_service.check_pattern(pattern, filters, item_type="skin")
            assert result == expected, f"{description}: паттерн {pattern} должен {'проходить' if expected else 'не проходить'}"


class TestFilterServiceCombined:
    """Тесты для комбинированной проверки float и паттерна (на основе реальных данных)."""
    
    def setup_method(self):
        """Настройка перед каждым тестом."""
        self.filter_service = FilterService()
    
    def test_real_case_from_logs(self):
        """Тест: реальный случай из логов - лот #765177620331184862."""
        # Данные из логов:
        # Лот: Цена: $45.73, Float: 0.350107, Паттерн: 522
        # Задача: Float: 0.35 - 0.36, Паттерны: 522 (skin), Макс. цена: $50.0
        
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36),
            pattern_list=PatternList(patterns=[522], item_type="skin"),
            max_price=50.0
        )
        
        # Проверка float
        float_result = self.filter_service.check_float(0.350107, filters)
        assert float_result is True, "Float 0.350107 должен проходить проверку"
        
        # Проверка паттерна
        pattern_result = self.filter_service.check_pattern(522, filters, item_type="skin")
        assert pattern_result is True, "Паттерн 522 должен проходить проверку"
        
        # Проверка цены
        item = {"sell_price_text": "$45.73"}
        price_result = self.filter_service.check_price(item, filters)
        assert price_result is True, "Цена $45.73 должна проходить проверку (макс. $50.0)"
    
    def test_float_out_of_range_pattern_ok(self):
        """Тест: float вне диапазона, паттерн OK - не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36),
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        float_result = self.filter_service.check_float(0.37, filters)
        assert float_result is False, "Float 0.37 не должен проходить (вне диапазона)"
        
        pattern_result = self.filter_service.check_pattern(522, filters, item_type="skin")
        assert pattern_result is True, "Паттерн 522 должен проходить"
        
        # Общий результат: не проходит из-за float
        assert float_result is False
    
    def test_float_ok_pattern_not_in_list(self):
        """Тест: float OK, паттерн не в списке - не должен проходить."""
        filters = SearchFilters(
            item_name="AK-47 | Redline (Field-Tested)",
            float_range=FloatRange(min=0.35, max=0.36),
            pattern_list=PatternList(patterns=[522], item_type="skin")
        )
        
        float_result = self.filter_service.check_float(0.350107, filters)
        assert float_result is True, "Float 0.350107 должен проходить"
        
        pattern_result = self.filter_service.check_pattern(523, filters, item_type="skin")
        assert pattern_result is False, "Паттерн 523 не должен проходить (не в списке)"
        
        # Общий результат: не проходит из-за паттерна
        assert pattern_result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

