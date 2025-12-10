"""
Скрипт для запуска тестов воспроизведения проблем без pytest.
Проверяет, что тесты корректно демонстрируют проблемы.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from test_problems_reproduction import (
    test_problem_1_massive_429_errors,
    test_problem_2_stuck_parsing_tasks,
    test_problem_3_proxy_acquisition_timeout,
    test_problem_4_concurrent_db_access_errors,
    test_problem_5_http_request_timeouts,
    test_problem_6_redis_service_get_attribute_error,
    test_problem_7_cascade_degradation,
    test_problem_8_long_running_heartbeat,
)


async def run_all_tests():
    """Запускает все тесты и выводит результаты."""
    tests = [
        ("Проблема 1: Массовые 429 ошибки", test_problem_1_massive_429_errors),
        ("Проблема 2: Зависшие задачи парсинга", test_problem_2_stuck_parsing_tasks),
        ("Проблема 3: Таймауты при получении прокси", test_problem_3_proxy_acquisition_timeout),
        ("Проблема 4: Ошибки конкурентного доступа к БД", test_problem_4_concurrent_db_access_errors),
        ("Проблема 5: Таймауты HTTP-запросов", test_problem_5_http_request_timeouts),
        ("Проблема 6: Проблемы с Redis Service", test_problem_6_redis_service_get_attribute_error),
        ("Проблема 7: Каскадный эффект", test_problem_7_cascade_degradation),
        ("Проблема 8: Heartbeat сообщения", test_problem_8_long_running_heartbeat),
    ]
    
    print("=" * 80)
    print("🧪 ЗАПУСК ТЕСТОВ ВОСПРОИЗВЕДЕНИЯ ПРОБЛЕМ")
    print("=" * 80)
    print()
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"📋 Тест: {name}")
        try:
            await test_func()
            print(f"   ✅ ПРОЙДЕН - проблема демонстрируется")
            passed += 1
        except AssertionError as e:
            print(f"   ❌ ПРОВАЛЕН: {e}")
            failed += 1
        except Exception as e:
            print(f"   ❌ ОШИБКА: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()
    
    print("=" * 80)
    print(f"📊 РЕЗУЛЬТАТЫ: {passed} пройдено, {failed} провалено")
    print("=" * 80)
    
    if failed == 0:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ - все проблемы корректно демонстрируются")
        return 0
    else:
        print("❌ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ - требуется исправление")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
