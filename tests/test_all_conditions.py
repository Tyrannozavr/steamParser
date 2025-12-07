#!/usr/bin/env python3
"""
Тестовый скрипт для проверки всех состояний предмета.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from parsers.item_page_parser import ItemPageParser
from core.steam_parser import SteamMarketParser
from core.config import Config
from services.redis_service import RedisService
from loguru import logger

async def test_all_conditions():
    """Тестируем парсинг всех состояний предмета."""
    
    # Настройка логирования
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")
    
    # Инициализация сервисов
    redis_service = None
    if Config.REDIS_ENABLED:
        redis_service = RedisService(Config.REDIS_URL)
    
    # Создаем парсер
    parser = SteamMarketParser(redis_service=redis_service)
    
    # Параметры для теста
    appid = 730
    base_hash_name = "AK-47 | Redline"
    target_listing_id = "733651971153157038"
    
    # Все возможные состояния
    conditions = [
        "(Battle-Scarred)",
        "(Well-Worn)",
        "(Field-Tested)",
        "(Minimal Wear)",
        "(Factory New)"
    ]
    
    logger.info(f"🔍 Ищем listing_id: {target_listing_id}")
    logger.info(f"📦 Проверяем все состояния предмета: {base_hash_name}")
    
    found = False
    
    async with parser:
        for condition in conditions:
            hash_name = f"{base_hash_name} {condition}"
            logger.info(f"\n{'='*60}")
            logger.info(f"🔍 Проверяем: {hash_name}")
            logger.info(f"{'='*60}")
            
            try:
                # Получаем первую страницу
                html = await parser._fetch_item_page(appid, hash_name, page=1)
                if not html:
                    logger.warning(f"⚠️ Не удалось загрузить первую страницу для {condition}")
                    continue
                
                page_parser = ItemPageParser(html)
                total_count = page_parser.get_total_listings_count()
                
                if total_count:
                    logger.info(f"📊 Всего лотов: {total_count}")
                    total_pages = (total_count + 9) // 10
                    logger.info(f"📊 Всего страниц: {total_pages}")
                    
                    # Проверяем первые 5 страниц для каждого состояния
                    max_pages = min(total_pages, 5)
                    for page in range(1, max_pages + 1):
                        if page > 1:
                            await asyncio.sleep(1)
                            html = await parser._fetch_item_page(appid, hash_name, page=page)
                            if not html:
                                break
                            page_parser = ItemPageParser(html)
                        
                        listings = page_parser.get_all_listings()
                        logger.info(f"📋 Страница {page}: Найдено {len(listings)} лотов")
                        
                        # Проверяем каждый лот
                        for listing in listings:
                            listing_id = listing.get('listing_id')
                            price = listing.get('price')
                            
                            if listing_id == target_listing_id:
                                found = True
                                logger.info(f"\n{'='*60}")
                                logger.info(f"✅✅✅ НАЙДЕН! ✅✅✅")
                                logger.info(f"📦 Состояние: {condition}")
                                logger.info(f"📄 Страница: {page}")
                                logger.info(f"💰 Цена: ${price:.2f}")
                                logger.info(f"🆔 Listing ID: {listing_id}")
                                logger.info(f"🔗 Inspect: {listing.get('inspect_link', 'N/A')}")
                                logger.info(f"{'='*60}\n")
                                return
                            
                            # Также проверяем, есть ли этот listing_id в HTML
                            if listing_id and str(target_listing_id) in str(listing_id):
                                logger.info(f"🔍 Похожий listing_id найден: {listing_id} (цена: ${price:.2f if price else 'N/A'})")
                
                else:
                    logger.warning(f"⚠️ Не удалось определить количество лотов для {condition}")
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при проверке {condition}: {e}")
                continue
    
    if not found:
        logger.error(f"\n{'='*60}")
        logger.error(f"❌ Listing ID {target_listing_id} не найден ни в одном состоянии!")
        logger.error(f"{'='*60}\n")

if __name__ == "__main__":
    asyncio.run(test_all_conditions())

