"""
Юнит-тесты для ProxyManagerFactory.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from services.proxy_manager_factory import ProxyManagerFactory
from services.proxy_manager import ProxyManager


@pytest.mark.asyncio
async def test_factory_creates_singleton():
    """Тест: фабрика создает singleton экземпляр."""
    # Очищаем существующие экземпляры
    await ProxyManagerFactory.clear_instance("steam")
    
    db_session = AsyncMock()
    redis_service = AsyncMock()
    
    # Создаем первый экземпляр
    instance1 = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        default_delay=0.2,
        site="steam"
    )
    
    assert instance1 is not None
    assert isinstance(instance1, ProxyManager)
    
    # Создаем второй экземпляр с теми же параметрами
    instance2 = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        default_delay=0.2,
        site="steam"
    )
    
    # Должен быть тот же экземпляр (singleton)
    assert instance1 is instance2


@pytest.mark.asyncio
async def test_factory_creates_different_instances_for_different_sites():
    """Тест: фабрика создает разные экземпляры для разных сайтов."""
    await ProxyManagerFactory.clear_instance("steam")
    await ProxyManagerFactory.clear_instance("other_site")
    
    db_session = AsyncMock()
    redis_service = AsyncMock()
    
    # Создаем экземпляр для steam
    instance_steam = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        site="steam"
    )
    
    # Создаем экземпляр для другого сайта
    instance_other = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        site="other_site"
    )
    
    # Должны быть разные экземпляры
    assert instance_steam is not instance_other


@pytest.mark.asyncio
async def test_factory_clear_instance():
    """Тест: очистка экземпляра."""
    await ProxyManagerFactory.clear_instance("steam")
    
    db_session = AsyncMock()
    redis_service = AsyncMock()
    
    # Создаем экземпляр
    instance1 = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        site="steam"
    )
    
    # Очищаем
    await ProxyManagerFactory.clear_instance("steam")
    
    # Создаем новый экземпляр
    instance2 = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        site="steam"
    )
    
    # Должен быть новый экземпляр
    assert instance1 is not instance2


@pytest.mark.asyncio
async def test_factory_get_instance_sync():
    """Тест: синхронное получение экземпляра."""
    await ProxyManagerFactory.clear_instance("steam")
    
    db_session = AsyncMock()
    redis_service = AsyncMock()
    
    # Сначала создаем экземпляр асинхронно
    instance_async = await ProxyManagerFactory.get_instance(
        db_session=db_session,
        redis_service=redis_service,
        site="steam"
    )
    
    # Получаем синхронно
    instance_sync = ProxyManagerFactory.get_instance_sync(site="steam")
    
    # Должен быть тот же экземпляр
    assert instance_async is instance_sync
    
    # Если экземпляр не создан, должен вернуть None
    await ProxyManagerFactory.clear_instance("nonexistent")
    instance_none = ProxyManagerFactory.get_instance_sync(site="nonexistent")
    assert instance_none is None

