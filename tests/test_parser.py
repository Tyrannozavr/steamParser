"""
Тестовый скрипт для проверки парсинга Steam Market.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import SearchFilters, FloatRange, PatternRange, StickersFilter, StickerInfo
import pytest

pytest_plugins = ('pytest_asyncio',)


async def main():
    """Основная функция для тестирования."""
    print("=" * 60)
    print("🧪 Тестирование парсера Steam Market")
    print("=" * 60)

    # Пример 1: Простой поиск без фильтров
    print("\n📌 Тест 1: Простой поиск")
    filters1 = SearchFilters(
        item_name="AK-47 | Redline",
        max_price=50.0
    )
    await test_single_request(filters1)

    # Пример 2: Поиск с float и паттерном
    print("\n" + "=" * 60)
    print("📌 Тест 2: Поиск с float и паттерном")
    filters2 = SearchFilters(
        item_name="AK-47 | Redline",
        float_range=FloatRange(min=0.10, max=0.20),
        pattern_range=PatternRange(min=100, max=200, item_type="skin"),
        max_price=30.0
    )
    await test_single_request(filters2)

    # Пример 3: Поиск с наклейками
    print("\n" + "=" * 60)
    print("📌 Тест 3: Поиск с фильтром по наклейкам")
    filters3 = SearchFilters(
        item_name="AK-47 | Redline",
        stickers_filter=StickersFilter(
            stickers=[
                StickerInfo(position=0, price=5.0),
                StickerInfo(position=1, price=3.0)
            ],
            total_stickers_price_min=5.0,
            total_stickers_price_max=20.0
        ),
        max_price=40.0
    )
    await test_single_request(filters3)

    # Пример 4: Поиск с прокси (закомментировано, так как нужен реальный прокси)
    # print("\n" + "=" * 60)
    # print("📌 Тест 4: Поиск с прокси")
    # filters4 = SearchFilters(item_name="AK-47 | Redline", max_price=50.0)
    # await test_single_request(filters4, proxy="http://user:pass@proxy:port")

    print("\n" + "=" * 60)
    print("✅ Тестирование завершено")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

