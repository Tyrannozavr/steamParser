"""
Модуль для получения цен предметов через API cs2floatchecker.com.
"""
import httpx
from typing import Optional, Dict, Any
from urllib.parse import quote


class ItemPricesAPI:
    """API для получения цен предметов с разных площадок."""

    BASE_URL = "https://api.cs2floatchecker.com/api/price"

    @staticmethod
    async def get_item_price(
        item_name: str,
        proxy: Optional[str] = None,
        timeout: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Получает цены предмета с разных площадок через API.

        Args:
            item_name: Название предмета (например, "AK-47 | Nightwish (Field-Tested)")
            proxy: Опциональный прокси
            timeout: Таймаут запроса

        Returns:
            Словарь с ценами или None
        """
        try:
            # URL-кодируем название предмета
            encoded_name = quote(item_name)
            url = f"{ItemPricesAPI.BASE_URL}/{encoded_name}"

            async with httpx.AsyncClient(proxy=proxy, timeout=timeout) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                )
                response.raise_for_status()
                data = response.json()

                if data.get("success"):
                    return data

        except Exception as e:
            # Тихая обработка ошибок
            pass

        return None

    @staticmethod
    def get_lowest_price(prices_data: Dict[str, Any]) -> Optional[float]:
        """
        Получает самую низкую цену из всех площадок.

        Args:
            prices_data: Данные из get_item_price()

        Returns:
            Самая низкая цена в USD или None
        """
        if not prices_data or not prices_data.get("success"):
            return None

        prices = prices_data.get("prices", {})
        min_price = None

        for platform, data in prices.items():
            if data and isinstance(data, dict):
                price_usd = data.get("price_usd")
                if price_usd is not None:
                    if min_price is None or price_usd < min_price:
                        min_price = price_usd

        return min_price

    @staticmethod
    def get_steam_price(prices_data: Dict[str, Any]) -> Optional[float]:
        """
        Получает цену со Steam Market.

        Args:
            prices_data: Данные из get_item_price()

        Returns:
            Цена в USD или None
        """
        if not prices_data or not prices_data.get("success"):
            return None

        steam_data = prices_data.get("prices", {}).get("steam")
        if steam_data and isinstance(steam_data, dict):
            return steam_data.get("price_usd")

        return None

