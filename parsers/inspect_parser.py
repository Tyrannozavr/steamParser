"""
Парсер для автоматического получения float и паттерна через inspect ссылки.
Использует сторонние API для извлечения данных.
"""
import re
from typing import Optional, Dict, Any
import httpx
from loguru import logger


class InspectLinkParser:
    """Парсер inspect ссылок для получения float и паттерна."""

    @staticmethod
    def parse_inspect_link(inspect_link: str) -> Optional[Dict[str, str]]:
        """
        Парсит inspect ссылку и извлекает параметры.

        Args:
            inspect_link: Inspect in Game ссылка

        Returns:
            Словарь с параметрами или None
        """
        # Формат: steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M{listingid}A{assetid}D{param}
        pattern = r'csgo_econ_action_preview.*?M(\d+)A(\d+)D(\d+)'
        match = re.search(pattern, inspect_link)
        
        if match:
            listingid, assetid, d_param = match.groups()
            return {
                'listingid': listingid,
                'assetid': assetid,
                'd_param': d_param
            }
        return None

    @staticmethod
    async def get_float_from_csgofloat_api(
        inspect_link: str,
        proxy: Optional[str] = None,
        timeout: int = 10,
        proxy_manager=None
    ) -> Optional[Dict[str, Any]]:
        """
        Получает float и паттерн через CSGOFloat API.

        Args:
            inspect_link: Inspect in Game ссылка
            proxy: Опциональный прокси
            timeout: Таймаут запроса

        Returns:
            Словарь с данными или None
        """
        params = InspectLinkParser.parse_inspect_link(inspect_link)
        if not params:
            return None

        # CSGOFloat API - несколько вариантов endpoints
        endpoints = [
            # Вариант 1: Через listing ID
            f"https://csgofloat.com/api/v1/listings/{params['listingid']}",
            # Вариант 2: Через inspect ссылку (URL encoded)
            f"https://csgofloat.com/api/v1/inspect?inspect={inspect_link.replace('steam://', '')}",
            # Вариант 3: Через asset ID
            f"https://csgofloat.com/api/v1/item/{params['assetid']}",
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Получаем прокси через proxy_manager, если он доступен
        current_proxy = proxy
        if proxy_manager and not current_proxy:
            proxy_obj = await proxy_manager.get_next_proxy(force_refresh=False)
            if proxy_obj:
                current_proxy = proxy_obj.url
                logger.debug(f"🌐 InspectLinkParser: Используем прокси ID={proxy_obj.id} из proxy_manager")
        
        async with httpx.AsyncClient(proxy=current_proxy, timeout=timeout, headers=headers) as client:
            for url in endpoints:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        # Разные форматы ответа от API
                        iteminfo = None
                        if 'iteminfo' in data:
                            iteminfo = data['iteminfo']
                        elif 'item' in data:
                            iteminfo = data['item']
                        elif isinstance(data, dict) and 'floatvalue' in data:
                            iteminfo = data
                        
                        if iteminfo:
                            # Ищем float в разных форматах
                            float_val = (
                                iteminfo.get('floatvalue') or 
                                iteminfo.get('float') or 
                                iteminfo.get('floatValue')
                            )
                            # Ищем pattern (paintSeed) в разных форматах
                            pattern_val = (
                                iteminfo.get('paintseed') or 
                                iteminfo.get('paintSeed') or  # Формат от расширения CS2 Float Checker
                                iteminfo.get('pattern') or
                                iteminfo.get('patternIndex')
                            )
                            
                            if float_val is not None or pattern_val is not None:
                                return {
                                    'float_value': float(float_val) if float_val is not None else None,
                                    'pattern': int(pattern_val) if pattern_val is not None else None,
                                    'source': 'csgofloat_api'
                                }
                except httpx.HTTPStatusError as e:
                    logger.debug(f"    ⚠️ InspectLinkParser (csgofloat): HTTP {e.response.status_code} для {url}")
                    if e.response.status_code == 429:
                        logger.warning(f"    ⚠️ InspectLinkParser (csgofloat): Rate limit (429)")
                    elif e.response.status_code == 403:
                        logger.warning(f"    ⚠️ InspectLinkParser (csgofloat): Forbidden (403)")
                    # Пробуем следующий endpoint
                    continue
                except httpx.TimeoutException as e:
                    logger.debug(f"    ⚠️ InspectLinkParser (csgofloat): Timeout для {url}: {e}")
                    continue
                except httpx.ConnectError as e:
                    logger.debug(f"    ⚠️ InspectLinkParser (csgofloat): Connection error для {url}: {e}")
                    continue
                except Exception as e:
                    logger.debug(f"    ⚠️ InspectLinkParser (csgofloat): Ошибка для {url}: {type(e).__name__}: {e}")
                    # Пробуем следующий endpoint
                    continue

        return None

    @staticmethod
    async def get_float_from_steam_web_api(
        assetid: str,
        appid: int = 730,
        contextid: str = "2",
        proxy: Optional[str] = None,
        timeout: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Получает данные через Steam Web API (требует API ключ).

        Args:
            assetid: ID предмета
            appid: ID приложения
            contextid: ID контекста
            proxy: Опциональный прокси
            timeout: Таймаут запроса

        Returns:
            Словарь с данными или None
        """
        # Steam Web API требует API ключ и доступ к инвентарю
        # Это более сложный способ, требует авторизации
        # Пока оставляем заглушку
        return None

    @staticmethod
    async def get_float_from_steam_web_api_direct(
        inspect_link: str,
        proxy: Optional[str] = None,
        timeout: int = 10
    ) -> Optional[Dict[str, Any]]:
        """
        Пытается получить данные напрямую через Steam Web API (без API ключа).
        Использует публичные endpoints.

        Args:
            inspect_link: Inspect in Game ссылка
            proxy: Опциональный прокси
            timeout: Таймаут запроса

        Returns:
            Словарь с данными или None
        """
        # Steam не предоставляет публичный API для этого
        # Но можно попробовать через Game Coordinator (сложно)
        return None

    @staticmethod
    async def get_float_from_cs2floatchecker_inspect(
        inspect_link: str,
        proxy: Optional[str] = None,
        timeout: int = 30,
        proxy_manager=None
    ) -> Optional[Dict[str, Any]]:
        """
        Получает float и pattern через API cs2floatchecker.com.
        Использует тот же API, что и расширение Chrome.

        Args:
            inspect_link: Inspect in Game ссылка
            proxy: Опциональный прокси
            timeout: Таймаут запроса (по умолчанию 30 секунд)

        Returns:
            Словарь с данными или None
        """
        try:
            from urllib.parse import quote
            
            # API endpoint, который использует расширение
            api_url = "https://api.cs2floatchecker.com"
            url = f"{api_url}/?url={quote(inspect_link)}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json"
            }
            
            # Получаем прокси через proxy_manager, если он доступен
            current_proxy = proxy
            if proxy_manager and not current_proxy:
                proxy_obj = await proxy_manager.get_next_proxy(force_refresh=False)
                if proxy_obj:
                    current_proxy = proxy_obj.url
                    logger.debug(f"🌐 InspectLinkParser (cs2floatchecker): Используем прокси ID={proxy_obj.id} из proxy_manager")
            
            async with httpx.AsyncClient(proxy=current_proxy, timeout=timeout, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                
                # API возвращает данные в поле iteminfo
                iteminfo = data.get('iteminfo')
                if not iteminfo:
                    return None
                
                # Извлекаем float и pattern (paintseed)
                float_val = iteminfo.get('floatvalue') or iteminfo.get('float')
                pattern_val = iteminfo.get('paintseed') or iteminfo.get('paintSeed')
                
                if float_val is not None or pattern_val is not None:
                    return {
                        'float_value': float(float_val) if float_val is not None else None,
                        'pattern': int(pattern_val) if pattern_val is not None else None,
                        'paintIndex': iteminfo.get('paintindex'),
                        'defIndex': iteminfo.get('defindex'),
                        'wearName': iteminfo.get('wear_name'),
                        'source': 'cs2floatchecker_api'
                    }
                
        except httpx.HTTPStatusError as e:
            logger.debug(f"    ⚠️ InspectLinkParser (cs2floatchecker): HTTP {e.response.status_code}: {e.response.url}")
            if e.response.status_code == 429:
                logger.warning(f"    ⚠️ InspectLinkParser (cs2floatchecker): Rate limit (429)")
            elif e.response.status_code == 403:
                logger.warning(f"    ⚠️ InspectLinkParser (cs2floatchecker): Forbidden (403)")
        except httpx.TimeoutException as e:
            logger.debug(f"    ⚠️ InspectLinkParser (cs2floatchecker): Timeout: {e}")
        except httpx.ConnectError as e:
            logger.debug(f"    ⚠️ InspectLinkParser (cs2floatchecker): Connection error: {e}")
        except Exception as e:
            logger.debug(f"    ⚠️ InspectLinkParser (cs2floatchecker): Ошибка: {type(e).__name__}: {e}")
        
        return None

    @staticmethod
    async def get_float_from_multiple_sources(
        inspect_link: str,
        assetid: Optional[str] = None,
        proxy: Optional[str] = None,
        proxy_manager=None
    ) -> Optional[Dict[str, Any]]:
        """
        Пытается получить float и паттерн из нескольких источников.

        Args:
            inspect_link: Inspect in Game ссылка
            assetid: Опциональный asset ID
            proxy: Опциональный прокси

        Returns:
            Словарь с данными или None
        """
        logger.info(f"    🔍 InspectLinkParser: Пытаемся получить float/pattern из inspect ссылки")
        logger.debug(f"    📎 Inspect ссылка: {inspect_link[:100]}...")
        
        # Сначала пробуем cs2floatchecker API (тот же, что использует расширение)
        logger.info(f"    🌐 InspectLinkParser: Пробуем cs2floatchecker.com API...")
        result = await InspectLinkParser.get_float_from_cs2floatchecker_inspect(
            inspect_link, proxy=proxy, proxy_manager=proxy_manager
        )
        
        if result and (result.get('float_value') is not None or result.get('pattern') is not None):
            logger.info(f"    ✅ InspectLinkParser: Данные получены через cs2floatchecker.com: float={result.get('float_value')}, pattern={result.get('pattern')}")
            return result
        else:
            logger.debug(f"    ⚠️ InspectLinkParser: cs2floatchecker.com не вернул данные")
        
        # Пробуем CSGOFloat API как fallback
        logger.info(f"    🌐 InspectLinkParser: Пробуем csgofloat.com API...")
        result = await InspectLinkParser.get_float_from_csgofloat_api(
            inspect_link, proxy=proxy, proxy_manager=proxy_manager
        )
        
        if result and (result.get('float_value') is not None or result.get('pattern') is not None):
            logger.info(f"    ✅ InspectLinkParser: Данные получены через csgofloat.com: float={result.get('float_value')}, pattern={result.get('pattern')}")
            return result
        else:
            logger.debug(f"    ⚠️ InspectLinkParser: csgofloat.com не вернул данные")

        # Пробуем другие источники:
        # - CS.Money API (требует API ключ)
        # - Skinport API (требует API ключ)
        # - Прямой парсинг inspect ссылки (сложно, требует запуск игры)
        
        logger.warning(f"    ❌ InspectLinkParser: Не удалось получить данные ни из одного источника")
        return None


async def test_inspect_parsing():
    """Тестовая функция для проверки парсинга inspect ссылок."""
    inspect_link = "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20M720139732925859819A47696126279D16747423212568741781"
    
    print("Парсинг inspect ссылки:")
    params = InspectLinkParser.parse_inspect_link(inspect_link)
    print(params)
    
    print("\nПопытка получить float через API:")
    result = await InspectLinkParser.get_float_from_multiple_sources(inspect_link)
    print(result)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_inspect_parsing())

