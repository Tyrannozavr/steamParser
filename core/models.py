"""
Pydantic модели для параметров поиска предметов на Steam Market.
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class FloatRange(BaseModel):
    """Диапазон float-значений предмета."""
    min: float = Field(ge=0.0, le=1.0, description="Минимальное float значение")
    max: float = Field(ge=0.0, le=1.0, description="Максимальное float значение")

    @field_validator('max')
    @classmethod
    def validate_max_greater_than_min(cls, v, info):
        if 'min' in info.data and v < info.data['min']:
            raise ValueError('max должен быть больше или равен min')
        return v


class StickerInfo(BaseModel):
    """Информация о наклейке."""
    position: Optional[int] = Field(None, ge=0, le=4, description="Позиция наклейки (0-4, максимум 5 наклеек)")
    wear: Optional[str] = Field(None, description="Потертость наклейки")
    price: Optional[float] = Field(None, ge=0, description="Цена наклейки")
    name: Optional[str] = Field(None, description="Название наклейки")


class StickersFilter(BaseModel):
    """Фильтр по наклейкам с формулой S = D + (P * x)."""
    stickers: list[StickerInfo] = Field(default_factory=list, description="Список наклеек")
    total_stickers_price_min: Optional[float] = Field(None, ge=0, description="Минимальная общая цена наклеек")
    total_stickers_price_max: Optional[float] = Field(None, ge=0, description="Максимальная общая цена наклеек")
    
    # Новые поля для формулы S = D + (P * x)
    max_overpay_coefficient: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Максимальный коэффициент переплаты за наклейки (x в формуле S = D + (P * x))"
    )
    min_stickers_price: Optional[float] = Field(
        None,
        ge=0,
        description="Минимальная общая цена наклеек для применения формулы (P в формуле)"
    )

    @field_validator('total_stickers_price_max')
    @classmethod
    def validate_stickers_price_max(cls, v, info):
        if v is not None and 'total_stickers_price_min' in info.data:
            min_price = info.data.get('total_stickers_price_min')
            if min_price is not None and v < min_price:
                raise ValueError('total_stickers_price_max должен быть больше или равен total_stickers_price_min')
        return v


class PatternRange(BaseModel):
    """Диапазон паттерна предмета (устаревший, используйте PatternList)."""
    min: int = Field(ge=0, description="Минимальное значение паттерна")
    max: int = Field(ge=0, description="Максимальное значение паттерна")
    item_type: str = Field(description="Тип предмета: 'skin' или 'keychain'")

    @field_validator('max')
    @classmethod
    def validate_max_greater_than_min(cls, v, info):
        if 'min' in info.data and v < info.data['min']:
            raise ValueError('max должен быть больше или равен min')
        return v

    @field_validator('item_type')
    @classmethod
    def validate_item_type(cls, v):
        if v not in ['skin', 'keychain']:
            raise ValueError("item_type должен быть 'skin' или 'keychain'")
        return v

    @field_validator('min', 'max')
    @classmethod
    def validate_pattern_range(cls, v, info):
        item_type = info.data.get('item_type', '')
        if item_type == 'skin' and v > 999:
            raise ValueError('Для скинов паттерн должен быть в диапазоне 0-999')
        if item_type == 'keychain' and v > 99999:
            raise ValueError('Для брелков паттерн должен быть в диапазоне 0-99999')
        return v


class PatternList(BaseModel):
    """Список отслеживаемых паттернов."""
    patterns: list[int] = Field(description="Список конкретных паттернов для отслеживания")
    item_type: str = Field(description="Тип предмета: 'skin' или 'keychain'")

    @field_validator('item_type')
    @classmethod
    def validate_item_type(cls, v):
        if v not in ['skin', 'keychain']:
            raise ValueError("item_type должен быть 'skin' или 'keychain'")
        return v

    @field_validator('patterns')
    @classmethod
    def validate_patterns(cls, v, info):
        if not v:
            raise ValueError('Список паттернов не может быть пустым')
        
        item_type = info.data.get('item_type', '')
        if item_type == 'skin':
            invalid = [p for p in v if p < 0 or p > 999]
            if invalid:
                raise ValueError(f'Для скинов паттерны должны быть в диапазоне 0-999. Найдены невалидные: {invalid}')
        elif item_type == 'keychain':
            invalid = [p for p in v if p < 0 or p > 99999]
            if invalid:
                raise ValueError(f'Для брелков паттерны должны быть в диапазоне 0-99999. Найдены невалидные: {invalid}')
        return v


class SearchFilters(BaseModel):
    """Параметры поиска предметов на Steam Market."""
    item_name: str = Field(description="Название предмета для поиска")
    float_range: Optional[FloatRange] = Field(None, description="Диапазон float-значений")
    stickers_filter: Optional[StickersFilter] = Field(None, description="Фильтр по наклейкам")
    pattern_range: Optional[PatternRange] = Field(None, description="Диапазон паттерна (устаревший, используйте pattern_list)")
    pattern_list: Optional[PatternList] = Field(None, description="Список конкретных паттернов для отслеживания")
    max_price: Optional[float] = Field(None, ge=0, description="Максимальная цена покупки")
    appid: int = Field(default=730, description="ID приложения Steam (730 для CS:GO/CS2)")
    currency: int = Field(default=1, description="Валюта (1 = USD)")
    
    # Поля для автообновления базовой цены
    auto_update_base_price: bool = Field(
        default=False,
        description="Автоматически обновлять базовую цену (D) для этого фильтра"
    )
    base_price_update_interval: Optional[int] = Field(
        None,
        ge=60,
        description="Интервал обновления базовой цены в секундах (минимум 60)"
    )


class ParsedItemData(BaseModel):
    """Распарсенные данные о предмете."""
    float_value: Optional[float] = Field(None, ge=0.0, le=1.0, description="Float-значение предмета")
    pattern: Optional[int] = Field(None, ge=0, description="Паттерн предмета")
    stickers: list[StickerInfo] = Field(default_factory=list, description="Список наклеек")
    total_stickers_price: float = Field(default=0.0, ge=0.0, description="Общая цена наклеек")
    item_name: Optional[str] = Field(None, description="Название предмета")
    item_price: Optional[float] = Field(None, ge=0.0, description="Цена предмета")
    inspect_links: list[str] = Field(default_factory=list, description="Inspect in Game ссылки")
    item_type: Optional[str] = Field(None, description="Тип предмета: 'skin' или 'keychain'")
    is_stattrak: bool = Field(default=False, description="Является ли предмет StatTrak")
    listing_id: Optional[str] = Field(None, description="ID лота на Steam Market (для проверки дубликатов)")


class ItemBasePrice(BaseModel):
    """Базовая цена предмета (цена первого лота)."""
    item_name: str
    base_price: float
    last_updated: datetime
    appid: int = 730

