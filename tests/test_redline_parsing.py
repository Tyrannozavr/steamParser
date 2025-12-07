"""
Простой тест для проверки парсинга AK-47 | Redline (Field-Tested) с паттерном 145.
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.steam_parser import SteamMarketParser
from core.models import SearchFilters, PatternList
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core.database import DatabaseManager
from core.config import Config
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

async def test_redline_parsing():
    """Тестирует парсинг AK-47 | Redline (Field-Tested) с паттерном 145."""
    logger.info("🧪 Начинаю тест парсинга AK-47 | Redline (Field-Tested)")
    
    # Подключение к БД
    db_manager = DatabaseManager(Config.DATABASE_URL)
    await db_manager.init_db()
    async_session = sessionmaker(db_manager.engine, class_=AsyncSession, expire_on_commit=False)
    
    # Подключение к Redis
    redis_service = RedisService(redis_url=Config.REDIS_URL)
    await redis_service.connect()
    
    # Создание ProxyManager
    async with async_session() as session:
        proxy_manager = ProxyManager(db_session=session, redis_service=redis_service)
        
        # Создание парсера
        parser = SteamMarketParser(
            proxy=None,
            timeout=30,
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        
        # Фильтры для поиска
        filters = SearchFilters(
            appid=730,
            item_name="AK-47 | Redline (Field-Tested)",
            max_price=50.0,
            pattern_list=PatternList(patterns=[145], item_type="skin")
        )
        
        logger.info(f"🔍 Ищу предмет: {filters.item_name}")
        logger.info(f"   Максимальная цена: ${filters.max_price}")
        logger.info(f"   Ищу паттерн: {filters.pattern_list.patterns}")
        
        # Выполняем поиск
        result = await parser.search_items(
            filters=filters,
            start=0,
            count=20,
            parse_all_pages=False  # Только первая страница для быстрого теста
        )
        
        logger.info(f"\n📊 Результаты парсинга:")
        logger.info(f"   success: {result.get('success')}")
        logger.info(f"   total_count: {result.get('total_count')}")
        logger.info(f"   filtered_count: {result.get('filtered_count')}")
        logger.info(f"   items: {len(result.get('items', []))}")
        
        # Проверяем найденные предметы
        items = result.get('items', [])
        if items:
            logger.info(f"\n✅ Найдено {len(items)} подходящих предметов:")
            for idx, item in enumerate(items[:5], 1):  # Показываем первые 5
                parsed_data = item.get('parsed_data', {})
                pattern = parsed_data.get('pattern')
                float_value = parsed_data.get('float_value')
                stickers = parsed_data.get('stickers', [])
                price = parsed_data.get('item_price', 0)
                
                logger.info(f"\n   {idx}. Предмет:")
                logger.info(f"      Цена: ${price:.2f}")
                logger.info(f"      Паттерн: {pattern}")
                logger.info(f"      Float: {float_value}")
                logger.info(f"      Наклеек: {len(stickers)}")
                if stickers:
                    sticker_names = [s.get('name') if isinstance(s, dict) else s.name for s in stickers]
                    logger.info(f"      Наклейки: {', '.join(sticker_names)}")
                
                # Проверяем, есть ли паттерн 145
                if pattern == 145:
                    logger.info(f"      🎯 НАЙДЕН ПАТТЕРН 145!")
        else:
            logger.warning(f"\n⚠️ Предметы не найдены")
        
        # Закрываем клиент
        await parser.close()
        
        await redis_service.disconnect()
        await db_manager.close()
        
        logger.info(f"\n✅ Тест завершен")

if __name__ == "__main__":
    asyncio.run(test_redline_parsing())

