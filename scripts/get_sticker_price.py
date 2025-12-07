"""
Скрипт для получения цены наклейки через основной код.
Использует StickerPricesAPI из parsers/sticker_prices.py
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.sticker_prices import StickerPricesAPI
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(
    lambda msg: print(msg, end=''),
    format="{time:HH:mm:ss} | {level: <8} | {message}",
    level="INFO"
)


async def get_sticker_price(sticker_name: str):
    """Получает цену наклейки через основной API."""
    logger.info(f"🔍 Запрашиваем цену для наклейки: '{sticker_name}'")
    
    try:
        # Используем основной метод из StickerPricesAPI
        # Без прокси и redis_service для простоты (можно добавить при необходимости)
        price = await StickerPricesAPI.get_sticker_price(
            sticker_name=sticker_name,
            appid=730,
            currency=1,
            proxy=None,
            timeout=10,
            redis_service=None,
            proxy_manager=None
        )
        
        if price is not None:
            logger.info(f"✅ Цена наклейки '{sticker_name}': ${price:.2f} USD")
            return price
        else:
            logger.warning(f"⚠️ Цена для наклейки '{sticker_name}' не найдена")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка при получении цены для '{sticker_name}': {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def main():
    """Основная функция."""
    stickers = [
        "Sticker | Battle Scarred",
        "Sticker | FURIA (Holo) | Stockholm 2021"
    ]
    
    print("=" * 80)
    print("🔍 Получение цен наклеек через основной код")
    print("=" * 80)
    print()
    
    results = {}
    for sticker_name in stickers:
        print()
        price = await get_sticker_price(sticker_name)
        results[sticker_name] = price
        print()
    
    print("=" * 80)
    print("📊 РЕЗУЛЬТАТЫ:")
    print("=" * 80)
    for sticker_name, price in results.items():
        if price is not None:
            print(f"✅ {sticker_name}: ${price:.2f} USD")
        else:
            print(f"❌ {sticker_name}: цена не найдена")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())


