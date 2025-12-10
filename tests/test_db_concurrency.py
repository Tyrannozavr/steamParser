#!/usr/bin/env python3
"""
Тесты для выявления ошибок конкурентного доступа к БД.

Эти тесты проверяют, что методы ProxyManager правильно используют блокировки
при работе с БД, чтобы избежать ошибок "concurrent operations are not permitted".
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


class TestDBConcurrency(unittest.TestCase):
    """Тесты конкурентного доступа к БД."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        # Создаем моки для БД сессии
        self.mock_db_session = AsyncMock()
        self.mock_db_session.execute = AsyncMock()
        self.mock_db_session.commit = AsyncMock()
        self.mock_db_session.rollback = AsyncMock()
        
        # Создаем моки для Redis
        self.mock_redis_service = MagicMock()
        self.mock_redis_service._client = AsyncMock()
        self.mock_redis_service.is_connected = MagicMock(return_value=True)
        self.mock_redis_service.get = AsyncMock(return_value=None)
        
        # Импортируем ProxyManager
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        
        from services.proxy_manager import ProxyManager
        self.ProxyManager = ProxyManager
    
    async def _create_proxy_manager(self):
        """Создает экземпляр ProxyManager с моками."""
        manager = self.ProxyManager(
            db_session=self.mock_db_session,
            redis_service=self.mock_redis_service,
            default_delay=0.2
        )
        return manager
    
    async def test_concurrent_update_redis_cache(self):
        """
        Тест 1: Конкурентные вызовы _update_redis_cache().
        
        Проблема: Если _update_redis_cache() вызывается из нескольких корутин
        одновременно без блокировки, возникает ошибка "concurrent operations are not permitted".
        
        Ожидается: Метод должен использовать _db_lock для защиты операций с БД.
        """
        manager = await self._create_proxy_manager()
        
        # Настраиваем мок для возврата прокси
        mock_proxy = MagicMock()
        mock_proxy.id = 1
        mock_proxy.url = "http://proxy1:8080"
        mock_proxy.is_active = True
        mock_proxy.delay_seconds = 0.2
        mock_proxy.success_count = 0
        mock_proxy.fail_count = 0
        mock_proxy.last_used = None
        mock_proxy.last_error = None
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_proxy]
        self.mock_db_session.execute.return_value = mock_result
        
        # Симулируем конкурентные вызовы
        async def call_update_cache():
            try:
                await manager._update_redis_cache()
                return "success"
            except Exception as e:
                return f"error: {str(e)}"
        
        # Запускаем 10 параллельных вызовов
        tasks = [call_update_cache() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Проверяем, что все вызовы завершились успешно
        errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
        
        # Если есть ошибки конкурентного доступа - это проблема
        concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
        
        if concurrent_errors:
            print(f"❌ ТЕСТ 1 ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
            assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
        else:
            print(f"✅ ТЕСТ 1 ПРОЙДЕН: Нет ошибок конкурентного доступа при параллельных вызовах _update_redis_cache()")
            assert True
    
    async def test_concurrent_get_active_proxies(self):
        """
        Тест 2: Конкурентные вызовы get_active_proxies().
        
        Проблема: Если get_active_proxies() вызывается из нескольких корутин
        одновременно без блокировки для БД операций, возникает ошибка.
        
        Ожидается: Метод должен использовать _db_lock для защиты операций с БД.
        """
        manager = await self._create_proxy_manager()
        
        # Настраиваем мок для возврата прокси
        mock_proxy = MagicMock()
        mock_proxy.id = 1
        mock_proxy.url = "http://proxy1:8080"
        mock_proxy.is_active = True
        mock_proxy.delay_seconds = 0.2
        mock_proxy.success_count = 0
        mock_proxy.fail_count = 0
        mock_proxy.last_used = None
        mock_proxy.last_error = None
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_proxy]
        self.mock_db_session.execute.return_value = mock_result
        
        # Симулируем конкурентные вызовы с force_refresh=True (обращение к БД)
        async def call_get_active_proxies():
            try:
                await manager.get_active_proxies(force_refresh=True)
                return "success"
            except Exception as e:
                return f"error: {str(e)}"
        
        # Запускаем 10 параллельных вызовов
        tasks = [call_get_active_proxies() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Проверяем, что все вызовы завершились успешно
        errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
        
        # Если есть ошибки конкурентного доступа - это проблема
        concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
        
        if concurrent_errors:
            print(f"❌ ТЕСТ 2 ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
            assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
        else:
            print(f"✅ ТЕСТ 2 ПРОЙДЕН: Нет ошибок конкурентного доступа при параллельных вызовах get_active_proxies()")
            assert True
    
    async def test_concurrent_is_proxy_blocked(self):
        """
        Тест 3: Конкурентные вызовы _is_proxy_temporarily_blocked().
        
        Проблема: Если _is_proxy_temporarily_blocked() вызывается из нескольких корутин
        одновременно без блокировки, возникает ошибка.
        
        Ожидается: Метод должен использовать _db_lock для защиты операций с БД.
        """
        manager = await self._create_proxy_manager()
        
        # Настраиваем мок для возврата прокси
        mock_proxy = MagicMock()
        mock_proxy.id = 1
        mock_proxy.blocked_until = None
        mock_proxy.fail_count = 0
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_proxy
        self.mock_db_session.execute.return_value = mock_result
        
        # Симулируем конкурентные вызовы
        async def call_is_blocked():
            try:
                result = await manager._is_proxy_temporarily_blocked(1)
                return f"success: {result}"
            except Exception as e:
                return f"error: {str(e)}"
        
        # Запускаем 10 параллельных вызовов
        tasks = [call_is_blocked() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Проверяем, что все вызовы завершились успешно
        errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
        
        # Если есть ошибки конкурентного доступа - это проблема
        concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
        
        if concurrent_errors:
            print(f"❌ ТЕСТ 3 ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
            assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
        else:
            print(f"✅ ТЕСТ 3 ПРОЙДЕН: Нет ошибок конкурентного доступа при параллельных вызовах _is_proxy_temporarily_blocked()")
            assert True
    
    async def test_concurrent_block_unblock_proxy(self):
        """
        Тест 4: Конкурентные вызовы _block_proxy_temporarily() и _unblock_proxy().
        
        Проблема: Если блокировка/разблокировка прокси вызывается из нескольких корутин
        одновременно без блокировки, возникает ошибка.
        
        Ожидается: Методы должны использовать _db_lock для защиты операций с БД.
        """
        manager = await self._create_proxy_manager()
        
        # Настраиваем мок для возврата прокси
        mock_proxy = MagicMock()
        mock_proxy.id = 1
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_proxy
        self.mock_db_session.execute.return_value = mock_result
        
        # Симулируем конкурентные вызовы блокировки и разблокировки
        async def call_block():
            try:
                await manager._block_proxy_temporarily(1, 600)
                return "blocked"
            except Exception as e:
                return f"error: {str(e)}"
        
        async def call_unblock():
            try:
                await manager._unblock_proxy(1)
                return "unblocked"
            except Exception as e:
                return f"error: {str(e)}"
        
        # Запускаем параллельные вызовы блокировки и разблокировки
        tasks = []
        for i in range(5):
            tasks.append(call_block())
            tasks.append(call_unblock())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Проверяем, что все вызовы завершились успешно
        errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
        
        # Если есть ошибки конкурентного доступа - это проблема
        concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
        
        if concurrent_errors:
            print(f"❌ ТЕСТ 4 ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
            assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
        else:
            print(f"✅ ТЕСТ 4 ПРОЙДЕН: Нет ошибок конкурентного доступа при параллельных вызовах блокировки/разблокировки")
            assert True
    
    async def test_concurrent_mixed_operations(self):
        """
        Тест 5: Смешанные конкурентные операции с БД.
        
        Проблема: Если разные методы, использующие БД, вызываются параллельно
        без правильных блокировок, возникает ошибка.
        
        Ожидается: Все методы должны использовать _db_lock для защиты операций с БД.
        """
        manager = await self._create_proxy_manager()
        
        # Настраиваем моки
        mock_proxy = MagicMock()
        mock_proxy.id = 1
        mock_proxy.url = "http://proxy1:8080"
        mock_proxy.is_active = True
        mock_proxy.blocked_until = None
        mock_proxy.fail_count = 0
        
        mock_result_list = MagicMock()
        mock_result_list.scalars.return_value.all.return_value = [mock_proxy]
        
        mock_result_one = MagicMock()
        mock_result_one.scalar_one_or_none.return_value = mock_proxy
        
        # Чередуем результаты для разных методов
        call_count = [0]
        def execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return mock_result_list
            else:
                return mock_result_one
        
        self.mock_db_session.execute.side_effect = execute_side_effect
        
        # Симулируем смешанные конкурентные вызовы
        async def call_mixed():
            try:
                # Вызываем разные методы
                await manager._update_redis_cache()
                await manager.get_active_proxies(force_refresh=True)
                await manager._is_proxy_temporarily_blocked(1)
                return "success"
            except Exception as e:
                return f"error: {str(e)}"
        
        # Запускаем 10 параллельных вызовов
        tasks = [call_mixed() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Проверяем, что все вызовы завершились успешно
        errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
        
        # Если есть ошибки конкурентного доступа - это проблема
        concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
        
        if concurrent_errors:
            print(f"❌ ТЕСТ 5 ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
            assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
        else:
            print(f"✅ ТЕСТ 5 ПРОЙДЕН: Нет ошибок конкурентного доступа при смешанных операциях")
            assert True


async def run_tests():
    """Запускает все тесты."""
    print("=" * 80)
    print("🧪 ЗАПУСК ТЕСТОВ КОНКУРЕНТНОГО ДОСТУПА К БД")
    print("=" * 80)
    print()
    
    test_suite = TestDBConcurrency()
    test_suite.setUp()
    
    tests = [
        ("Тест 1: Конкурентные вызовы _update_redis_cache()", test_suite.test_concurrent_update_redis_cache),
        ("Тест 2: Конкурентные вызовы get_active_proxies()", test_suite.test_concurrent_get_active_proxies),
        ("Тест 3: Конкурентные вызовы _is_proxy_temporarily_blocked()", test_suite.test_concurrent_is_proxy_blocked),
        ("Тест 4: Конкурентные вызовы блокировки/разблокировки", test_suite.test_concurrent_block_unblock_proxy),
        ("Тест 5: Смешанные конкурентные операции", test_suite.test_concurrent_mixed_operations),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n📋 {test_name}")
        print("-" * 80)
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"❌ ПРОВАЛЕН: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print()
    print("=" * 80)
    print(f"📊 РЕЗУЛЬТАТЫ: {passed} пройдено, {failed} провалено")
    if failed == 0:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ - конкурентный доступ к БД защищен правильно!")
    else:
        print("❌ ЕСТЬ ПРОВАЛЕННЫЕ ТЕСТЫ - нужно проверить блокировки в коде!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_tests())
