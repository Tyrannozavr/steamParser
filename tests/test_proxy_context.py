"""
Юнит-тесты для ProxyContext.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from services.proxy_context import ProxyContext
from services.proxy_manager import ProxyManager
from core import Proxy


@pytest.mark.asyncio
async def test_proxy_context_success():
    """Тест: успешное использование прокси через контекст."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    context = ProxyContext(proxy_manager, proxy)
    
    async with context:
        assert context.proxy is proxy
        await context.mark_success()
    
    # Проверяем, что был вызван mark_proxy_used с success=True
    proxy_manager.mark_proxy_used.assert_called_once()
    call_args = proxy_manager.mark_proxy_used.call_args
    assert call_args[0][0] is proxy
    assert call_args[1]['success'] is True
    assert call_args[1]['is_429_error'] is False
    
    # Проверяем, что был вызван _release_proxy
    proxy_manager._release_proxy.assert_called_once_with(proxy.id)


@pytest.mark.asyncio
async def test_proxy_context_429_error():
    """Тест: обработка 429 ошибки через контекст."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    context = ProxyContext(proxy_manager, proxy)
    
    async with context:
        assert context.proxy is proxy
        await context.mark_429_error()
    
    # Проверяем, что был вызван mark_proxy_used с is_429_error=True
    proxy_manager.mark_proxy_used.assert_called_once()
    call_args = proxy_manager.mark_proxy_used.call_args
    assert call_args[0][0] is proxy
    assert call_args[1]['success'] is False
    assert call_args[1]['is_429_error'] is True
    assert "429" in call_args[1]['error']


@pytest.mark.asyncio
async def test_proxy_context_other_error():
    """Тест: обработка другой ошибки через контекст."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    context = ProxyContext(proxy_manager, proxy)
    error_message = "Connection timeout"
    
    async with context:
        assert context.proxy is proxy
        await context.mark_error(error_message)
    
    # Проверяем, что был вызван mark_proxy_used с error
    proxy_manager.mark_proxy_used.assert_called_once()
    call_args = proxy_manager.mark_proxy_used.call_args
    assert call_args[0][0] is proxy
    assert call_args[1]['success'] is False
    assert call_args[1]['is_429_error'] is False
    assert call_args[1]['error'] == error_message


@pytest.mark.asyncio
async def test_proxy_context_none_proxy():
    """Тест: контекст с None прокси."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    
    context = ProxyContext(proxy_manager, None)
    
    async with context:
        assert context.proxy is None
    
    # Не должно быть вызовов методов
    proxy_manager.mark_proxy_used.assert_not_called()
    proxy_manager._release_proxy.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_context_auto_success():
    """Тест: автоматический успех при отсутствии явного вызова mark_success/mark_error."""
    proxy_manager = AsyncMock(spec=ProxyManager)
    proxy = MagicMock(spec=Proxy)
    proxy.id = 1
    
    context = ProxyContext(proxy_manager, proxy)
    
    async with context:
        assert context.proxy is proxy
        # Не вызываем mark_success или mark_error
    
    # Должен быть вызван mark_proxy_used с success=True (по умолчанию)
    proxy_manager.mark_proxy_used.assert_called_once()
    call_args = proxy_manager.mark_proxy_used.call_args
    assert call_args[1]['success'] is True

