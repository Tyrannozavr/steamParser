#!/usr/bin/env python3
"""
Тесты для проверки кода на наличие незащищенных операций с БД.

Эти тесты анализируют исходный код и проверяют, что все методы,
использующие db_session.execute(), защищены блокировкой _db_lock.
"""
import re
import ast
from pathlib import Path


def find_db_operations_in_file(file_path: str):
    """
    Находит все операции с БД в файле.
    
    Returns:
        List[dict]: Список найденных операций с информацией о строке и контексте
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
    
    operations = []
    
    # Ищем паттерны использования БД
    patterns = [
        (r'self\.db_session\.execute\s*\(', 'db_session.execute'),
        (r'self\.db_session\.commit\s*\(', 'db_session.commit'),
        (r'self\.db_session\.rollback\s*\(', 'db_session.rollback'),
    ]
    
    for line_num, line in enumerate(lines, 1):
        for pattern, operation_type in patterns:
            if re.search(pattern, line):
                # Проверяем, есть ли блокировка _db_lock в контексте
                context_start = max(0, line_num - 20)
                context_end = min(len(lines), line_num + 5)
                context = '\n'.join(lines[context_start:context_end])
                
                # Проверяем наличие блокировки в контексте
                has_lock = 'async with self._db_lock' in context or 'async with self._lock' in context
                
                operations.append({
                    'line': line_num,
                    'operation': operation_type,
                    'code': line.strip(),
                    'has_lock': has_lock,
                    'context': context
                })
    
    return operations


def check_proxy_manager_db_operations():
    """
    Проверяет proxy_manager.py на наличие незащищенных операций с БД.
    """
    print("=" * 80)
    print("🔍 ПРОВЕРКА КОДА НА НЕЗАЩИЩЕННЫЕ ОПЕРАЦИИ С БД")
    print("=" * 80)
    print()
    
    file_path = Path(__file__).parent.parent / "services" / "proxy_manager.py"
    
    if not file_path.exists():
        print(f"❌ Файл не найден: {file_path}")
        return
    
    print(f"📁 Проверяем файл: {file_path}")
    print()
    
    operations = find_db_operations_in_file(str(file_path))
    
    # Группируем по наличию блокировки
    protected = [op for op in operations if op['has_lock']]
    unprotected = [op for op in operations if not op['has_lock']]
    
    print(f"📊 Найдено операций с БД: {len(operations)}")
    print(f"   ✅ Защищенных блокировкой: {len(protected)}")
    print(f"   ⚠️  Незащищенных: {len(unprotected)}")
    print()
    
    if unprotected:
        print("⚠️  НАЙДЕНЫ НЕЗАЩИЩЕННЫЕ ОПЕРАЦИИ С БД:")
        print("-" * 80)
        for op in unprotected:
            print(f"   Строка {op['line']}: {op['operation']}")
            print(f"   Код: {op['code'][:80]}")
            print(f"   Контекст (первые 200 символов):")
            print(f"   {op['context'][:200]}...")
            print()
        
        print("💡 РЕКОМЕНДАЦИЯ: Добавьте 'async with self._db_lock:' перед этими операциями")
        print()
        return False
    else:
        print("✅ ВСЕ ОПЕРАЦИИ С БД ЗАЩИЩЕНЫ БЛОКИРОВКОЙ!")
        print()
        return True


def check_all_service_files():
    """
    Проверяет все файлы в services/ на наличие незащищенных операций с БД.
    """
    print("=" * 80)
    print("🔍 ПРОВЕРКА ВСЕХ ФАЙЛОВ В services/ НА НЕЗАЩИЩЕННЫЕ ОПЕРАЦИИ С БД")
    print("=" * 80)
    print()
    
    services_dir = Path(__file__).parent.parent / "services"
    
    if not services_dir.exists():
        print(f"❌ Директория не найдена: {services_dir}")
        return
    
    all_unprotected = []
    
    for file_path in services_dir.glob("*.py"):
        if file_path.name == "__init__.py":
            continue
        
        operations = find_db_operations_in_file(str(file_path))
        unprotected = [op for op in operations if not op['has_lock']]
        
        if unprotected:
            all_unprotected.append({
                'file': file_path.name,
                'operations': unprotected
            })
    
    if all_unprotected:
        print("⚠️  НАЙДЕНЫ ФАЙЛЫ С НЕЗАЩИЩЕННЫМИ ОПЕРАЦИЯМИ С БД:")
        print("-" * 80)
        for file_info in all_unprotected:
            print(f"📁 {file_info['file']}: {len(file_info['operations'])} незащищенных операций")
            for op in file_info['operations'][:3]:  # Показываем первые 3
                print(f"   Строка {op['line']}: {op['operation']}")
            if len(file_info['operations']) > 3:
                print(f"   ... и еще {len(file_info['operations']) - 3}")
            print()
        
        return False
    else:
        print("✅ ВО ВСЕХ ФАЙЛАХ ОПЕРАЦИИ С БД ЗАЩИЩЕНЫ БЛОКИРОВКОЙ!")
        print()
        return True


def main():
    """Запускает все проверки."""
    print()
    
    # Проверка 1: proxy_manager.py
    result1 = check_proxy_manager_db_operations()
    
    # Проверка 2: Все файлы в services/
    result2 = check_all_service_files()
    
    print("=" * 80)
    if result1 and result2:
        print("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - код защищен от конкурентного доступа!")
    else:
        print("⚠️  НАЙДЕНЫ ПРОБЛЕМЫ - нужно добавить блокировки в указанных местах")
    print("=" * 80)
    print()
    print("💡 Эти проверки помогают:")
    print("   1. Найти места, где операции с БД не защищены блокировкой")
    print("   2. Предотвратить появление новых ошибок конкурентного доступа")
    print("   3. Убедиться, что все исправления применены")
    print()


if __name__ == "__main__":
    main()
