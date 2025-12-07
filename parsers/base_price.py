"""
Модуль для получения базовой цены предмета (цена первого лота).
"""
import httpx
from typing import Optional
from loguru import logger


class BasePriceAPI:
    """API для получения базовой цены предмета (самого дешевого лота)."""
    
    STEAM_MARKET_SEARCH_URL = "https://steamcommunity.com/market/search/render/"

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
        Получает базовую цену предмета, усредняя несколько первых лотов.
        
        Использует Steam Market API с сортировкой по цене (asc),
        берет несколько первых лотов и вычисляет среднюю цену для более точного результата.
        Это помогает избежать ошибок, когда первый лот может быть с наклейками или иметь аномальную цену.
        
        Args:
            item_name: Название предмета
            appid: ID приложения (730 для CS:GO/CS2)
            currency: Валюта (1 = USD)
            proxy: Прокси-сервер (если указан, используется напрямую)
            timeout: Таймаут запроса
            proxy_manager: ProxyManager для ротации прокси при 429 ошибках (опционально)
            max_retries: Максимальное количество попыток с разными прокси
            sample_size: Количество первых лотов для усреднения (по умолчанию 5)
            
        Returns:
            Средняя цена первых лотов в USD или None при ошибке
        """
        current_proxy = proxy
        used_proxies = set()  # Отслеживаем использованные прокси
        
        for attempt in range(max_retries):
            try:
                # Если есть proxy_manager и получили 429, пробуем другой прокси
                if proxy_manager and attempt > 0:
                    logger.info(f"    🔄 BasePriceAPI: Попытка {attempt + 1}/{max_retries} с другим прокси для '{item_name}'")
                    next_proxy = await proxy_manager.get_next_proxy(force_refresh=False)
                    if next_proxy and next_proxy.url not in used_proxies:
                        current_proxy = next_proxy.url
                        used_proxies.add(current_proxy)
                        logger.info(f"    🌐 BasePriceAPI: Используем прокси ID={next_proxy.id} для базовой цены")
                    elif current_proxy:
                        # Если все прокси использованы, ждем и пробуем снова
                        logger.warning(f"    ⚠️ BasePriceAPI: Все прокси использованы, ждем перед повторной попыткой")
                        import asyncio
                        await asyncio.sleep(2.0 * attempt)  # Экспоненциальная задержка
                
                async with httpx.AsyncClient(proxy=current_proxy, timeout=timeout) as client:
                    params = {
                        "query": item_name,
                        "start": 0,
                        "count": sample_size,  # Берем несколько первых лотов для усреднения
                        "search_descriptions": 0,
                        "sort_column": "price",
                        "sort_dir": "asc",  # Сортировка по возрастанию цены
                        "appid": appid,
                        "currency": currency,
                        "norender": 1
                    }

                    response = await client.get(
                        BasePriceAPI.STEAM_MARKET_SEARCH_URL,
                        params=params,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        }
                    )
                    response.raise_for_status()
                    data = response.json()

                    if data.get("success") and data.get("results"):
                        results = data["results"]
                        prices = []
                        
                        # Извлекаем цены из всех полученных лотов
                        for item in results:
                            price = None
                            
                            # Пробуем разные поля для цены
                            if isinstance(item.get("sell_price"), (int, float)):
                                price = item.get("sell_price") / 100.0
                            elif item.get("sell_price_text"):
                                price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
                                try:
                                    price = float(price_text)
                                except ValueError:
                                    pass
                            elif isinstance(item.get("price"), (int, float)):
                                price = item.get("price") / 100.0
                            
                            if price is not None and price > 0:
                                prices.append(price)
                        
                        if not prices:
                            logger.warning(f"    ⚠️ BasePriceAPI: Не удалось извлечь цены из результатов для '{item_name}'")
                            continue
                        
                        # Вычисляем среднюю цену
                        if len(prices) == 1:
                            average_price = prices[0]
                            logger.info(f"    📊 BasePriceAPI: Получен 1 лот для '{item_name}': ${average_price:.2f}")
                        else:
                            # Используем медиану для более устойчивого результата (исключает выбросы)
                            sorted_prices = sorted(prices)
                            n = len(sorted_prices)
                            if n % 2 == 0:
                                median_price = (sorted_prices[n//2 - 1] + sorted_prices[n//2]) / 2.0
                            else:
                                median_price = sorted_prices[n//2]
                            
                            average_price = sum(prices) / len(prices)
                            
                            # Используем медиану, если она сильно отличается от среднего (есть выбросы)
                            if abs(median_price - average_price) / average_price > 0.2:  # Разница > 20%
                                logger.info(f"    📊 BasePriceAPI: Обнаружены выбросы, используем медиану вместо среднего")
                                logger.info(f"    📊 BasePriceAPI: Среднее: ${average_price:.2f}, Медиана: ${median_price:.2f}, Лотов: {len(prices)}")
                                average_price = median_price
                            else:
                                logger.info(f"    📊 BasePriceAPI: Получено {len(prices)} лотов для '{item_name}': цены от ${min(prices):.2f} до ${max(prices):.2f}, средняя: ${average_price:.2f}")
                            
                            # Логируем все цены для отладки
                            logger.debug(f"    📊 BasePriceAPI: Все цены: {[f'${p:.2f}' for p in sorted_prices]}")
                        
                        # Валидация: проверяем, что цена разумная
                        suspicious_price_threshold = 1.0  # $1.00
                        
                        # Проверяем название предмета на признаки дорогого предмета
                        first_item = results[0]
                        item_hash_name = first_item.get("asset_description", {}).get("market_hash_name", "") or first_item.get("name", "")
                        is_expensive_item = any(keyword in item_name.lower() for keyword in [
                            "redline", "asiimov", "dragon lore", "howl", "fire serpent"
                        ])
                        
                        if is_expensive_item and average_price < suspicious_price_threshold:
                            logger.warning(f"    ⚠️ BasePriceAPI: ПОДОЗРИТЕЛЬНО НИЗКАЯ базовая цена для '{item_name}': ${average_price:.2f}")
                            logger.warning(f"    ⚠️ BasePriceAPI: Возможно, это предметы с наклейками или ошибка API")
                            logger.warning(f"    ⚠️ BasePriceAPI: Проверено лотов: {len(prices)}, цены: {[f'${p:.2f}' for p in sorted(prices)]}")
                            logger.warning(f"    ⚠️ BasePriceAPI: Рекомендуется проверить вручную")
                        
                        logger.info(f"    ✅ BasePriceAPI: Базовая цена получена для '{item_name}': ${average_price:.2f} (из {len(prices)} лотов)")
                        return average_price

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning(f"    ⚠️ BasePriceAPI: 429 ошибка при получении базовой цены для '{item_name}' (попытка {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1 and proxy_manager:
                        # Пробуем другой прокси
                        import asyncio
                        await asyncio.sleep(1.0 * (attempt + 1))  # Задержка перед следующей попыткой
                        continue
                    else:
                        logger.error(f"    ❌ BasePriceAPI: Превышено количество попыток для получения базовой цены '{item_name}'")
                        return None
                else:
                    logger.warning(f"    ⚠️ BasePriceAPI: HTTP ошибка {e.response.status_code} при получении базовой цены для '{item_name}'")
                    return None
            except Exception as e:
                logger.warning(f"    ⚠️ BasePriceAPI: Ошибка при получении базовой цены для '{item_name}': {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return None

        return None

