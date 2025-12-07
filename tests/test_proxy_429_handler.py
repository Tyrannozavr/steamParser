"""
Юнит-тесты для Proxy429Handler.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.proxy_429_handler import Proxy429Handler
from services.proxy_manager import ProxyManager
from services.proxy_context import ProxyContext
from core import Proxy


@pytest.mark.asyncio
async def test_execute_with_retry_success():
    """Тест: успешное выполнение запроса без 429 ошибок."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    # Мокаем use_proxy как контекстный менеджер
    context = MagicMock(spec=ProxyContext)
    context.proxy = proxy
    context.mark_success = AsyncMock()
    context.mark_429_error = AsyncMock()
    context.mark_error = AsyncMock()
    
    proxy_manager.use_proxy = AsyncMock(return_value=context)
    
    handler = Proxy429Handler(proxy_manager)
    
    # Мокаем request_func
    request_func = AsyncMock(return_value="success_result")
    
    result = await handler.execute_with_retry(request_func)
    
    assert result == "success_result"
    request_func.assert_called_once_with(proxy)
    context.mark_success.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_429_retry():
    """Тест: автоматический retry при 429 ошибке."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    
    # Создаем два прокси для retry
    proxy1 = MagicMock(spec=Proxy)
    proxy1.id = 1
    proxy2 = MagicMock(spec=Proxy)
    proxy2.id = 2
    
    # Мокаем use_proxy для возврата разных прокси
    context1 = MagicMock(spec=ProxyContext)
    context1.proxy = proxy1
    context1.mark_success = AsyncMock()
    context1.mark_429_error = AsyncMock()
    
    context2 = MagicMock(spec=ProxyContext)
    context2.proxy = proxy2
    context2.mark_success = AsyncMock()
    context2.mark_429_error = AsyncMock()
    
    proxy_manager.use_proxy = AsyncMock(side_effect=[context1, context2])
    
    handler = Proxy429Handler(proxy_manager)
    
    # Мокаем request_func: первый вызов - 429, второй - успех
    request_func = AsyncMock(side_effect=[
        Exception("429 Too Many Requests"),
        "success_result"
    ])
    
    result = await handler.execute_with_retry(request_func, max_retries=2)
    
    assert result == "success_result"
    assert request_func.call_count == 2
    context1.mark_429_error.assert_called_once()
    context2.mark_success.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_429_max_retries():
    """Тест: исчерпание попыток при 429 ошибках."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    context = MagicMock(spec=ProxyContext)
    context.proxy = proxy
    context.mark_429_error = AsyncMock()
    
    proxy_manager.use_proxy = AsyncMock(return_value=context)
    
    handler = Proxy429Handler(proxy_manager)
    
    # Мокаем request_func: всегда 429
    request_func = AsyncMock(side_effect=Exception("429 Too Many Requests"))
    
    result = await handler.execute_with_retry(request_func, max_retries=3)
    
    assert result is None
    assert request_func.call_count == 3
    assert context.mark_429_error.call_count == 3


@pytest.mark.asyncio
async def test_execute_with_retry_other_error():
    """Тест: другая ошибка (не 429) не вызывает автоматический retry."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    context = MagicMock(spec=ProxyContext)
    context.proxy = proxy
    context.mark_error = AsyncMock()
    
    proxy_manager.use_proxy = AsyncMock(return_value=context)
    
    handler = Proxy429Handler(proxy_manager)
    
    # Мокаем request_func: другая ошибка
    request_func = AsyncMock(side_effect=Exception("Connection timeout"))
    
    with pytest.raises(Exception, match="Connection timeout"):
        await handler.execute_with_retry(request_func)
    
    request_func.assert_called_once()
    context.mark_error.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_no_proxy():
    """Тест: обработка случая, когда прокси не получен."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    
    context = MagicMock(spec=ProxyContext)
    context.proxy = None
    
    proxy_manager.use_proxy = AsyncMock(return_value=context)
    
    handler = Proxy429Handler(proxy_manager)
    
    request_func = AsyncMock()
    
    result = await handler.execute_with_retry(request_func, max_retries=2)
    
    # Должен вернуть None после исчерпания попыток
    assert result is None
    request_func.assert_not_called()  # Не должен вызываться, т.к. proxy=None

