"""
Контекстный менеджер для работы с прокси.
Автоматически управляет жизненным циклом прокси (резервация, освобождение, обновление статистики).
"""
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from loguru import logger

from core import Proxy

if TYPE_CHECKING:
    from services.proxy_manager import ProxyManager


class ProxyContext:
    """Контекстный менеджер для работы с прокси."""
    
    def __init__(self, proxy_manager: "ProxyManager", proxy: Optional[Proxy]):
        """
        Инициализация контекста.
        
        Args:
            proxy_manager: Менеджер прокси
            proxy: Прокси для использования
        """
        self.proxy_manager = proxy_manager
        self.proxy = proxy
        self._success = False
        self._error = None
        self._is_429 = False
        self._start_time = datetime.now()
    
    async def __aenter__(self):
        """Вход в контекст - прокси уже зарезервирован."""
        if self.proxy:
            logger.debug(f"🔓 ProxyContext: Вход в контекст для прокси ID={self.proxy.id}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Выход из контекста - освобождаем прокси и обновляем статистику."""
        if not self.proxy:
            return
        
        try:
            # Освобождаем резервацию прокси
            await self.proxy_manager._release_proxy(self.proxy.id)
            
            # Обновляем статистику использования
            if self._success:
                await self.proxy_manager.mark_proxy_used(
                    self.proxy,
                    success=True,
                    error=None,
                    is_429_error=False
                )
            elif self._is_429:
                await self.proxy_manager.mark_proxy_used(
                    self.proxy,
                    success=False,
                    error="429 Too Many Requests",
                    is_429_error=True
                )
            elif self._error:
                await self.proxy_manager.mark_proxy_used(
                    self.proxy,
                    success=False,
                    error=self._error,
                    is_429_error=False
                )
            else:
                # Не было явного вызова mark_success/mark_error - считаем успешным
                await self.proxy_manager.mark_proxy_used(
                    self.proxy,
                    success=True,
                    error=None,
                    is_429_error=False
                )
            
            duration = (datetime.now() - self._start_time).total_seconds()
            logger.debug(
                f"🔓 ProxyContext: Выход из контекста для прокси ID={self.proxy.id} "
                f"(успех={self._success}, ошибка={self._error is not None}, длительность={duration:.2f}с)"
            )
        except Exception as e:
            logger.error(f"❌ ProxyContext: Ошибка при выходе из контекста для прокси ID={self.proxy.id}: {e}")
    
    async def mark_success(self):
        """Отмечает использование прокси как успешное."""
        self._success = True
        self._error = None
        self._is_429 = False
    
    async def mark_error(self, error: str):
        """
        Отмечает использование прокси как неуспешное.
        
        Args:
            error: Текст ошибки
        """
        self._success = False
        self._error = error
        self._is_429 = "429" in error or "Too Many Requests" in error
    
    async def mark_429_error(self):
        """Отмечает использование прокси как 429 ошибку."""
        self._success = False
        self._error = "429 Too Many Requests"
        self._is_429 = True

