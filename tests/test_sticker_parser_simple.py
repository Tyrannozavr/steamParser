#!/usr/bin/env python3
"""
Простой тест для проверки парсинга наклеек и получения цен.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.utils.sticker_parser import StickerParser, StickerPriceResolver
from parsers.sticker_prices import StickerPricesAPI
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.config import Config
from core.database import DatabaseManager
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")


async def test_sticker_parsing():
    """Тестирует парсинг наклеек из HTML."""
    
    # Пример HTML с наклейками
    sticker_html = '''
    <img title="Sticker: Crown (Foil)" src="...">
    <img title="Sticker: Bosh (Holo)" src="...">
    <img title="Sticker: Bish (Holo)" src="...">
    <img title="Sticker: Bash (Holo)" src="...">
    <img title="Sticker: MOUZ | Austin 2025" src="...">
    '''
    
    logger.info("🧪 Тест 1: Парсинг наклеек из HTML")
    stickers = StickerParser.parse_stickers_from_html(sticker_html)
    logger.info(f"   Найдено наклеек: {len(stickers)}")
    for sticker in stickers:
        logger.info(f"   - {sticker.name} (позиция {sticker.position})")
    logger.info("")
    
    # Пример asset item
    asset_item = {
        'descriptions': [
            {
                'name': 'sticker_info',
                'value': sticker_html
            }
        ]
    }
    
    logger.info("🧪 Тест 2: Парсинг наклеек из asset item")
    stickers = StickerParser.parse_stickers_from_asset(asset_item)
    logger.info(f"   Найдено наклеек: {len(stickers)}")
    for sticker in stickers:
        logger.info(f"   - {sticker.name} (позиция {sticker.position})")
    logger.info("")


async def test_sticker_prices():
    """Тестирует получение цен наклеек."""
    
    # Инициализируем компоненты
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    session = await db_manager.get_session()
    
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    proxy_manager = ProxyManager(session, redis_service=redis_service)
    proxy_obj = await proxy_manager.get_next_proxy(force_refresh=False)
    proxy_url = proxy_obj.url if proxy_obj else None
    
    try:
        logger.info("🧪 Тест 3: Получение цен наклеек")
        
        # Создаем resolver
        resolver = StickerPriceResolver(
            sticker_prices_api=StickerPricesAPI,
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        
        # Тестируем разные варианты названий
        test_cases = [
            ['Crown (Foil)', 'Bosh (Holo)', 'Bish (Holo)', 'Bash (Holo)', 'MOUZ | Austin 2025'],
            ['Team EnVyUs | Cluj-Napoca 2015', 'Team EnVyUs | Cologne 2015'],
            ['Crown Foil', 'Bosh Holo'],  # Без скобок
        ]
        
        for idx, sticker_names in enumerate(test_cases, 1):
            logger.info(f"   Тест 3.{idx}: {sticker_names}")
            prices = await resolver.get_stickers_prices(
                sticker_names,
                appid=730,
                currency=1,
                proxy=proxy_url,
                delay=0.1,
                use_fuzzy_matching=True
            )
            
            total = sum(p for p in prices.values() if p is not None)
            logger.info(f"      Получено цен: {len([p for p in prices.values() if p is not None])} из {len(sticker_names)}")
            logger.info(f"      Общая цена: ${total:.2f}")
            for name, price in prices.items():
                if price is not None:
                    logger.info(f"      ✅ {name}: ${price:.2f}")
                else:
                    logger.warning(f"      ❌ {name}: цена не найдена")
            logger.info("")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


async def main():
    """Запускает все тесты."""
    logger.info("="*80)
    logger.info("🧪 ТЕСТИРОВАНИЕ ПАРСИНГА НАКЛЕЕК И ПОЛУЧЕНИЯ ЦЕН")
    logger.info("="*80)
    logger.info("")
    
    await test_sticker_parsing()
    await test_sticker_prices()
    
    logger.info("="*80)
    logger.info("✅ Все тесты завершены")
    logger.info("="*80)


if __name__ == "__main__":
    asyncio.run(main())

