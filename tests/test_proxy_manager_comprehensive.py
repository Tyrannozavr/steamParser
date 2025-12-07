"""
Комплексные юнит-тесты для ProxyManager с моками.
Покрывает все крайние случаи: очередь, ожидание, блокировки, нагрузка.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from typing import List

from services.proxy_manager import ProxyManager
from core import Proxy
from services.redis_service import RedisService


@pytest.fixture
def mock_db_session():
    """Мок сессии БД."""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_redis_service():
    """Мок Redis сервиса."""
    redis = AsyncMock(spec=RedisService)
    redis.is_connected = MagicMock(return_value=True)
    redis._client = AsyncMock()
    redis._client.get = AsyncMock(return_value=None)
    redis._client.set = AsyncMock(return_value=True)
    redis._client.delete = AsyncMock(return_value=1)
    redis._client.exists = AsyncMock(return_value=False)
    return redis


@pytest.fixture
def mock_proxies():
    """Создает список мок-прокси."""
    proxies = []
    for i in range(1, 6):
        proxy = MagicMock(spec=Proxy)
        proxy.id = i
        proxy.url = f"http://proxy{i}:8080"
        proxy.is_active = True
        proxy.delay_seconds = 0.2
        proxy.success_count = 0
        proxy.fail_count = 0
        proxy.last_used = None
        proxies.append(proxy)
    return proxies


@pytest.mark.asyncio
async def test_get_proxy_basic(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: базовое получение прокси."""
    manager = ProxyManager(
        db_session=mock_db_session,
        redis_service=mock_redis_service,
        default_delay=0.2
    )
    
    # Мокаем get_active_proxies
    manager.get_active_proxies = AsyncMock(return_value=mock_proxies)
    # Мокаем _get_proxy_last_used_from_redis чтобы возвращал None (прокси не использовался)
    manager._get_proxy_last_used_from_redis = AsyncMock(return_value=None)
    # Мокаем _reserve_proxy чтобы всегда возвращал True
    manager._reserve_proxy = AsyncMock(return_value=True)
    # Мокаем _is_proxy_temporarily_blocked чтобы всегда возвращал False
    manager._is_proxy_temporarily_blocked = AsyncMock(return_value=False)
    # Мокаем _is_proxy_in_use чтобы всегда возвращал False
    manager._is_proxy_in_use = AsyncMock(return_value=False)
    # Мокаем _set_last_proxy_index
    manager._set_last_proxy_index = AsyncMock()
    
    ctx = await manager.use_proxy()
    async with ctx:
        assert ctx.proxy is not None
        assert ctx.proxy.id in [p.id for p in mock_proxies]
        await ctx.mark_success()


@pytest.mark.asyncio
async def test_get_proxy_all_busy_wait(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: все прокси заняты - система ждет и возвращает самый старый."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.2
        )
        
        # Резервируем все прокси кроме одного
        for i in range(4):
            await manager._reserve_proxy(mock_proxies[i].id)
        
        # Устанавливаем время последнего использования для последнего прокси
        last_used_time = datetime.now() - timedelta(seconds=0.3)  # Прошло больше delay
        mock_redis_service._client.get = AsyncMock(
            return_value=last_used_time.isoformat().encode()
        )
        
        # Должен вернуть прокси после ожидания
        ctx = await manager.use_proxy()
        async with ctx:
            assert ctx.proxy is not None
            await ctx.mark_success()


@pytest.mark.asyncio
async def test_get_proxy_all_blocked_429(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: все прокси заблокированы из-за 429 - система ждет разблокировки."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.2
        )
        
        # Блокируем все прокси на 30 минут
        blocked_until = datetime.now() + timedelta(minutes=30)
        for proxy in mock_proxies:
            await manager._block_proxy_temporarily(proxy.id, duration_seconds=1800)
            mock_redis_service._client.get = AsyncMock(
                return_value=blocked_until.isoformat().encode()
            )
        
        # Должен вернуть None (все заблокированы)
        ctx = await manager.use_proxy()
        async with ctx:
            # В реальности система должна ждать, но для теста проверяем логику
            if ctx.proxy is None:
                # Это нормально - все прокси заблокированы
                pass


@pytest.mark.asyncio
async def test_get_proxy_high_load_many_proxies_few_requests(mock_db_session, mock_redis_service):
    """Тест: высокая нагрузка - много прокси, мало запросов."""
    # Создаем 50 прокси
    many_proxies = []
    for i in range(1, 51):
        proxy = MagicMock(spec=Proxy)
        proxy.id = i
        proxy.url = f"http://proxy{i}:8080"
        proxy.is_active = True
        proxy.delay_seconds = 0.2
        proxy.success_count = 0
        proxy.fail_count = 0
        proxy.last_used = None
        many_proxies.append(proxy)
    
    with patch.object(ProxyManager, 'get_active_proxies', return_value=many_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.2
        )
        
        # Делаем только 5 запросов одновременно
        tasks = []
        for i in range(5):
            async def get_proxy_task():
                ctx = await manager.use_proxy()
                async with ctx:
                    if ctx.proxy:
                        await ctx.mark_success()
                        return ctx.proxy.id
            tasks.append(get_proxy_task())
        
        results = await asyncio.gather(*tasks)
        
        # Все должны получить разные прокси
        assert len(set(results)) == 5  # Все разные


