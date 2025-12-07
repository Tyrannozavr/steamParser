"""
Комплексные юнит-тесты для Proxy429Handler с моками.
Покрывает обработку 429 ошибок, ретраи, переключение прокси.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import httpx

from services.proxy_429_handler import Proxy429Handler
from services.proxy_manager import ProxyManager
from services.proxy_context import ProxyContext
from core import Proxy


@pytest.fixture
def mock_proxy_manager():
    """Мок ProxyManager."""
    manager = AsyncMock(spec=ProxyManager)
    return manager


@pytest.fixture
def mock_proxies():
    """Создает список мок-прокси."""
    proxies = []
    for i in range(1, 6):
        proxy = MagicMock(spec=Proxy)
        proxy.id = i
        proxy.url = f"http://proxy{i}:8080"
        proxies.append(proxy)
    return proxies


@pytest.fixture
def mock_proxy_context():
    """Фабрика для создания мок-контекстов."""
    def create_context(proxy, should_fail=False, fail_type="429"):
        ctx = MagicMock(spec=ProxyContext)
        ctx.proxy = proxy
        ctx.mark_success = AsyncMock()
        ctx.mark_error = AsyncMock()
        ctx.mark_429_error = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx
    return create_context


@pytest.mark.asyncio
async def test_execute_with_retry_success_first_try(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: успешное выполнение с первой попытки."""
    proxy = mock_proxies[0]
    ctx = mock_proxy_context(proxy)
    mock_proxy_manager.use_proxy = AsyncMock(return_value=ctx)
    
    handler = Proxy429Handler(mock_proxy_manager)
    
    request_func = AsyncMock(return_value="success")
    
    result = await handler.execute_with_retry(request_func)
    
    assert result == "success"
    request_func.assert_called_once_with(proxy)
    ctx.mark_success.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_429_switch_proxy(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: 429 ошибка - переключение на другой прокси."""
    proxy1 = mock_proxies[0]
    proxy2 = mock_proxies[1]
    
    ctx1 = mock_proxy_context(proxy1)
    ctx2 = mock_proxy_context(proxy2)
    
    mock_proxy_manager.use_proxy = AsyncMock(side_effect=[ctx1, ctx2])
    
    handler = Proxy429Handler(mock_proxy_manager)
    
    # Первый вызов - 429, второй - успех
    request_func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock(status_code=429)),
        "success"
    ])
    
    result = await handler.execute_with_retry(request_func, max_retries=5)
    
    assert result == "success"
    assert request_func.call_count == 2
    ctx1.mark_error.assert_called_once()
    ctx2.mark_success.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_429_max_retries_exceeded(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: исчерпание попыток при 429 ошибках."""
    proxy = mock_proxies[0]
    ctx = mock_proxy_context(proxy)
    mock_proxy_manager.use_proxy = AsyncMock(return_value=ctx)
    
    handler = Proxy429Handler(mock_proxy_manager)
    
    # Всегда 429
    request_func = AsyncMock(side_effect=httpx.HTTPStatusError(
        "429",
        request=MagicMock(),
        response=MagicMock(status_code=429)
    ))
    
    with pytest.raises(Exception, match="Не удалось выполнить запрос"):
        await handler.execute_with_retry(request_func, max_retries=3)
    
    assert request_func.call_count == 3
    assert ctx.mark_error.call_count == 3


@pytest.mark.asyncio
async def test_execute_with_retry_429_all_proxies_blocked(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: все прокси заблокированы - система ждет и пробует снова."""
    # Создаем контексты с None прокси (все заблокированы)
    ctx_none = mock_proxy_context(None)
    ctx_success = mock_proxy_context(mock_proxies[0])
    
    # Первые попытки - нет прокси, последняя - успех
    mock_proxy_manager.use_proxy = AsyncMock(side_effect=[ctx_none, ctx_none, ctx_success])
    
    handler = Proxy429Handler(mock_proxy_manager)
    
    request_func = AsyncMock(return_value="success")
    
    result = await handler.execute_with_retry(request_func, max_retries=5)
    
    assert result == "success"
    # Должен быть вызов после получения прокси
    assert request_func.call_count == 1


@pytest.mark.asyncio
async def test_execute_with_retry_network_error(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: сетевая ошибка (не 429) - не ретраится."""
    proxy = mock_proxies[0]
    ctx = mock_proxy_context(proxy)
    mock_proxy_manager.use_proxy = AsyncMock(return_value=ctx)
    
    handler = Proxy429Handler(mock_proxy_manager)
    
    # Сетевая ошибка
    request_func = AsyncMock(side_effect=httpx.RequestError("Connection failed"))
    
    with pytest.raises(httpx.RequestError):
        await handler.execute_with_retry(request_func)
    
    request_func.assert_called_once()
    ctx.mark_error.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_mixed_errors(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: смешанные ошибки - 429, затем другая ошибка."""
    proxy1 = mock_proxies[0]
    proxy2 = mock_proxies[1]
    
    ctx1 = mock_proxy_context(proxy1)
    ctx2 = mock_proxy_context(proxy2)
    
    mock_proxy_manager.use_proxy = AsyncMock(side_effect=[ctx1, ctx2])
    
    handler = Proxy429Handler(mock_proxy_manager)
    
    # Первый - 429, второй - другая ошибка
    request_func = AsyncMock(side_effect=[
        httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock(status_code=429)),
        httpx.RequestError("Connection failed")
    ])
    
    with pytest.raises(httpx.RequestError):
        await handler.execute_with_retry(request_func, max_retries=5)
    
    assert request_func.call_count == 2
    ctx1.mark_error.assert_called_once()
    ctx2.mark_error.assert_called_once()


@pytest.mark.asyncio
async def test_execute_with_retry_high_load(mock_proxy_manager, mock_proxies, mock_proxy_context):
    """Тест: высокая нагрузка - много одновременных запросов."""
    handler = Proxy429Handler(mock_proxy_manager)
    
    # Создаем 10 одновременных задач
    async def execute_task(task_id):
        proxy = mock_proxies[task_id % len(mock_proxies)]
        ctx = mock_proxy_context(proxy)
        mock_proxy_manager.use_proxy = AsyncMock(return_value=ctx)
        
        request_func = AsyncMock(return_value=f"success_{task_id}")
        return await handler.execute_with_retry(request_func)
    
    tasks = [execute_task(i) for i in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Все должны быть успешными
    valid_results = [r for r in results if not isinstance(r, Exception)]
    assert len(valid_results) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

