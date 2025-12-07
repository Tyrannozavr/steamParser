"""
Сервис для получения курсов валют с trueskins.org/currencies.
Кэширует результаты в Redis на 1 час.
"""
import json
import asyncio
from typing import Optional, Dict
from datetime import datetime, timedelta
from loguru import logger
import httpx
from bs4 import BeautifulSoup

from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from services.proxy_429_handler import Proxy429Handler


class CurrencyService:
    """Сервис для получения и кэширования курсов валют."""
    
    CACHE_KEY = "currency_rates:trueskins"
    CACHE_TTL = 3600  # 1 час в секундах
    CURRENCIES_URL = "https://trueskins.org/currencies"
    FALLBACK_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"  # Fallback API
    
    # Коды валют, которые нужно получать
    TARGET_CURRENCIES = {
        "THB": "Тайский бат",
        "CNY": "Китайский юань",
        "RUB": "Российский рубль"
    }
    
    def __init__(self, redis_service: Optional[RedisService] = None, proxy_manager: Optional[ProxyManager] = None):
        """
        Инициализация сервиса курсов валют.
        
        Args:
            redis_service: Сервис Redis для кэширования
            proxy_manager: Менеджер прокси для запросов
        """
        self.redis_service = redis_service
        self.proxy_manager = proxy_manager
        self._rates_cache: Optional[Dict[str, float]] = None
    
    async def get_currency_rates(self) -> Dict[str, float]:
        """
        Получает курсы валют (THB, CNY, RUB к USD).
        
        Returns:
            Словарь с курсами валют: {"THB": 35.5, "CNY": 7.2, "RUB": 90.0}
        """
        # Проверяем кэш в Redis
        if self.redis_service and self.redis_service.is_connected():
            try:
                cached_rates = await self.redis_service.get_json(self.CACHE_KEY)
                if cached_rates:
                    logger.debug(f"✅ CurrencyService: Использован кэш из Redis (THB={cached_rates.get('THB')}, CNY={cached_rates.get('CNY')}, RUB={cached_rates.get('RUB')})")
                    return cached_rates
            except Exception as e:
                logger.warning(f"⚠️ CurrencyService: Ошибка при чтении кэша из Redis: {e}")
        
        # Если кэша нет или Redis недоступен, запрашиваем через прокси
        logger.info("🔄 CurrencyService: Запрашиваем курсы валют с trueskins.org через прокси...")
        
        rates = await self._fetch_currency_rates()
        
        # Если не удалось получить с trueskins.org, используем fallback API
        if not rates or len(rates) < len(self.TARGET_CURRENCIES):
            logger.warning("⚠️ CurrencyService: Не удалось получить все курсы с trueskins.org, используем fallback API...")
            rates = await self._fetch_currency_rates_fallback()
        
        # Сохраняем в кэш Redis только если получили все курсы
        if rates and len(rates) >= len(self.TARGET_CURRENCIES) and self.redis_service and self.redis_service.is_connected():
            try:
                await self.redis_service.set_json(
                    self.CACHE_KEY,
                    rates,
                    ex=self.CACHE_TTL
                )
                logger.info(f"✅ CurrencyService: Курсы валют сохранены в Redis кэш на {self.CACHE_TTL} секунд")
            except Exception as e:
                logger.warning(f"⚠️ CurrencyService: Ошибка при сохранении в Redis кэш: {e}")
        
        return rates or {}
    
    async def _fetch_currency_rates(self) -> Optional[Dict[str, float]]:
        """
        Запрашивает курсы валют с trueskins.org/currencies через прокси.
        
        Returns:
            Словарь с курсами валют или None при ошибке
        """
        if not self.proxy_manager:
            logger.error("❌ CurrencyService: ProxyManager не доступен")
            return None
        
        # Используем Proxy429Handler для автоматической обработки ошибок
        from services.proxy_429_handler import Proxy429Handler
        handler = Proxy429Handler(self.proxy_manager)
        
        async def fetch_with_proxy(proxy):
            """Выполняет запрос через прокси."""
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8,application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
            
            # httpx использует proxy параметр, а не proxies
            async with httpx.AsyncClient(proxy=proxy.url, timeout=30.0, headers=headers, follow_redirects=True) as client:
                logger.debug(f"🌐 CurrencyService: Запрос к {self.CURRENCIES_URL} через прокси {proxy.url[:50]}...")
                response = await client.get(self.CURRENCIES_URL)
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').lower()
                
                logger.debug(f"📥 CurrencyService: Получен ответ {response.status_code}, content-type: {content_type}")
                
                # Если это JSON, возвращаем как JSON
                if 'application/json' in content_type:
                    return response.json()
                else:
                    return response.text
        
        try:
            content = await handler.execute_with_retry(fetch_with_proxy)
            
            # Парсим данные (может быть JSON или HTML)
            if isinstance(content, dict):
                # Это JSON ответ
                rates = self._parse_currency_rates_json(content)
            else:
                # Это HTML
                rates = self._parse_currency_rates(content)
            
            if rates:
                logger.info(f"✅ CurrencyService: Получены курсы валют: THB={rates.get('THB')}, CNY={rates.get('CNY')}, RUB={rates.get('RUB')}")
            else:
                logger.warning("⚠️ CurrencyService: Не удалось извлечь курсы валют")
            
            return rates
            
        except Exception as e:
            logger.error(f"❌ CurrencyService: Ошибка при запросе курсов валют: {e}")
            import traceback
            logger.debug(f"   Traceback: {traceback.format_exc()}")
            return None
    
    def _parse_currency_rates_json(self, json_data: Dict) -> Optional[Dict[str, float]]:
        """
        Парсит JSON данные с курсами валют.
        
        Args:
            json_data: JSON данные
            
        Returns:
            Словарь с курсами валют или None
        """
        try:
            rates = {}
            
            # Пробуем разные варианты структуры JSON
            # Вариант 1: Прямой словарь с кодами валют
            for currency_code in self.TARGET_CURRENCIES.keys():
                if currency_code in json_data:
                    try:
                        rate = float(json_data[currency_code])
                        if 0.1 < rate < 10000:
                            rates[currency_code] = rate
                    except (ValueError, TypeError):
                        pass
            
            # Вариант 2: Вложенная структура {"currencies": {"THB": 35.5, ...}}
            if not rates and isinstance(json_data, dict):
                for key in ['currencies', 'rates', 'data', 'result']:
                    if key in json_data and isinstance(json_data[key], dict):
                        for currency_code in self.TARGET_CURRENCIES.keys():
                            if currency_code in json_data[key]:
                                try:
                                    rate = float(json_data[key][currency_code])
                                    if 0.1 < rate < 10000:
                                        rates[currency_code] = rate
                                except (ValueError, TypeError):
                                    pass
            
            # Вариант 3: Массив объектов [{"code": "THB", "rate": 35.5}, ...]
            if not rates and isinstance(json_data, dict):
                for key in ['currencies', 'rates', 'data', 'result']:
                    if key in json_data and isinstance(json_data[key], list):
                        for item in json_data[key]:
                            if isinstance(item, dict):
                                code = item.get('code') or item.get('currency') or item.get('symbol')
                                rate = item.get('rate') or item.get('value') or item.get('price')
                                if code and code in self.TARGET_CURRENCIES and rate:
                                    try:
                                        rate_float = float(rate)
                                        if 0.1 < rate_float < 10000:
                                            rates[code] = rate_float
                                    except (ValueError, TypeError):
                                        pass
            
            return rates if rates else None
            
        except Exception as e:
            logger.error(f"❌ CurrencyService: Ошибка при парсинге JSON: {e}")
            return None
    
    def _parse_currency_rates(self, html_content: str) -> Optional[Dict[str, float]]:
        """
        Парсит HTML страницы trueskins.org/currencies для извлечения курсов валют.
        
        Args:
            html_content: HTML содержимое страницы
            
        Returns:
            Словарь с курсами валют или None
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            rates = {}
            
            # Ищем таблицу или элементы с курсами валют
            # Нужно адаптировать под реальную структуру страницы
            
            # Вариант 1: Ищем по тексту валют
            for currency_code, currency_name in self.TARGET_CURRENCIES.items():
                # Ищем элементы, содержащие код валюты или название
                # Пробуем разные варианты поиска
                found = False
                
                # Поиск по коду валюты
                elements = soup.find_all(text=lambda text: text and currency_code in text)
                if not elements:
                    # Поиск по названию
                    elements = soup.find_all(text=lambda text: text and currency_name.lower() in text.lower())
                
                if elements:
                    # Пытаемся найти ближайшее числовое значение (курс)
                    for elem in elements[:5]:  # Проверяем первые 5 совпадений
                        parent = elem.parent if hasattr(elem, 'parent') else None
                        if parent:
                            # Ищем числа в родительском элементе и соседних
                            text = parent.get_text() if hasattr(parent, 'get_text') else str(parent)
                            
                            # Ищем паттерн: число после кода валюты или в том же элементе
                            import re
                            # Паттерн: валюта + число (например: "THB 35.5" или "35.5 THB")
                            patterns = [
                                rf"{currency_code}\s*[:\-]?\s*(\d+\.?\d*)",
                                rf"(\d+\.?\d*)\s*{currency_code}",
                                rf"{currency_name}.*?(\d+\.?\d*)",
                                rf"(\d+\.?\d*).*?{currency_name}"
                            ]
                            
                            for pattern in patterns:
                                match = re.search(pattern, text, re.IGNORECASE)
                                if match:
                                    try:
                                        rate = float(match.group(1))
                                        if 0.1 < rate < 10000:  # Разумный диапазон для курса
                                            rates[currency_code] = rate
                                            found = True
                                            logger.debug(f"   ✅ Найден курс {currency_code}: {rate} (из текста: {text[:100]})")
                                            break
                                    except (ValueError, IndexError):
                                        continue
                            
                            if found:
                                break
                
                if not found:
                    logger.warning(f"⚠️ CurrencyService: Не найден курс для {currency_code} ({currency_name})")
            
            # Если не нашли через поиск по тексту, пробуем найти таблицу
            if len(rates) < len(self.TARGET_CURRENCIES):
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            cell_text = ' '.join([cell.get_text(strip=True) for cell in cells])
                            
                            for currency_code, currency_name in self.TARGET_CURRENCIES.items():
                                if currency_code not in rates:
                                    if currency_code in cell_text or currency_name.lower() in cell_text.lower():
                                        # Ищем число в этой строке
                                        import re
                                        numbers = re.findall(r'\d+\.?\d*', cell_text)
                                        for num_str in numbers:
                                            try:
                                                rate = float(num_str)
                                                if 0.1 < rate < 10000:
                                                    rates[currency_code] = rate
                                                    logger.debug(f"   ✅ Найден курс {currency_code}: {rate} (из таблицы)")
                                                    break
                                            except ValueError:
                                                continue
            
            # Если все еще не нашли, пробуем найти JSON данные в скриптах
            if len(rates) < len(self.TARGET_CURRENCIES):
                scripts = soup.find_all('script')
                for script in scripts:
                    script_text = script.string if script.string else ''
                    if 'currency' in script_text.lower() or 'rate' in script_text.lower():
                        # Пытаемся найти JSON данные
                        import re
                        json_match = re.search(r'\{[^{}]*"currency"[^{}]*\}', script_text)
                        if json_match:
                            try:
                                data = json.loads(json_match.group(0))
                                # Обрабатываем JSON данные
                                for currency_code in self.TARGET_CURRENCIES.keys():
                                    if currency_code not in rates:
                                        if currency_code in data:
                                            rates[currency_code] = float(data[currency_code])
                            except:
                                pass
            
            return rates if rates else None
            
        except Exception as e:
            logger.error(f"❌ CurrencyService: Ошибка при парсинге HTML: {e}")
            import traceback
            logger.debug(f"   Traceback: {traceback.format_exc()}")
            return None
    
    async def _fetch_currency_rates_fallback(self) -> Optional[Dict[str, float]]:
        """
        Запрашивает курсы валют с fallback API (exchangerate-api.com).
        Этот метод не требует прокси, так как это публичный API.
        
        Returns:
            Словарь с курсами валют или None при ошибке
        """
        try:
            logger.info(f"🔄 CurrencyService: Запрос к fallback API {self.FALLBACK_API_URL}...")
            
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(self.FALLBACK_API_URL)
                response.raise_for_status()
                
                data = response.json()
                rates_data = data.get('rates', {})
                
                # Извлекаем нужные валюты
                rates = {}
                for currency_code in self.TARGET_CURRENCIES.keys():
                    if currency_code in rates_data:
                        rate = float(rates_data[currency_code])
                        if 0.1 < rate < 10000:  # Разумный диапазон
                            rates[currency_code] = rate
                
                if rates and len(rates) == len(self.TARGET_CURRENCIES):
                    logger.info(f"✅ CurrencyService: Получены курсы валют из fallback API: THB={rates.get('THB')}, CNY={rates.get('CNY')}, RUB={rates.get('RUB')}")
                    return rates
                else:
                    logger.warning(f"⚠️ CurrencyService: Fallback API вернул неполные данные: {rates}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ CurrencyService: Ошибка при запросе fallback API: {e}")
            import traceback
            logger.debug(f"   Traceback: {traceback.format_exc()}")
            return None
    
    def convert_price(self, usd_price: float, rates: Dict[str, float]) -> Dict[str, float]:
        """
        Конвертирует цену из USD в другие валюты.
        
        Args:
            usd_price: Цена в USD
            rates: Словарь с курсами валют
            
        Returns:
            Словарь с ценами в разных валютах
        """
        converted = {}
        for currency_code in self.TARGET_CURRENCIES.keys():
            if currency_code in rates:
                converted[currency_code] = usd_price * rates[currency_code]
            else:
                converted[currency_code] = None
        
        return converted

