"""
Тестовый скрипт для проверки парсинга с фильтром по паттерну.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from core import DatabaseManager, MonitoringTask, SearchFilters, PatternList
from services import ParsingService, ProxyManager
from services.redis_service import RedisService
from loguru import logger

async def test_parsing_with_pattern_filter():
    """Тестирует парсинг с фильтром по паттерну."""
    logger.info("🧪 Начинаем тест парсинга с фильтром по паттерну")
    
    # Инициализируем БД
    db_manager = DatabaseManager("steam_monitor.db")
    await db_manager.init_db()
    db_session = await db_manager.get_session()
    
    try:
        # Инициализируем Redis
        redis_service = RedisService(redis_url="redis://localhost:6379/0")
        await redis_service.connect()
        logger.info("✅ Redis подключен")
        
        # Инициализируем ProxyManager
        proxy_manager = ProxyManager(db_session, redis_service=redis_service)
        
        # Инициализируем ParsingService
        parsing_service = ParsingService(
            db_session=db_session,
            proxy_manager=proxy_manager,
            redis_service=redis_service
        )
        
        # Создаем фильтры с паттерном 960
        filters = SearchFilters(
            item_name="M249 | Downtown",
            appid=730,
            currency=1,
            max_price=1.06,
            pattern_list=PatternList(patterns=[960], item_type="skin")
        )
        
        logger.info(f"📋 Фильтры для теста:")
        logger.info(f"   Предмет: {filters.item_name}")
        logger.info(f"   Макс. цена: {filters.max_price}")
        logger.info(f"   Паттерны: {filters.pattern_list.patterns if filters.pattern_list else None}")
        logger.info(f"   Тип: {filters.pattern_list.item_type if filters.pattern_list else None}")
        
        # Выполняем парсинг
        logger.info("🚀 Начинаем парсинг...")
        result = await parsing_service.parse_items(filters, start=0, count=10)
        
        logger.info(f"📊 Результат парсинга:")
        logger.info(f"   success: {result.get('success')}")
        logger.info(f"   total_count: {result.get('total_count', 0)}")
        logger.info(f"   filtered_count: {result.get('filtered_count', 0)}")
        logger.info(f"   items: {len(result.get('items', []))}")
        
        if result.get('items'):
            logger.info("✅ Найдены предметы:")
            for item in result.get('items', []):
                parsed_data = item.get('parsed_data', {})
                logger.info(f"   - {item.get('name', 'Unknown')}")
                logger.info(f"     Float: {parsed_data.get('float_value')}")
                logger.info(f"     Pattern: {parsed_data.get('pattern')}")
                logger.info(f"     Price: ${item.get('sell_price_text', 'N/A')}")
        else:
            logger.warning("⚠️ Предметы не найдены")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db_session.close()
        if redis_service.is_connected():
            await redis_service.disconnect()

if __name__ == "__main__":
    asyncio.run(test_parsing_with_pattern_filter())

