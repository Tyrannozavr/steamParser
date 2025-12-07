"""
Модуль с вспомогательными методами для SteamMarketParser.
Вынесено из steam_parser.py для улучшения структуры кода.
"""
import asyncio
import random
from typing import Dict, Optional
from loguru import logger
import httpx


class SteamHelperMethods:
    """Миксин с вспомогательными методами."""
    
    def _get_browser_headers(self) -> Dict[str, str]:
        """
        Генерирует реалистичные заголовки для имитации браузера Chrome.
        Каждый раз выбирается случайный User-Agent и языковые настройки.
        """
        from .steam_parser_constants import get_random_user_agent, get_browser_headers
        user_agent = get_random_user_agent()
        self._current_user_agent = user_agent
        return get_browser_headers(user_agent)
    
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
                retry_seconds = int(retry_after)
                logger.info(f"📋 Получен заголовок Retry-After: {retry_seconds} сек")
                return retry_seconds * 1.1
            except ValueError:
                logger.warning(f"⚠️ Retry-After в неожиданном формате: {retry_after}, используем экспоненциальную задержку")
        
        # Если Retry-After нет, используем экспоненциальную задержку
        exponential_delay = base_delay * (2 ** attempt)
        return exponential_delay
    
    async def _switch_proxy(self) -> bool:
        """
        Переключается на другой прокси через proxy_manager.
        Обновляет список активных прокси, чтобы исключить заблокированные.
        
        Returns:
            True если прокси был переключен, False если не удалось
        """
        if not self.proxy_manager:
            return False
        
        try:
            # Проверяем состояние сессии БД и делаем rollback при необходимости
            if hasattr(self.proxy_manager, 'db_session'):
                try:
                    # Пытаемся проверить состояние сессии
                    from sqlalchemy.orm import Session
                    if hasattr(self.proxy_manager.db_session, 'is_active'):
                        # Если сессия неактивна или была откачена, делаем rollback
                        try:
                            await self.proxy_manager.db_session.rollback()
                        except Exception:
                            pass  # Игнорируем ошибки rollback
                except Exception:
                    pass  # Игнорируем ошибки проверки сессии
            
            # Обновляем список активных прокси, чтобы исключить заблокированные
            all_proxies = await self.proxy_manager.get_active_proxies(force_refresh=True)
            if not all_proxies:
                logger.warning(f"⚠️ Нет доступных прокси для переключения")
                return False
            
            current_proxy_id = None
            if self.proxy:
                for p in all_proxies:
                    if p.url == self.proxy:
                        current_proxy_id = p.id
                        break
            
            # Получаем следующий прокси (исключая текущий)
            next_proxy = await self.proxy_manager.get_next_proxy(force_refresh=True)
            
            if not next_proxy:
                logger.warning(f"⚠️ Не удалось получить следующий прокси")
                return False
            
            # Если получили тот же прокси, выбираем другой из доступных
            if current_proxy_id and next_proxy.id == current_proxy_id:
                available_proxies = [p for p in all_proxies if p.id != current_proxy_id]
                if not available_proxies:
                    logger.warning(f"⚠️ Нет других прокси для переключения")
                    return False
                
                # Выбираем прокси с наименьшей задержкой
                available_proxies.sort(key=lambda p: p.delay_seconds)
                next_proxy = available_proxies[0]
                logger.debug(f"   Выбран прокси с наименьшей задержкой: ID={next_proxy.id}, delay={next_proxy.delay_seconds:.1f}с")
            
            old_proxy = self.proxy
            self.proxy = next_proxy.url
            logger.info(f"🔄 Переключение прокси: {old_proxy[:50] if old_proxy else 'None'}... → {self.proxy[:50]}... (ID={next_proxy.id})")
            
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
    
    async def _handle_429_fast(self, proxy: Optional[object], context: str = ""):
        """
        Быстрая обработка 429 ошибки: сразу помечает прокси как неактивный
        и немедленно переключается на следующий.
        НЕ делает задержек, НЕ делает повторных попыток.
        """
        if self.proxy_manager:
            if proxy:
                logger.warning(f"🚫 ProxyManager: Прокси ID={proxy.id} получил 429 для {context} - помечаем как неактивный и исключаем")
                await self.proxy_manager.mark_proxy_used(
                    proxy, 
                    success=False, 
                    error="429 Too Many Requests (быстрое исключение)", 
                    is_429_error=True
                )
            else:
                # Если proxy не передан, пытаемся получить текущий прокси
                proxy = await self._get_current_proxy()
                if proxy:
                    logger.warning(f"🚫 ProxyManager: Прокси ID={proxy.id} получил 429 для {context} - помечаем как неактивный и исключаем")
                    await self.proxy_manager.mark_proxy_used(
                        proxy, 
                        success=False, 
                        error="429 Too Many Requests (быстрое исключение)", 
                        is_429_error=True
                    )
            
            # Немедленно переключаемся на следующий прокси
            await self._switch_proxy()
        else:
            logger.warning(f"⚠️ 429 (Too Many Requests) для {context} - нет ProxyManager для быстрой обработки")
    
    async def _get_current_proxy(self) -> Optional[object]:
        """Возвращает текущий объект прокси, если он установлен."""
        if not self.proxy_manager:
            return None
        
        # Если есть proxy, ищем его в списке активных
        if self.proxy:
            active_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
            for p in active_proxies:
                if p.url == self.proxy:
                    return p
        
        # Если proxy нет, но есть proxy_manager, получаем следующий доступный прокси
        # Это нужно для случаев, когда прокси еще не был установлен, но proxy_manager доступен
        if self.proxy_manager:
            next_proxy = await self.proxy_manager.get_next_proxy(force_refresh=False)
            if next_proxy:
                # Устанавливаем прокси для последующего использования
                self.proxy = next_proxy.url
                await self._ensure_client()
                return next_proxy
        
        return None
    
    async def _handle_429_error(
        self, 
        response: Optional[httpx.Response], 
        attempt: int, 
        max_retries: int,
        base_delay: float,
        context: str = ""
    ) -> bool:
        """
        Обрабатывает 429 ошибку: сразу блокирует прокси и переключается на другой.
        
        Returns:
            True - если прокси переключен и нужно продолжить попытки
            False - если не удалось переключить прокси или достигнут лимит попыток
        """
        # Получаем текущий прокси
        current_proxy = await self._get_current_proxy()
        
        # Быстро блокируем прокси и переключаемся
        await self._handle_429_fast(current_proxy, context)
        
        # Пытаемся переключиться на другой прокси
        if self.proxy_manager:
            proxy_switched = await self._switch_proxy()
            if proxy_switched:
                # Прокси переключен - продолжаем попытки с новым прокси
                logger.info(f"✅ Прокси переключен, продолжаем попытки с новым прокси (попытка {attempt + 1}/{max_retries})")
                return True
            else:
                # Не удалось переключить прокси - выходим из цикла
                logger.warning(f"⚠️ Не удалось переключить прокси, прекращаем попытки")
                return False
        else:
            # Нет ProxyManager - не можем переключить прокси
            logger.warning(f"⚠️ Нет ProxyManager для переключения прокси")
            return False
    
    async def _ensure_client(self):
        """Создает HTTP клиент, если он еще не создан."""
        if self._client is None:
            headers = self._get_browser_headers()
            if self.proxy:
                logger.debug(f"🌐 SteamMarketParser: Создаем HTTP клиент с прокси: {self.proxy[:50]}...")
            else:
                logger.warning("⚠️ SteamMarketParser: Создаем HTTP клиент БЕЗ прокси (прямое подключение)")
            logger.debug(f"📋 User-Agent: {headers.get('User-Agent', 'Unknown')[:80]}...")
            
            self._client = httpx.AsyncClient(
                proxy=self.proxy,
                timeout=self.timeout,
                headers=headers,
                follow_redirects=True,
                cookies={},
            )
            logger.debug("🍪 HTTP клиент создан с поддержкой cookies и реалистичными заголовками для обхода блокировок")
