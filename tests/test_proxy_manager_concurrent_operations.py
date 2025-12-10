"""
Тесты для воспроизведения ошибок конкурентного доступа в ProxyManager.

Эти тесты должны вызывать ошибки типа:
- "cannot perform operation: another operation is in progress"
- "This session is provisioning a new connection; concurrent operations are not permitted"
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


class TestProxyManagerConcurrentOperations(unittest.TestCase):
    """Тесты для проверки конкурентного доступа к БД в ProxyManager."""
    
    def setUp(self):
        """Настройка тестового окружения."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def tearDown(self):
        """Очистка после тестов."""
        self.loop.close()
    
    async def _create_mock_proxy_manager(self):
        """Создает мок ProxyManager с реальной блокировкой."""
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        from services.proxy_manager import ProxyManager
        
        # Создаем мок для db_session
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalar.return_value = 0
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        # Создаем мок для redis_service
        mock_redis = AsyncMock()
        mock_redis._client = AsyncMock()
        mock_redis._client.get.return_value = None
        mock_redis._client.setex = AsyncMock(return_value=True)
        mock_redis._client.delete = AsyncMock(return_value=1)
        mock_redis.is_connected = MagicMock(return_value=True)
        
        # Создаем ProxyManager
        proxy_manager = ProxyManager(
            db_session=mock_session,
            redis_service=mock_redis
        )
        
        return proxy_manager, mock_session
    
    async def test_concurrent_get_active_proxies(self):
        """
        Тест: одновременные вызовы get_active_proxies должны вызывать ошибку
        конкурентного доступа, если блокировка не работает правильно.
        """
        proxy_manager, mock_session = await self._create_mock_proxy_manager()
        
        # Симулируем ситуацию, когда execute вызывается одновременно
        call_count = {'count': 0}
        
        async def mock_execute(*args, **kwargs):
            """Мок execute, который симулирует конкурентный доступ."""
            call_count['count'] += 1
            # Если это не первый вызов, симулируем ошибку конкурентного доступа
            if call_count['count'] > 1:
                from sqlalchemy.exc import InterfaceError
                from asyncpg.exceptions import InterfaceError as AsyncPGInterfaceError
                raise InterfaceError(
                    "cannot perform operation: another operation is in progress",
                    orig=AsyncPGInterfaceError("cannot perform operation: another operation is in progress")
                )
            # Первый вызов успешен
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result
        
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        
        # Вызываем get_active_proxies одновременно из нескольких корутин
        async def call_get_active_proxies():
            try:
                await proxy_manager.get_active_proxies(force_refresh=True)
                return "success"
            except Exception as e:
                return f"error: {type(e).__name__}: {str(e)[:100]}"
        
        # Запускаем 10 одновременных вызовов
        results = await asyncio.gather(*[call_get_active_proxies() for _ in range(10)])
        
        # Проверяем, что были ошибки конкурентного доступа
        errors = [r for r in results if "error" in r and "InterfaceError" in r]
        
        # Если блокировка работает правильно, не должно быть ошибок
        # Если блокировка не работает, будут ошибки
        print(f"\n📊 Результаты теста concurrent_get_active_proxies:")
        print(f"   Всего вызовов: {len(results)}")
        print(f"   Ошибок: {len(errors)}")
        print(f"   Успешных: {len([r for r in results if r == 'success'])}")
        
        # Этот тест должен показать проблему, если она есть
        # После исправления ошибок не должно быть
        if errors:
            print(f"   ⚠️ Найдены ошибки конкурентного доступа (ожидаемо до исправления)")
            for i, err in enumerate(errors[:3], 1):
                print(f"      {i}. {err}")
    
    async def test_concurrent_update_redis_cache(self):
        """
        Тест: одновременные вызовы _update_redis_cache должны вызывать ошибку
        конкурентного доступа, если блокировка не работает правильно.
        """
        proxy_manager, mock_session = await self._create_mock_proxy_manager()
        
        # Симулируем ситуацию, когда execute вызывается одновременно
        call_count = {'count': 0}
        
        async def mock_execute(*args, **kwargs):
            """Мок execute, который симулирует конкурентный доступ."""
            call_count['count'] += 1
            # Если это не первый вызов, симулируем ошибку конкурентного доступа
            if call_count['count'] > 1:
                from sqlalchemy.exc import InterfaceError
                from asyncpg.exceptions import InterfaceError as AsyncPGInterfaceError
                raise InterfaceError(
                    "cannot perform operation: another operation is in progress",
                    orig=AsyncPGInterfaceError("cannot perform operation: another operation is in progress")
                )
            # Первый вызов успешен
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result
        
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        
        # Вызываем _update_redis_cache одновременно из нескольких корутин
        async def call_update_cache():
            try:
                await proxy_manager._update_redis_cache()
                return "success"
            except Exception as e:
                return f"error: {type(e).__name__}: {str(e)[:100]}"
        
        # Запускаем 10 одновременных вызовов
        results = await asyncio.gather(*[call_update_cache() for _ in range(10)])
        
        # Проверяем, что были ошибки конкурентного доступа
        errors = [r for r in results if "error" in r and "InterfaceError" in r]
        
        print(f"\n📊 Результаты теста concurrent_update_redis_cache:")
        print(f"   Всего вызовов: {len(results)}")
        print(f"   Ошибок: {len(errors)}")
        print(f"   Успешных: {len([r for r in results if r == 'success'])}")
        
        if errors:
            print(f"   ⚠️ Найдены ошибки конкурентного доступа (ожидаемо до исправления)")
            for i, err in enumerate(errors[:3], 1):
                print(f"      {i}. {err}")
    
    async def test_concurrent_mixed_operations(self):
        """
        Тест: одновременные вызовы разных методов (get_active_proxies и _update_redis_cache)
        должны вызывать ошибку конкурентного доступа, если блокировка не работает правильно.
        """
        proxy_manager, mock_session = await self._create_mock_proxy_manager()
        
        # Симулируем ситуацию, когда execute вызывается одновременно
        call_count = {'count': 0}
        lock = asyncio.Lock()
        
        async def mock_execute(*args, **kwargs):
            """Мок execute, который симулирует конкурентный доступ."""
            async with lock:
                call_count['count'] += 1
                current_count = call_count['count']
            
            # Если это не первый вызов, симулируем ошибку конкурентного доступа
            if current_count > 1:
                # Небольшая задержка, чтобы симулировать реальную ситуацию
                await asyncio.sleep(0.01)
                from sqlalchemy.exc import InterfaceError
                from asyncpg.exceptions import InterfaceError as AsyncPGInterfaceError
                raise InterfaceError(
                    "cannot perform operation: another operation is in progress",
                    orig=AsyncPGInterfaceError("cannot perform operation: another operation is in progress")
                )
            # Первый вызов успешен
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result
        
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        
        # Вызываем разные методы одновременно
        async def call_get_active():
            try:
                await proxy_manager.get_active_proxies(force_refresh=True)
                return "get_active: success"
            except Exception as e:
                return f"get_active: error: {type(e).__name__}: {str(e)[:100]}"
        
        async def call_update_cache():
            try:
                await proxy_manager._update_redis_cache()
                return "update_cache: success"
            except Exception as e:
                return f"update_cache: error: {type(e).__name__}: {str(e)[:100]}"
        
        # Запускаем смешанные вызовы
        tasks = []
        for i in range(5):
            tasks.append(call_get_active())
            tasks.append(call_update_cache())
        
        results = await asyncio.gather(*tasks)
        
        # Проверяем, что были ошибки конкурентного доступа
        errors = [r for r in results if "error" in r and "InterfaceError" in r]
        
        print(f"\n📊 Результаты теста concurrent_mixed_operations:")
        print(f"   Всего вызовов: {len(results)}")
        print(f"   Ошибок: {len(errors)}")
        print(f"   Успешных: {len([r for r in results if 'success' in r])}")
        
        if errors:
            print(f"   ⚠️ Найдены ошибки конкурентного доступа (ожидаемо до исправления)")
            for i, err in enumerate(errors[:3], 1):
                print(f"      {i}. {err}")
    
    def run_async_test(self, coro):
        """Запускает асинхронный тест."""
        return self.loop.run_until_complete(coro)
    
    def test_concurrent_get_active_proxies_sync(self):
        """Синхронная обертка для test_concurrent_get_active_proxies."""
        self.run_async_test(self.test_concurrent_get_active_proxies())
    
    def test_concurrent_update_redis_cache_sync(self):
        """Синхронная обертка для test_concurrent_update_redis_cache."""
        self.run_async_test(self.test_concurrent_update_redis_cache())
    
    def test_concurrent_mixed_operations_sync(self):
        """Синхронная обертка для test_concurrent_mixed_operations."""
        self.run_async_test(self.test_concurrent_mixed_operations())


if __name__ == '__main__':
    unittest.main()
