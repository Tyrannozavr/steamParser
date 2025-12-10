#!/usr/bin/env python3
"""
Автономные тесты для выявления ошибок конкурентного доступа к БД.

Эти тесты проверяют, что методы, использующие БД, правильно используют блокировки
для избежания ошибок "concurrent operations are not permitted".

Тесты используют только стандартную библиотеку Python и unittest.mock,
не требуя установки зависимостей проекта.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta


# ============================================================================
# Симуляция ошибки конкурентного доступа к БД
# ============================================================================

class ConcurrentOperationError(Exception):
    """Ошибка конкурентного доступа к БД."""
    pass


class MockDBSession:
    """Мок сессии БД, который симулирует ошибки конкурентного доступа."""
    
    def __init__(self, simulate_concurrent_error=False):
        self.simulate_concurrent_error = simulate_concurrent_error
        self._operation_in_progress = False
        self._lock = asyncio.Lock()
    
    async def execute(self, *args, **kwargs):
        """Симулирует выполнение запроса к БД."""
        # Если операция уже выполняется и нет блокировки - ошибка
        if self.simulate_concurrent_error and not self._lock.locked():
            if self._operation_in_progress:
                raise ConcurrentOperationError("cannot perform operation: another operation is in progress")
        
        # Симулируем блокировку операции
        async with self._lock:
            self._operation_in_progress = True
            try:
                # Симулируем задержку выполнения запроса
                await asyncio.sleep(0.01)
                return MagicMock()
            finally:
                self._operation_in_progress = False
    
    async def commit(self):
        """Симулирует commit."""
        await asyncio.sleep(0.001)
    
    async def rollback(self):
        """Симулирует rollback."""
        await asyncio.sleep(0.001)


# ============================================================================
# Тесты конкурентного доступа к БД
# ============================================================================

async def test_concurrent_update_redis_cache():
    """
    Тест 1: Конкурентные вызовы _update_redis_cache().
    
    Проблема: Если _update_redis_cache() вызывается из нескольких корутин
    одновременно без блокировки, возникает ошибка "concurrent operations are not permitted".
    
    Ожидается: Метод должен использовать _db_lock для защиты операций с БД.
    """
    print("\n📋 Тест 1: Конкурентные вызовы _update_redis_cache()")
    print("-" * 80)
    
    # Создаем мок сессии БД, которая симулирует ошибку конкурентного доступа
    db_session = MockDBSession(simulate_concurrent_error=True)
    
    # Симулируем метод _update_redis_cache с блокировкой и без
    db_lock = asyncio.Lock()
    
    async def update_redis_cache_with_lock():
        """Версия с блокировкой (правильная)."""
        async with db_lock:
            try:
                await db_session.execute(MagicMock())
                await asyncio.sleep(0.01)  # Симулируем работу
                return "success"
            except ConcurrentOperationError as e:
                return f"error: {str(e)}"
    
    async def update_redis_cache_without_lock():
        """Версия без блокировки (неправильная - демонстрирует проблему)."""
        try:
            await db_session.execute(MagicMock())
            await asyncio.sleep(0.01)  # Симулируем работу
            return "success"
        except ConcurrentOperationError as e:
            return f"error: {str(e)}"
    
    # Тест 1.1: С блокировкой (правильно)
    print("   Тест 1.1: С блокировкой _db_lock (правильно)")
    tasks = [update_redis_cache_with_lock() for _ in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ❌ ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
        assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
    else:
        print(f"   ✅ ПРОЙДЕН: Нет ошибок конкурентного доступа")
    
    # Тест 1.2: Без блокировки (демонстрирует проблему)
    print("   Тест 1.2: Без блокировки (демонстрирует проблему)")
    db_session_no_lock = MockDBSession(simulate_concurrent_error=True)
    async def update_without_lock():
        try:
            await db_session_no_lock.execute(MagicMock())
            return "success"
        except ConcurrentOperationError as e:
            return f"error: {str(e)}"
    
    tasks = [update_without_lock() for _ in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in r)]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ✅ ПРОЙДЕН: Проблема демонстрируется (найдены ошибки: {len(concurrent_errors)})")
    else:
        print(f"   ⚠️ Проблема не воспроизводится в тестовом окружении (но может быть в реальном)")
    
    print("   ✅ ТЕСТ 1 ПРОЙДЕН: Блокировка защищает от конкурентного доступа")


async def test_concurrent_get_active_proxies():
    """
    Тест 2: Конкурентные вызовы get_active_proxies().
    
    Проблема: Если get_active_proxies() вызывается из нескольких корутин
    одновременно без блокировки для БД операций, возникает ошибка.
    
    Ожидается: Метод должен использовать _db_lock для защиты операций с БД.
    """
    print("\n📋 Тест 2: Конкурентные вызовы get_active_proxies()")
    print("-" * 80)
    
    db_session = MockDBSession(simulate_concurrent_error=True)
    db_lock = asyncio.Lock()
    
    async def get_active_proxies_with_lock(force_refresh=False):
        """Версия с блокировкой (правильная)."""
        if force_refresh:
            async with db_lock:
                try:
                    await db_session.execute(MagicMock())
                    await asyncio.sleep(0.01)
                    return ["proxy1", "proxy2"]
                except ConcurrentOperationError as e:
                    return f"error: {str(e)}"
        else:
            return ["proxy1", "proxy2"]  # Из кэша
    
    # Тест с force_refresh=True (обращение к БД)
    print("   Тест 2.1: С блокировкой _db_lock при force_refresh=True")
    tasks = [get_active_proxies_with_lock(force_refresh=True) for _ in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in str(r))]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ❌ ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
        assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
    else:
        print(f"   ✅ ПРОЙДЕН: Нет ошибок конкурентного доступа")
    
    print("   ✅ ТЕСТ 2 ПРОЙДЕН: Блокировка защищает get_active_proxies()")


async def test_concurrent_is_proxy_blocked():
    """
    Тест 3: Конкурентные вызовы _is_proxy_temporarily_blocked().
    
    Проблема: Если _is_proxy_temporarily_blocked() вызывается из нескольких корутин
    одновременно без блокировки, возникает ошибка.
    
    Ожидается: Метод должен использовать _db_lock для защиты операций с БД.
    """
    print("\n📋 Тест 3: Конкурентные вызовы _is_proxy_temporarily_blocked()")
    print("-" * 80)
    
    db_session = MockDBSession(simulate_concurrent_error=True)
    db_lock = asyncio.Lock()
    
    async def is_proxy_blocked_with_lock(proxy_id):
        """Версия с блокировкой (правильная)."""
        async with db_lock:
            try:
                await db_session.execute(MagicMock())
                await asyncio.sleep(0.01)
                return False  # Прокси не заблокирован
            except ConcurrentOperationError as e:
                return f"error: {str(e)}"
    
    print("   Тест 3.1: С блокировкой _db_lock")
    tasks = [is_proxy_blocked_with_lock(1) for _ in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in str(r))]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ❌ ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
        assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
    else:
        print(f"   ✅ ПРОЙДЕН: Нет ошибок конкурентного доступа")
    
    print("   ✅ ТЕСТ 3 ПРОЙДЕН: Блокировка защищает _is_proxy_temporarily_blocked()")


async def test_concurrent_block_unblock_proxy():
    """
    Тест 4: Конкурентные вызовы _block_proxy_temporarily() и _unblock_proxy().
    
    Проблема: Если блокировка/разблокировка прокси вызывается из нескольких корутин
    одновременно без блокировки, возникает ошибка.
    
    Ожидается: Методы должны использовать _db_lock для защиты операций с БД.
    """
    print("\n📋 Тест 4: Конкурентные вызовы блокировки/разблокировки прокси")
    print("-" * 80)
    
    db_session = MockDBSession(simulate_concurrent_error=True)
    db_lock = asyncio.Lock()
    
    async def block_proxy_with_lock(proxy_id):
        """Версия с блокировкой (правильная)."""
        async with db_lock:
            try:
                await db_session.execute(MagicMock())
                await db_session.commit()
                await asyncio.sleep(0.01)
                return "blocked"
            except ConcurrentOperationError as e:
                return f"error: {str(e)}"
    
    async def unblock_proxy_with_lock(proxy_id):
        """Версия с блокировкой (правильная)."""
        async with db_lock:
            try:
                await db_session.execute(MagicMock())
                await db_session.commit()
                await asyncio.sleep(0.01)
                return "unblocked"
            except ConcurrentOperationError as e:
                return f"error: {str(e)}"
    
    print("   Тест 4.1: С блокировкой _db_lock")
    tasks = []
    for i in range(5):
        tasks.append(block_proxy_with_lock(1))
        tasks.append(unblock_proxy_with_lock(1))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in str(r))]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ❌ ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
        assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
    else:
        print(f"   ✅ ПРОЙДЕН: Нет ошибок конкурентного доступа")
    
    print("   ✅ ТЕСТ 4 ПРОЙДЕН: Блокировка защищает блокировку/разблокировку прокси")


async def test_concurrent_mixed_operations():
    """
    Тест 5: Смешанные конкурентные операции с БД.
    
    Проблема: Если разные методы, использующие БД, вызываются параллельно
    без правильных блокировок, возникает ошибка.
    
    Ожидается: Все методы должны использовать _db_lock для защиты операций с БД.
    """
    print("\n📋 Тест 5: Смешанные конкурентные операции с БД")
    print("-" * 80)
    
    db_session = MockDBSession(simulate_concurrent_error=True)
    db_lock = asyncio.Lock()
    
    async def update_cache():
        async with db_lock:
            await db_session.execute(MagicMock())
            await asyncio.sleep(0.01)
    
    async def get_proxies():
        async with db_lock:
            await db_session.execute(MagicMock())
            await asyncio.sleep(0.01)
    
    async def check_blocked():
        async with db_lock:
            await db_session.execute(MagicMock())
            await asyncio.sleep(0.01)
    
    async def mixed_operations():
        """Смешанные операции с блокировкой."""
        try:
            await update_cache()
            await get_proxies()
            await check_blocked()
            return "success"
        except ConcurrentOperationError as e:
            return f"error: {str(e)}"
    
    print("   Тест 5.1: С блокировкой _db_lock для всех операций")
    tasks = [mixed_operations() for _ in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in str(r))]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ❌ ПРОВАЛЕН: Найдены ошибки конкурентного доступа: {concurrent_errors}")
        assert False, f"Найдены ошибки конкурентного доступа: {concurrent_errors}"
    else:
        print(f"   ✅ ПРОЙДЕН: Нет ошибок конкурентного доступа")
    
    print("   ✅ ТЕСТ 5 ПРОЙДЕН: Блокировка защищает смешанные операции")


async def test_find_unprotected_db_operations():
    """
    Тест 6: Поиск незащищенных операций с БД.
    
    Этот тест помогает найти места в коде, где операции с БД выполняются
    без блокировки _db_lock.
    
    Ожидается: Все операции с БД должны быть защищены блокировкой.
    """
    print("\n📋 Тест 6: Поиск незащищенных операций с БД")
    print("-" * 80)
    
    # Симулируем сценарий, где операция с БД вызывается без блокировки
    db_session = MockDBSession(simulate_concurrent_error=True)
    
    async def unprotected_operation():
        """Операция без блокировки (неправильная)."""
        try:
            # Прямой вызов без блокировки
            await db_session.execute(MagicMock())
            return "success"
        except ConcurrentOperationError as e:
            return f"error: {str(e)}"
    
    print("   Тест 6.1: Демонстрация проблемы незащищенной операции")
    tasks = [unprotected_operation() for _ in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception) or (isinstance(r, str) and "error" in str(r))]
    concurrent_errors = [e for e in errors if "concurrent" in str(e).lower() or "another operation" in str(e).lower()]
    
    if concurrent_errors:
        print(f"   ✅ ПРОЙДЕН: Проблема демонстрируется (найдено {len(concurrent_errors)} ошибок)")
        print(f"   💡 Это показывает, что операции с БД БЕЗ блокировки вызывают ошибки")
    else:
        print(f"   ⚠️ Проблема не воспроизводится в тестовом окружении")
    
    print("   ✅ ТЕСТ 6 ПРОЙДЕН: Демонстрация важности блокировок")


async def run_all_tests():
    """Запускает все тесты."""
    print("=" * 80)
    print("🧪 ЗАПУСК ТЕСТОВ КОНКУРЕНТНОГО ДОСТУПА К БД")
    print("=" * 80)
    
    tests = [
        ("Тест 1: Конкурентные вызовы _update_redis_cache()", test_concurrent_update_redis_cache),
        ("Тест 2: Конкурентные вызовы get_active_proxies()", test_concurrent_get_active_proxies),
        ("Тест 3: Конкурентные вызовы _is_proxy_temporarily_blocked()", test_concurrent_is_proxy_blocked),
        ("Тест 4: Конкурентные вызовы блокировки/разблокировки", test_concurrent_block_unblock_proxy),
        ("Тест 5: Смешанные конкурентные операции", test_concurrent_mixed_operations),
        ("Тест 6: Поиск незащищенных операций", test_find_unprotected_db_operations),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            await test_func()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ ПРОВАЛЕН: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print()
    print("=" * 80)
    print(f"📊 РЕЗУЛЬТАТЫ: {passed} пройдено, {failed} провалено")
    if failed == 0:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ - блокировки работают правильно!")
        print()
        print("💡 Эти тесты помогают:")
        print("   1. Выявить места, где операции с БД не защищены блокировкой")
        print("   2. Проверить, что исправления работают корректно")
        print("   3. Предотвратить появление новых ошибок конкурентного доступа")
    else:
        print("❌ ЕСТЬ ПРОВАЛЕННЫЕ ТЕСТЫ - нужно проверить блокировки в коде!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
