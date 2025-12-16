#!/usr/bin/env python3
"""
Скрипт для мониторинга состояния БД и сессий.

Показывает:
- Активные соединения
- Долгие запросы
- Блокировки
- Состояние транзакций
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from loguru import logger
import asyncpg

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


async def check_active_connections():
    """Проверяет активные соединения к БД."""
    print("=" * 80)
    print("📊 АКТИВНЫЕ СОЕДИНЕНИЯ К БД")
    print("=" * 80)
    
    # Парсим DATABASE_URL
    db_url = Config.DATABASE_URL
    # Формат: postgresql+asyncpg://user:pass@host:port/db
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    from urllib.parse import urlparse
    parsed = urlparse(db_url)
    
    conn = await asyncpg.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "steam_user",
        password=parsed.password or "steam_password",
        database=parsed.path.lstrip("/") or "steam_monitor"
    )
    
    try:
        # Активные соединения
        rows = await conn.fetch("""
            SELECT 
                pid,
                usename,
                application_name,
                client_addr,
                state,
                query_start,
                state_change,
                wait_event_type,
                wait_event,
                query
            FROM pg_stat_activity
            WHERE datname = current_database()
            AND pid != pg_backend_pid()
            ORDER BY query_start DESC NULLS LAST
        """)
        
        print(f"\n✅ Найдено активных соединений: {len(rows)}\n")
        
        for row in rows:
            print(f"PID: {row['pid']}")
            print(f"  Пользователь: {row['usename']}")
            print(f"  Приложение: {row['application_name']}")
            print(f"  Адрес: {row['client_addr']}")
            print(f"  Состояние: {row['state']}")
            if row['query_start']:
                duration = (datetime.now() - row['query_start']).total_seconds()
                print(f"  Длительность запроса: {duration:.2f} сек")
            if row['wait_event_type']:
                print(f"  Ожидание: {row['wait_event_type']} - {row['wait_event']}")
            if row['query']:
                query_preview = row['query'][:100].replace('\n', ' ')
                print(f"  Запрос: {query_preview}...")
            print()
        
        # Долгие запросы (>5 секунд)
        long_queries = [r for r in rows if r['query_start'] and (datetime.now() - r['query_start']).total_seconds() > 5]
        if long_queries:
            print(f"\n⚠️  ДОЛГИЕ ЗАПРОСЫ (>5 сек): {len(long_queries)}")
            for row in long_queries:
                duration = (datetime.now() - row['query_start']).total_seconds()
                print(f"  PID {row['pid']}: {duration:.2f} сек - {row['query'][:80]}")
        
    finally:
        await conn.close()


async def check_locks():
    """Проверяет блокировки в БД."""
    print("\n" + "=" * 80)
    print("🔒 БЛОКИРОВКИ В БД")
    print("=" * 80)
    
    db_url = Config.DATABASE_URL
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    from urllib.parse import urlparse
    parsed = urlparse(db_url)
    
    conn = await asyncpg.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "steam_user",
        password=parsed.password or "steam_password",
        database=parsed.path.lstrip("/") or "steam_monitor"
    )
    
    try:
        # Блокировки
        rows = await conn.fetch("""
            SELECT 
                l.locktype,
                l.database,
                l.relation::regclass,
                l.page,
                l.tuple,
                l.virtualxid,
                l.transactionid,
                l.classid,
                l.objid,
                l.objsubid,
                l.virtualtransaction,
                l.pid,
                l.mode,
                l.granted,
                a.usename,
                a.query,
                a.query_start,
                age(now(), a.query_start) AS age
            FROM pg_locks l
            LEFT JOIN pg_stat_activity a ON l.pid = a.pid
            WHERE l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
            ORDER BY a.query_start
        """)
        
        if not rows:
            print("✅ Блокировок не обнаружено")
        else:
            print(f"\n⚠️  Найдено блокировок: {len(rows)}\n")
            
            for row in rows:
                print(f"PID: {row['pid']}")
                print(f"  Тип: {row['locktype']}")
                if row['relation']:
                    print(f"  Таблица: {row['relation']}")
                print(f"  Режим: {row['mode']}")
                print(f"  Предоставлена: {'✅' if row['granted'] else '❌'}")
                print(f"  Пользователь: {row['usename']}")
                if row['age']:
                    print(f"  Возраст: {row['age']}")
                if row['query']:
                    print(f"  Запрос: {row['query'][:80]}")
                print()
        
        # Deadlocks (если есть)
        deadlocks = await conn.fetch("""
            SELECT 
                pid,
                usename,
                query,
                state,
                wait_event_type,
                wait_event
            FROM pg_stat_activity
            WHERE datname = current_database()
            AND wait_event_type = 'Lock'
            AND state = 'active'
        """)
        
        if deadlocks:
            print(f"\n❌ ВОЗМОЖНЫЕ DEADLOCK'И: {len(deadlocks)}")
            for row in deadlocks:
                print(f"  PID {row['pid']}: ожидает блокировку - {row['query'][:80]}")
        
    finally:
        await conn.close()


async def check_transactions():
    """Проверяет состояние транзакций."""
    print("\n" + "=" * 80)
    print("💳 СОСТОЯНИЕ ТРАНЗАКЦИЙ")
    print("=" * 80)
    
    db_url = Config.DATABASE_URL
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    from urllib.parse import urlparse
    parsed = urlparse(db_url)
    
    conn = await asyncpg.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "steam_user",
        password=parsed.password or "steam_password",
        database=parsed.path.lstrip("/") or "steam_monitor"
    )
    
    try:
        # Долгие транзакции
        rows = await conn.fetch("""
            SELECT 
                pid,
                usename,
                application_name,
                state,
                xact_start,
                query_start,
                state_change,
                age(now(), xact_start) AS transaction_age,
                age(now(), query_start) AS query_age,
                query
            FROM pg_stat_activity
            WHERE datname = current_database()
            AND xact_start IS NOT NULL
            AND pid != pg_backend_pid()
            ORDER BY xact_start
        """)
        
        if not rows:
            print("✅ Активных транзакций не обнаружено")
        else:
            print(f"\n📋 Активных транзакций: {len(rows)}\n")
            
            for row in rows:
                print(f"PID: {row['pid']}")
                print(f"  Приложение: {row['application_name']}")
                print(f"  Состояние: {row['state']}")
                if row['transaction_age']:
                    age_seconds = row['transaction_age'].total_seconds()
                    print(f"  Возраст транзакции: {age_seconds:.2f} сек")
                if row['query_age']:
                    query_age_seconds = row['query_age'].total_seconds()
                    print(f"  Возраст запроса: {query_age_seconds:.2f} сек")
                if row['query']:
                    print(f"  Запрос: {row['query'][:100]}")
                print()
            
            # Долгие транзакции (>30 секунд)
            long_tx = [r for r in rows if r['transaction_age'] and r['transaction_age'].total_seconds() > 30]
            if long_tx:
                print(f"\n⚠️  ДОЛГИЕ ТРАНЗАКЦИИ (>30 сек): {len(long_tx)}")
                for row in long_tx:
                    age = row['transaction_age'].total_seconds()
                    print(f"  PID {row['pid']}: {age:.2f} сек - {row['query'][:80]}")
        
    finally:
        await conn.close()


async def check_table_stats():
    """Показывает статистику по таблицам."""
    print("\n" + "=" * 80)
    print("📊 СТАТИСТИКА ТАБЛИЦ")
    print("=" * 80)
    
    db_url = Config.DATABASE_URL
    if "+asyncpg" in db_url:
        db_url = db_url.replace("+asyncpg", "")
    
    from urllib.parse import urlparse
    parsed = urlparse(db_url)
    
    conn = await asyncpg.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=parsed.username or "steam_user",
        password=parsed.password or "steam_password",
        database=parsed.path.lstrip("/") or "steam_monitor"
    )
    
    try:
        # Статистика по monitoring_tasks
        rows = await conn.fetch("""
            SELECT 
                schemaname,
                tablename,
                n_tup_ins as inserts,
                n_tup_upd as updates,
                n_tup_del as deletes,
                n_live_tup as live_tuples,
                n_dead_tup as dead_tuples,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze
            FROM pg_stat_user_tables
            WHERE tablename IN ('monitoring_tasks', 'found_items', 'proxies')
            ORDER BY tablename
        """)
        
        for row in rows:
            print(f"\n📋 Таблица: {row['tablename']}")
            print(f"  Вставок: {row['inserts']}")
            print(f"  Обновлений: {row['updates']}")
            print(f"  Удалений: {row['deletes']}")
            print(f"  Живых строк: {row['live_tuples']}")
            print(f"  Мертвых строк: {row['dead_tuples']}")
            if row['last_autovacuum']:
                print(f"  Последний autovacuum: {row['last_autovacuum']}")
            if row['last_autoanalyze']:
                print(f"  Последний autoanalyze: {row['last_autoanalyze']}")
        
    finally:
        await conn.close()


async def main():
    """Главная функция."""
    print("=" * 80)
    print("🔍 МОНИТОРИНГ СОСТОЯНИЯ БД")
    print("=" * 80)
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    try:
        await check_active_connections()
        await check_locks()
        await check_transactions()
        await check_table_stats()
        
        print("\n" + "=" * 80)
        print("✅ Мониторинг завершен")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
