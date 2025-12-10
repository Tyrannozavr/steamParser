"""
Модуль для получения базовой цены предмета (цена первого лота).
"""
import httpx
from typing import Optional
from loguru import logger
import re


class BasePriceAPI:
    """API для получения базовой цены предмета (самого дешевого лота)."""
    
    STEAM_MARKET_PRICE_OVERVIEW_URL = "https://steamcommunity.com/market/priceoverview/"

    @staticmethod
    async def get_base_price(
        item_name: str,
        appid: int = 730,
        currency: int = 1,
        proxy: Optional[str] = None,
        timeout: int = 30,
        proxy_manager=None,
        max_retries: int = 3,
        sample_size: int = 5
    ) -> Optional[float]:
        """
        Получает базовую цену предмета через priceoverview API.
        
        Использует Steam Market priceoverview API для получения точной lowest_price
        для конкретного предмета по его точному названию. Это гарантирует, что
        мы получаем цену именно для нужного варианта предмета (например, Minimal Wear,
        а не Field-Tested).
        
        Args:
            item_name: Название предмета (точное, например "AK-47 | Redline (Minimal Wear)")
            appid: ID приложения (730 для CS:GO/CS2)
            currency: Валюта (1 = USD)
            proxy: Прокси-сервер (если указан, используется напрямую)
            timeout: Таймаут запроса
            proxy_manager: ProxyManager для ротации прокси при 429 ошибках (опционально)
            max_retries: Максимальное количество попыток с разными прокси
            sample_size: Не используется (оставлено для совместимости)
            
        Returns:
            Базовая цена (lowest_price) в USD или None при ошибке
        """
        current_proxy = proxy
        current_proxy_obj = None
        used_proxies = set()  # Отслеживаем использованные прокси
        
        for attempt in range(max_retries):
            try:
                # Получаем прокси через proxy_manager, если он доступен
                if proxy_manager and not current_proxy:
                    current_proxy_obj = await proxy_manager.get_next_proxy(force_refresh=(attempt > 0))
                    if current_proxy_obj:
                        current_proxy = current_proxy_obj.url
                        used_proxies.add(current_proxy)
                        logger.debug(f"    🌐 BasePriceAPI: Используем прокси ID={current_proxy_obj.id} для базовой цены")
                elif proxy_manager and attempt > 0:
                    # Пробуем другой прокси при повторной попытке
                    logger.info(f"    🔄 BasePriceAPI: Попытка {attempt + 1}/{max_retries} с другим прокси для '{item_name}'")
                    # ВАЖНО: Используем force_refresh=False, чтобы не обращаться к БД
                    next_proxy = await proxy_manager.get_next_proxy(force_refresh=False)
                    if next_proxy and next_proxy.url not in used_proxies:
                        current_proxy = next_proxy.url
                        current_proxy_obj = next_proxy
                        used_proxies.add(current_proxy)
                        logger.info(f"    🌐 BasePriceAPI: Используем прокси ID={next_proxy.id} для базовой цены")
                    elif current_proxy:
                        # Если все прокси использованы, ждем и пробуем снова
                        logger.warning(f"    ⚠️ BasePriceAPI: Все прокси использованы, ждем перед повторной попыткой")
                        import asyncio
                        await asyncio.sleep(2.0 * attempt)  # Экспоненциальная задержка
                
                # Формируем параметры для priceoverview API
                params = {
                    'appid': appid,
                    'currency': currency,
                    'market_hash_name': item_name  # Используем точное название предмета
                }
                
                logger.debug(f"    🌐 BasePriceAPI: Запрашиваем priceoverview для '{item_name}'")
                
                async with httpx.AsyncClient(proxy=current_proxy, timeout=timeout) as client:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "application/json",
                        "Referer": "https://steamcommunity.com/market/"
                    }
                    
                    response = await client.get(
                        BasePriceAPI.STEAM_MARKET_PRICE_OVERVIEW_URL,
                        params=params,
                        headers=headers
                    )
                    
                    if response.status_code == 429:
                        logger.warning(f"    ⚠️ BasePriceAPI: 429 ошибка при получении базовой цены для '{item_name}' (попытка {attempt + 1}/{max_retries})")
                        if proxy_manager and current_proxy_obj:
                            # Отмечаем прокси как заблокированный
                            await proxy_manager.mark_proxy_used(
                                current_proxy_obj,
                                success=False,
                                error="429 Too Many Requests",
                                is_429_error=True
                            )
                        if attempt < max_retries - 1:
                            import asyncio
                            await asyncio.sleep(1.0 * (attempt + 1))  # Задержка перед следующей попыткой
                            current_proxy = None  # Сбрасываем прокси для следующей попытки
                            continue
                        else:
                            logger.error(f"    ❌ BasePriceAPI: Превышено количество попыток для получения базовой цены '{item_name}'")
                            return None
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Проверяем успешность ответа
                    if data.get("success") == True:
                        # Извлекаем lowest_price из ответа
                        lowest_price_str = data.get("lowest_price", "")
                        if lowest_price_str:
                            # Парсим цену (формат: "$302.27" или "302,27 USD")
                            price_match = re.search(r'[\d,]+\.?\d*', lowest_price_str.replace(',', ''))
                            if price_match:
                                try:
                                    price = float(price_match.group(0).replace(',', ''))
                                    logger.info(f"    ✅ BasePriceAPI: Базовая цена получена для '{item_name}': ${price:.2f} (lowest_price из priceoverview)")
                                    return price
                                except ValueError:
                                    logger.warning(f"    ⚠️ BasePriceAPI: Не удалось преобразовать цену '{lowest_price_str}' в число")
                            else:
                                logger.warning(f"    ⚠️ BasePriceAPI: Не удалось извлечь цену из строки '{lowest_price_str}'")
                        else:
                            logger.warning(f"    ⚠️ BasePriceAPI: Поле 'lowest_price' отсутствует в ответе для '{item_name}'")
                    else:
                        logger.warning(f"    ⚠️ BasePriceAPI: API вернул success=False для '{item_name}': {data.get('message', 'Unknown error')}")
                        # Если предмет не найден, возвращаем None
                        if "No listings" in str(data.get("message", "")) or "not found" in str(data.get("message", "")).lower():
                            logger.warning(f"    ⚠️ BasePriceAPI: Предмет '{item_name}' не найден на Steam Market")
                            return None

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Уже обработано выше
                    continue
                else:
                    logger.warning(f"    ⚠️ BasePriceAPI: HTTP ошибка {e.response.status_code} при получении базовой цены для '{item_name}'")
                    if attempt < max_retries - 1:
                        import asyncio
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    return None
            except Exception as e:
                logger.warning(f"    ⚠️ BasePriceAPI: Ошибка при получении базовой цены для '{item_name}': {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return None

        return None

