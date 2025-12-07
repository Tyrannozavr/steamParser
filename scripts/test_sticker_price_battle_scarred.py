#!/usr/bin/env python3
"""
Скрипт для тестирования получения цены наклейки "Sticker | Battle Scarred"
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.sticker_prices import StickerPricesAPI
from loguru import logger

async def main():
    sticker_name = "Sticker | Battle Scarred"
    
    logger.info(f"🔍 Запрашиваем цену для наклейки: '{sticker_name}'")
    
    try:
        # Сначала пробуем получить HTML страницы напрямую для анализа
        import httpx
        from urllib.parse import quote
        
        encoded_name = quote(sticker_name, safe='')
        url = f"https://steamcommunity.com/market/listings/730/{encoded_name}"
        logger.info(f"🔍 Загружаем HTML страницы: {url}")
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if response.status_code == 200:
                html = response.text
                # Ищем цену в HTML
                import re
                price_match = re.search(
                    r'<span[^>]*class=["\']market_commodity_orders_header_promote["\'][^>]*>\$?([\d,]+\.?\d*)</span>',
                    html,
                    re.IGNORECASE
                )
                if price_match:
                    all_matches = re.findall(
                        r'<span[^>]*class=["\']market_commodity_orders_header_promote["\'][^>]*>\$?([\d,]+\.?\d*)</span>',
                        html,
                        re.IGNORECASE
                    )
                    logger.info(f"📊 Найдено совпадений в HTML: {len(all_matches)}, значения: {all_matches}")
                    if all_matches:
                        # Берем последний (там обычно цена)
                        price_from_html = float(all_matches[-1].replace(',', ''))
                        logger.info(f"💰 Цена из HTML (последний span): ${price_from_html:.2f}")
        
        # Запрашиваем цену без прокси и Redis (для простоты)
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
            logger.info(f"✅ Цена наклейки '{sticker_name}': ${price:.2f}")
            print(f"\n{'='*60}")
            print(f"Наклейка: {sticker_name}")
            print(f"Цена: ${price:.2f} USD")
            print(f"{'='*60}\n")
            return price
        else:
            logger.warning(f"⚠️ Не удалось получить цену для наклейки '{sticker_name}'")
            print(f"\n{'='*60}")
            print(f"Наклейка: {sticker_name}")
            print(f"Цена: Не найдена")
            print(f"{'='*60}\n")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка при получении цены: {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(f"\n{'='*60}")
        print(f"Ошибка: {e}")
        print(f"{'='*60}\n")
        return None

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result is not None else 1)

