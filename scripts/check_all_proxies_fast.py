#!/usr/bin/env python3
"""
Быстрая параллельная проверка всех прокси.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import DatabaseManager
from services.proxy_manager import ProxyManager


async def main():
    """Быстрая проверка всех прокси параллельно."""
    print("🚀 Запуск быстрой параллельной проверки всех прокси...")
    
    # Инициализируем базу данных
    db_manager = DatabaseManager()
    
    async with await db_manager.get_session() as session:
        # Создаем ProxyManager
        proxy_manager = ProxyManager(session)
        
        # Запускаем параллельную проверку
        print("⏳ Проверяем прокси...")
        results = await proxy_manager.check_all_proxies_parallel(max_concurrent=20)
        
        # Выводим результаты
        print("\n" + "="*60)
        print("📊 РЕЗУЛЬТАТЫ БЫСТРОЙ ПРОВЕРКИ ПРОКСИ:")
        print("="*60)
        print(f"📋 Всего прокси: {results['total']}")
        print(f"✅ Работающих: {results['working']}")
        print(f"🚫 Заблокированных: {results['blocked']}")
        print(f"❌ Ошибок: {results['error']}")
        
        if results['working'] > 0:
            working_percentage = (results['working'] / results['total']) * 100
            print(f"📈 Процент работающих: {working_percentage:.1f}%")
        
        # Показываем детали по заблокированным
        if results['blocked'] > 0:
            print(f"\n⚠️ Заблокированные прокси:")
            blocked_proxies = [r for r in results['results'] if r['status'] == 'blocked']
            for proxy in blocked_proxies[:10]:  # Показываем первые 10
                print(f"   ID={proxy['proxy_id']}: {proxy['url']}")
            if len(blocked_proxies) > 10:
                print(f"   ... и еще {len(blocked_proxies) - 10} заблокированных")
        
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
