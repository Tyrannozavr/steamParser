"""
Сервис для обработки 429 ошибок (Too Many Requests).
Отвечает за автоматическое переключение прокси при получении 429 ошибки.
"""
import asyncio
from typing import Optional, Callable, Any, Dict
from loguru import logger

from services.proxy_manager import ProxyManager
from core import Proxy


class Proxy429Handler:
    """Сервис для обработки 429 ошибок с автоматическим переключением прокси."""
    
    def __init__(self, proxy_manager: ProxyManager):
        """
        Инициализация сервиса.
        
        Args:
            proxy_manager: Менеджер прокси
        """
        self.proxy_manager = proxy_manager
        self.max_retries = 50  # Максимальное количество попыток с разными прокси
    
    async def execute_with_retry(
        self,
        request_func: Callable[[Proxy], Any],
        max_retries: Optional[int] = None
    ) -> Optional[Any]:
        """
        Выполняет запрос с автоматическим переключением прокси при 429 ошибке.
        
        Args:
            request_func: Асинхронная функция, принимающая Proxy и возвращающая результат
                         Должна бросать исключение с текстом "429" или "Too Many Requests" при 429 ошибке
            max_retries: Максимальное количество попыток (по умолчанию self.max_retries)
            
        Returns:
            Результат выполнения request_func или None при исчерпании попыток
        """
        max_retries = max_retries or self.max_retries
        retry_count = 0
        
        while retry_count < max_retries:
            # Получаем прокси через контекстный менеджер
            proxy_context = await self.proxy_manager.use_proxy()
            async with proxy_context:
                proxy = proxy_context.proxy
                
                if not proxy:
                    logger.warning(f"⚠️ Proxy429Handler: Не удалось получить прокси (попытка {retry_count + 1}/{max_retries})")
                    retry_count += 1
                    await asyncio.sleep(1.0)  # Небольшая задержка перед следующей попыткой
                    continue
                
                try:
                    logger.debug(f"🔄 Proxy429Handler: Попытка {retry_count + 1}/{max_retries} с прокси ID={proxy.id}")
                    
                    # Выполняем запрос
                    result = await request_func(proxy)
                    
                    # Успешный результат - отмечаем прокси как успешно использованный
                    await proxy_context.mark_success()
                    logger.info(f"✅ Proxy429Handler: Успешный запрос через прокси ID={proxy.id}")
                    return result
                    
                except Exception as e:
                    error_str = str(e)
                    is_429 = "429" in error_str or "Too Many Requests" in error_str
                    
                    if is_429:
                        # 429 ошибка - отмечаем прокси как заблокированный и пробуем другой
                        await proxy_context.mark_429_error()
                        logger.warning(
                            f"🚫 Proxy429Handler: 429 ошибка на прокси ID={proxy.id} "
                            f"(попытка {retry_count + 1}/{max_retries}), переключаемся на другой прокси"
                        )
                        retry_count += 1
                        
                        # Небольшая задержка перед следующей попыткой
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        # Другая ошибка - отмечаем как неуспешную, но не переключаемся автоматически
                        await proxy_context.mark_error(str(e))
                        logger.error(
                            f"❌ Proxy429Handler: Ошибка на прокси ID={proxy.id}: {type(e).__name__}: {error_str}"
                        )
                        # Для других ошибок не делаем автоматический retry
                        raise
        
        logger.error(f"❌ Proxy429Handler: Исчерпаны все попытки ({max_retries}), не удалось выполнить запрос")
        return None
    
    async def execute_with_retry_sync(
        self,
        request_func: Callable[[Proxy], Any],
        max_retries: Optional[int] = None
    ) -> Optional[Any]:
        """
        Синхронная версия execute_with_retry (для совместимости).
        
        Args:
            request_func: Функция, принимающая Proxy и возвращающая результат
            max_retries: Максимальное количество попыток
            
        Returns:
            Результат выполнения request_func или None
        """
        return await self.execute_with_retry(request_func, max_retries)

