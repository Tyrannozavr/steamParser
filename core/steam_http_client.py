"""
HTTP клиент и управление запросами для Steam Market парсера.
"""
import asyncio
import random
from typing import Optional, Dict
from loguru import logger
import httpx

from .steam_parser_constants import USER_AGENTS


class SteamHttpClient:
    """Класс для управления HTTP запросами к Steam Market."""
    
    def __init__(self, proxy: Optional[str] = None, timeout: int = 30, proxy_manager=None):
        """
        Инициализация HTTP клиента.
        
        Args:
            proxy: Прокси-сервер в формате "http://user:pass@host:port" или None
            timeout: Таймаут запроса в секундах
            proxy_manager: Менеджер прокси для ротации (опционально)
        """
        self.proxy = proxy
        self.timeout = timeout
        self.proxy_manager = proxy_manager
        self._client: Optional[httpx.AsyncClient] = None
        self._current_user_agent: Optional[str] = None
    
    def _get_random_user_agent(self) -> str:
        """Возвращает случайный User-Agent из списка."""
        return random.choice(USER_AGENTS)
    
    def _get_browser_headers(self) -> Dict[str, str]:
        """
        Генерирует реалистичные заголовки для имитации браузера Chrome.
        Каждый раз выбирается случайный User-Agent и языковые настройки.
        """
        self._current_user_agent = self._get_random_user_agent()
        
        # Определяем платформу из User-Agent для правильных Sec-CH-UA заголовков
        if "Windows" in self._current_user_agent:
            accept_language = random.choice([
                "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "en-US,en;q=0.9,ru;q=0.8"
            ])
            sec_ch_ua_platform = '"Windows"'
        elif "Macintosh" in self._current_user_agent:
            accept_language = random.choice([
                "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "en-US,en;q=0.9,ru;q=0.8"
            ])
            sec_ch_ua_platform = '"macOS"'
        else:
            accept_language = "en-US,en;q=0.9,ru;q=0.8"
            sec_ch_ua_platform = '"Linux"'
        
        # Определяем версию браузера из User-Agent
        chrome_version = "131"  # По умолчанию
        if "Chrome/" in self._current_user_agent:
            try:
                chrome_version = self._current_user_agent.split("Chrome/")[1].split(".")[0]
            except:
                pass
        
        # Формируем реалистичные заголовки как у Chrome
        headers = {
            "User-Agent": self._current_user_agent,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": accept_language,
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://steamcommunity.com",
            "Referer": "https://steamcommunity.com/market/search?appid=730",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-CH-UA": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not_A Brand";v="24"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": sec_ch_ua_platform,
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
        }
        
        return headers
    
    async def _random_delay(self, min_seconds: float = 1.0, max_seconds: float = 3.0):
        """
        Случайная задержка между запросами для имитации человеческого поведения.
        
        Args:
            min_seconds: Минимальная задержка в секундах
            max_seconds: Максимальная задержка в секундах
            
        Returns:
            Фактическая задержка в секундах (для логирования)
        """
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)
        return delay
    
    def _get_retry_after_delay(self, response: httpx.Response, base_delay: float, attempt: int) -> float:
        """
        Определяет задержку для повторной попытки при 429 ошибке.
        Приоритет: Retry-After заголовок > экспоненциальная задержка.
        
        Args:
            response: HTTP ответ с 429 ошибкой
            base_delay: Базовая задержка для экспоненциальной задержки
            attempt: Номер попытки (для экспоненциальной задержки)
            
        Returns:
            Задержка в секундах
        """
        # Проверяем заголовок Retry-After
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                # Retry-After может быть в секундах (число) или в формате HTTP-date
                retry_seconds = int(retry_after)
                logger.info(f"📋 Получен заголовок Retry-After: {retry_seconds} сек")
                # Добавляем небольшой буфер (10%) для безопасности
                return retry_seconds * 1.1
            except ValueError:
                # Если не число, пытаемся парсить как HTTP-date (пока не реализовано)
                logger.warning(f"⚠️ Retry-After в неожиданном формате: {retry_after}, используем экспоненциальную задержку")
        
        # Если Retry-After нет, используем экспоненциальную задержку
        exponential_delay = base_delay * (2 ** attempt)
        return exponential_delay
    
    async def _switch_proxy(self) -> bool:
        """
        Переключается на другой прокси через proxy_manager.
        Исключает текущий прокси из списка доступных.
        
        Returns:
            True если прокси был переключен, False если не удалось
        """
        if not self.proxy_manager:
            return False
        
        try:
            # Получаем список всех активных прокси
            all_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
            if not all_proxies:
                logger.warning(f"⚠️ Нет доступных прокси для переключения")
                return False
            
            # Находим текущий прокси по URL
            current_proxy_id = None
            if self.proxy:
                for p in all_proxies:
                    if p.url == self.proxy:
                        current_proxy_id = p.id
                        break
            
            # Исключаем текущий прокси из списка
            available_proxies = [p for p in all_proxies if p.id != current_proxy_id]
            
            if not available_proxies:
                logger.warning(f"⚠️ Нет других прокси для переключения (всего прокси: {len(all_proxies)}, текущий: {current_proxy_id})")
                return False
            
            # Выбираем случайный из доступных
            next_proxy = random.choice(available_proxies)
            
            old_proxy = self.proxy
            self.proxy = next_proxy.url
            logger.debug(f"🔄 Переключение прокси: {old_proxy[:50] if old_proxy else 'None'}... → {self.proxy[:50]}... (ID={next_proxy.id})")
            logger.debug(f"   Доступно прокси для переключения: {len(available_proxies)} (исключен ID={current_proxy_id})")
            
            # Пересоздаем HTTP клиент с новым прокси
            if self._client:
                await self._client.aclose()
                self._client = None
            
            await self._ensure_client()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при переключении прокси: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return False
    
    
    async def _ensure_client(self):
        """Создает HTTP клиент, если он еще не создан.
        
        Использует постоянные куки для имитации сессии браузера.
        Применяет реалистичные заголовки для обхода блокировок.
        """
        if self._client is None:
            # Получаем реалистичные заголовки (как в тестовом скрипте)
            headers = self._get_browser_headers()
            if self.proxy:
                logger.debug(f"🌐 SteamHttpClient: Создаем HTTP клиент с прокси: {self.proxy[:50]}...")
            else:
                logger.warning("⚠️ SteamHttpClient: Создаем HTTP клиент БЕЗ прокси (прямое подключение)")
            logger.debug(f"📋 User-Agent: {headers.get('User-Agent', 'Unknown')[:80]}...")
            # Создаем клиент с cookies для имитации сессии браузера
            # ВАЖНО: Используем явный httpx.Timeout с отдельными таймаутами для надежности
            # Это предотвращает зависание, если прокси завис после подключения
            import httpx as httpx_lib
            timeout_config = httpx_lib.Timeout(
                timeout=self.timeout,  # Общий таймаут (fallback)
                connect=min(10.0, self.timeout * 0.5),  # Подключение: быстрее (50% от общего, но не больше 10 сек)
                read=min(self.timeout * 0.75, 15.0),  # Чтение: 75% от общего, но не больше 15 сек
                write=5.0,  # Отправка: фиксированные 5 секунд (должно быть быстро)
                pool=5.0  # Получение соединения из пула: 5 секунд
            )
            self._client = httpx.AsyncClient(
                proxy=self.proxy,  # В новых версиях httpx используется proxy вместо proxies
                timeout=timeout_config,  # Используем явный Timeout объект
                headers=headers,
                follow_redirects=True,
                cookies={},  # Инициализируем пустые куки, они будут автоматически сохраняться
            )
            logger.debug("🍪 HTTP клиент создан с поддержкой cookies и реалистичными заголовками для обхода блокировок")
    
    async def close(self):
        """Закрывает HTTP клиент."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    @property
    def client(self) -> Optional[httpx.AsyncClient]:
        """Возвращает HTTP клиент."""
        return self._client
    
    async def fetch_item_page(self, appid: int, hash_name: str) -> Optional[str]:
        """
        Получает HTML страницы предмета.
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            
        Returns:
            HTML содержимое страницы или None при ошибке
        """
        await self._ensure_client()
        url = f"https://steamcommunity.com/market/listings/{appid}/{hash_name}"
        
        try:
            logger.debug(f"📄 Запрос страницы предмета: {url}")
            response = await self._client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"⚠️ 429 ошибка при запросе страницы предмета: {url}")
            else:
                logger.error(f"❌ HTTP ошибка {e.response.status_code} при запросе страницы предмета: {url}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе страницы предмета {url}: {e}")
            return None
    
    async def fetch_listing_page(self, appid: int, hash_name: str, listing_id: str) -> Optional[str]:
        """
        Получает HTML страницы конкретного лота.
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета
            listing_id: ID лота
            
        Returns:
            HTML содержимое страницы или None при ошибке
        """
        await self._ensure_client()
        url = f"https://steamcommunity.com/market/listings/{appid}/{hash_name}/{listing_id}"
        
        try:
            logger.debug(f"📄 Запрос страницы лота: {url}")
            response = await self._client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"⚠️ 429 ошибка при запросе страницы лота: {url}")
            else:
                logger.error(f"❌ HTTP ошибка {e.response.status_code} при запросе страницы лота: {url}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе страницы лота {url}: {e}")
            return None

