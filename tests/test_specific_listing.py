#!/usr/bin/env python3
"""
Тест для конкретного listing элемента.
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


async def test_specific_listing():
    """Тестирует конкретный listing элемент."""
    
    # HTML элемент из запроса пользователя
    listing_html = '''<div class="market_listing_row market_recent_listing_row listing_762925820507418058" id="listing_762925820507418058">
	<div class="market_listing_item_img_container">		
		<img id="listing_762925820507418058_image" src="https://community.fastly.steamstatic.com/economy/image/i0CoZ81Ui0m-9KwlBY1L_18myuGuq1wfhWSaZgMttyVfPaERSR0Wqmu7LAocGIGz3UqlXOLrxM-vMGmW8VNxu5Dx60noTyLwlcK3wiFO0POlPPNSI_-RHGavzedxuPUnFniykEtzsWWBzoyuIiifaAchDZUjTOZe4RC_w4buM-6z7wzbgokUyzK-0H08hRGDMA/62fx62f" srcset="https://community.fastly.steamstatic.com/economy/image/i0CoZ81Ui0m-9KwlBY1L_18myuGuq1wfhWSaZgMttyVfPaERSR0Wqmu7LAocGIGz3UqlXOLrxM-vMGmW8VNxu5Dx60noTyLwlcK3wiFO0POlPPNSI_-RHGavzedxuPUnFniykEtzsWWBzoyuIiifaAchDZUjTOZe4RC_w4buM-6z7wzbgokUyzK-0H08hRGDMA/62fx62f 1x, https://community.fastly.steamstatic.com/economy/image/i0CoZ81Ui0m-9KwlBY1L_18myuGuq1wfhWSaZgMttyVfPaERSR0Wqmu7LAocGIGz3UqlXOLrxM-vMGmW8VNxu5Dx60noTyLwlcK3wiFO0POlPPNSI_-RHGavzedxuPUnFniykEtzsWWBzoyuIiifaAchDZUjTOZe4RC_w4buM-6z7wzbgokUyzK-0H08hRGDMA/62fx62fdpx2x 2x" style="border-color: #d32ce6;background-color: #3d293f;" class="market_listing_item_img economy_item_hoverable" alt="">	
	</div>
	<div class="market_listing_price_listings_block">
		<div class="market_listing_right_cell market_listing_action_buttons">
			<div class="market_listing_buy_button">
				<a href="javascript:BuyMarketListing('listing', '762925820507418058', 730, '2', '48050774302')" class="item_market_action_button btn_green_white_innerfade btn_small">
					<span>Buy Now</span>
				</a>
			</div>
		</div>
		<div class="market_listing_right_cell market_listing_their_price">
			<span class="market_table_value">
				<span class="market_listing_price market_listing_price_with_fee">$816.80 USD</span>
				<span class="market_listing_price market_listing_price_with_publisher_fee_only">$781.29 USD</span>
				<span class="market_listing_price market_listing_price_without_fee">$710.27 USD</span>
				<br>
			</span>
		</div>
		<div class="market_listing_right_cell">
			<div class="market_listing_row_action"><a href="steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M762925820507418058A48050774302D14865329898664371505">Inspect in Game...</a></div>
		</div>
	</div>
	<div class="market_listing_item_name_block">
		<span class="market_listing_item_name economy_item_hoverable" id="listing_762925820507418058_name" style="color: #d32ce6;">AK-47 | Redline (Minimal Wear)</span>
		<br>
		<div class="market_listing_row_details economy_item_hoverable" id="listing_762925820507418058_details">
			<br><div id="sticker_info" class="sticker_info" style="width=100; margin:4px; padding:8px;"><img width="64" height="48" src="https://cdn.steamstatic.com/apps/730/icons/econ/stickers/eslkatowice2015/hellraisers_holo.9d838b302ef030c9a04501db6324d6d20492c3dd.png"><img width="64" height="48" src="https://cdn.steamstatic.com/apps/730/icons/econ/stickers/eslkatowice2015/hellraisers_holo.9d838b302ef030c9a04501db6324d6d20492c3dd.png"><img width="64" height="48" src="https://cdn.steamstatic.com/apps/730/icons/econ/stickers/eslkatowice2015/hellraisers_holo.9d838b302ef030c9a04501db6324d6d20492c3dd.png"><img width="64" height="48" src="https://cdn.steamstatic.com/apps/730/icons/econ/stickers/eslkatowice2015/hellraisers_holo.9d838b302ef030c9a04501db6324d6d20492c3dd.png"></div>
		</div>
	</div>
	<div style="clear: both;"></div>
</div>'''
    
    logger.info("="*80)
    logger.info("🧪 ТЕСТ КОНКРЕТНОГО LISTING ЭЛЕМЕНТА")
    logger.info("="*80)
    logger.info(f"   Listing ID: 762925820507418058")
    logger.info(f"   Цена предмета: $816.80 USD")
    logger.info(f"   Предмет: AK-47 | Redline (Minimal Wear)")
    logger.info("")
    
    # Извлекаем HTML с наклейками
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(listing_html, 'html.parser')
    sticker_div = soup.find('div', id='sticker_info')
    
    if not sticker_div:
        logger.error("❌ Не найден div с наклейками!")
        return
    
    sticker_html = str(sticker_div)
    logger.info("📋 HTML с наклейками:")
    logger.info(f"   {sticker_html[:200]}...")
    logger.info("")
    
    # Парсим наклейки
    logger.info("🔍 ШАГ 1: Парсинг наклеек из HTML...")
    stickers = StickerParser.parse_stickers_from_html(sticker_html)
    
    if not stickers:
        logger.warning("⚠️ Наклейки не найдены в HTML!")
        logger.info("   Пробуем альтернативный способ...")
        # Пробуем найти изображения напрямую
        images = sticker_div.find_all('img')
        logger.info(f"   Найдено изображений: {len(images)}")
        for idx, img in enumerate(images):
            logger.info(f"   Изображение {idx}: src={img.get('src', '')[:80]}...")
    else:
        logger.info(f"✅ Найдено наклеек: {len(stickers)}")
        for sticker in stickers:
            logger.info(f"   - {sticker.name} (позиция {sticker.position})")
    logger.info("")
    
    # Если наклейки не найдены через title, пробуем определить по URL изображения
    if not stickers:
        logger.info("🔍 ШАГ 1.1: Пробуем определить наклейки по URL изображений...")
        images = sticker_div.find_all('img')
        # Из URL видно: eslkatowice2015/hellraisers_holo
        # Это HellRaisers (Holo) | Katowice 2015
        sticker_name = "HellRaisers (Holo) | Katowice 2015"
        from core import StickerInfo
        stickers = [StickerInfo(position=i, name=sticker_name, wear=sticker_name, price=None) for i in range(len(images))]
        logger.info(f"✅ Определено наклеек по URL: {len(stickers)}")
        for sticker in stickers:
            logger.info(f"   - {sticker.name} (позиция {sticker.position})")
        logger.info("")
    
    if not stickers:
        logger.error("❌ Не удалось определить наклейки!")
        return
    
    # Получаем цены
    logger.info("💰 ШАГ 2: Получение цен наклеек...")
    
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
        # Создаем resolver
        resolver = StickerPriceResolver(
            sticker_prices_api=StickerPricesAPI,
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        
        # Получаем цены
        sticker_names = [s.name for s in stickers]
        logger.info(f"   Запрашиваем цены для: {sticker_names}")
        
        prices = await resolver.get_stickers_prices(
            sticker_names,
            appid=730,
            currency=1,
            proxy=proxy_url,
            delay=0.2,
            use_fuzzy_matching=True
        )
        
        # Вычисляем общую цену
        total_price = 0.0
        logger.info("")
        logger.info("📊 РЕЗУЛЬТАТЫ:")
        logger.info("="*80)
        for sticker in stickers:
            price = prices.get(sticker.name)
            if price is not None:
                total_price += price
                logger.info(f"   ✅ {sticker.name}: ${price:.2f}")
            else:
                logger.warning(f"   ❌ {sticker.name}: цена не найдена")
        
        logger.info("")
        logger.info(f"💵 ОБЩАЯ ЦЕНА НАКЛЕЕК: ${total_price:.2f}")
        logger.info(f"🔍 Фильтр: min_stickers_price = $200.00")
        
        if total_price >= 200.0:
            logger.info(f"✅ ПРОХОДИТ ФИЛЬТР! (${total_price:.2f} >= $200.00)")
        else:
            logger.info(f"❌ НЕ ПРОХОДИТ фильтр (${total_price:.2f} < $200.00)")
        logger.info("="*80)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await session.close()
        await redis_service.disconnect()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(test_specific_listing())