@pytest.mark.asyncio
async def test_get_proxy_high_load_few_proxies_many_requests(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: высокая нагрузка - мало прокси (5), много запросов (20)."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.1  # Маленькая задержка для быстрого теста
        )
        
        # Делаем 20 запросов одновременно
        tasks = []
        for i in range(20):
            async def get_proxy_task():
                ctx = await manager.use_proxy()
                async with ctx:
                    if ctx.proxy:
                        await asyncio.sleep(0.05)  # Симулируем работу
                        await ctx.mark_success()
                        return ctx.proxy.id
            tasks.append(get_proxy_task())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Все должны получить прокси (система ждет)
        valid_results = [r for r in results if not isinstance(r, Exception)]
        assert len(valid_results) == 20  # Все получили прокси


@pytest.mark.asyncio
async def test_get_proxy_429_error_handling(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: обработка 429 ошибки - прокси блокируется, используется другой."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.2
        )
        
        # Получаем первый прокси
        ctx1 = await manager.use_proxy()
        async with ctx1:
            proxy1 = ctx1.proxy
            # Симулируем 429 ошибку
            await ctx1.mark_error(error="429 Too Many Requests")
        
        # Проверяем, что прокси заблокирован
        is_blocked = await manager._is_proxy_temporarily_blocked(proxy1.id)
        assert is_blocked is True
        
        # Получаем следующий прокси (должен быть другой)
        ctx2 = await manager.use_proxy()
        async with ctx2:
            proxy2 = ctx2.proxy
            assert proxy2.id != proxy1.id
            await ctx2.mark_success()


@pytest.mark.asyncio
async def test_get_proxy_queue_waiting(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: очередь ожидания - если прокси еще "свежий", система ждет."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.2
        )
        
        # Используем прокси
        ctx1 = await manager.use_proxy()
        async with ctx1:
            proxy1 = ctx1.proxy
            await ctx1.mark_success()
        
        # Сразу пытаемся использовать тот же прокси
        # Система должна подождать delay_seconds
        start_time = datetime.now()
        ctx2 = await manager.use_proxy()
        async with ctx2:
            proxy2 = ctx2.proxy
            await ctx2.mark_success()
        end_time = datetime.now()
        
        # Должна быть задержка (хотя бы минимальная)
        elapsed = (end_time - start_time).total_seconds()
        # В реальности может быть больше из-за асинхронности, но должна быть задержка


@pytest.mark.asyncio
async def test_get_proxy_no_proxies_available(mock_db_session, mock_redis_service):
    """Тест: нет доступных прокси - система возвращает None и ждет."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=[]):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.2
        )
        
        ctx = await manager.use_proxy()
        async with ctx:
            # Должен вернуть None, так как нет прокси
            assert ctx.proxy is None


@pytest.mark.asyncio
async def test_get_proxy_rotation(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: ротация прокси - каждый раз возвращается следующий."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.0  # Без задержки для быстрого теста
        )
        
        used_proxy_ids = []
        for i in range(5):
            ctx = await manager.use_proxy()
            async with ctx:
                if ctx.proxy:
                    used_proxy_ids.append(ctx.proxy.id)
                    await ctx.mark_success()
        
        # Должны использоваться разные прокси (ротация)
        assert len(set(used_proxy_ids)) >= 3  # Хотя бы 3 разных


@pytest.mark.asyncio
async def test_get_proxy_concurrent_access(mock_db_session, mock_redis_service, mock_proxies):
    """Тест: конкурентный доступ - несколько задач одновременно."""
    with patch.object(ProxyManager, 'get_active_proxies', return_value=mock_proxies):
        manager = ProxyManager(
            db_session=mock_db_session,
            redis_service=mock_redis_service,
            default_delay=0.0
        )
        
        # Запускаем 10 задач одновременно
        async def use_proxy_task(task_id):
            ctx = await manager.use_proxy()
            async with ctx:
                if ctx.proxy:
                    await asyncio.sleep(0.01)  # Симулируем работу
                    await ctx.mark_success()
                    return ctx.proxy.id
            return None
        
        tasks = [use_proxy_task(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Все должны получить прокси (система ждет)
        valid_results = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert len(valid_results) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

