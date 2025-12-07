#!/usr/bin/env python3
"""
Тестовый скрипт для проверки получения цен наклеек напрямую со страницы товара.
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
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}", level="DEBUG")

# Список наклеек из логов для тестирования
# Тестируем только одну наклейку для детальной отладки
TEST_STICKERS = [
    "HellRaisers (Holo) | Katowice 2015",
]


async def test_sticker_price(sticker_name: str):
    """Тестирует получение цены для одной наклейки."""
    logger.info(f"\n{'='*80}")
    logger.info(f"🧪 Тестируем наклейку: '{sticker_name}'")
    logger.info(f"{'='*80}")
    
    try:
        # Тестируем новый метод получения цены со страницы
        price = await StickerPricesAPI._get_price_from_item_page(
            sticker_name=sticker_name,
            appid=730,
            currency=1,
            proxy=None,
            timeout=15,
            redis_service=None,
            proxy_manager=None
        )
        
        if price is not None:
            logger.info(f"✅ УСПЕХ: Цена найдена через страницу товара: ${price:.2f}")
            return True, price
        else:
            logger.warning(f"❌ НЕУДАЧА: Цена не найдена через страницу товара")
            return False, None
            
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {type(e).__name__}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False, None


async def main():
    """Основная функция тестирования."""
    logger.info("🚀 Начинаем тестирование получения цен наклеек со страницы товара")
    logger.info(f"📋 Всего наклеек для тестирования: {len(TEST_STICKERS)}\n")
    
    results = []
    success_count = 0
    fail_count = 0
    
    for sticker_name in TEST_STICKERS:
        success, price = await test_sticker_price(sticker_name)
        results.append({
            'sticker': sticker_name,
            'success': success,
            'price': price
        })
        
        if success:
            success_count += 1
        else:
            fail_count += 1
        
        # Небольшая задержка между запросами
        await asyncio.sleep(1.0)
    
    # Выводим итоговую статистику
    logger.info(f"\n{'='*80}")
    logger.info(f"📊 ИТОГОВАЯ СТАТИСТИКА")
    logger.info(f"{'='*80}")
    logger.info(f"✅ Успешно: {success_count}/{len(TEST_STICKERS)} ({success_count/len(TEST_STICKERS)*100:.1f}%)")
    logger.info(f"❌ Неудачно: {fail_count}/{len(TEST_STICKERS)} ({fail_count/len(TEST_STICKERS)*100:.1f}%)")
    
    logger.info(f"\n📋 Детальные результаты:")
    for result in results:
        if result['success']:
            logger.info(f"   ✅ {result['sticker']}: ${result['price']:.2f}")
        else:
            logger.warning(f"   ❌ {result['sticker']}: цена не найдена")
    
    return success_count, fail_count


if __name__ == "__main__":
    success, fail = asyncio.run(main())
    sys.exit(0 if success > 0 else 1)

