#!/usr/bin/env python3
"""
Скрипт для проверки использования памяти Redis и очистки старых/зависших ключей.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.redis_service import RedisService
from loguru import logger


async def analyze_redis_memory():
    """Анализирует использование памяти Redis и находит проблемные ключи."""
    redis_service = RedisService()
    await redis_service.connect()
    
    if not redis_service.is_connected():
        logger.error("❌ Не удалось подключиться к Redis")
        return
    
    client = redis_service._client
    if not client:
        logger.error("❌ Redis клиент не инициализирован")
        return
    
    logger.info("🔍 Анализируем использование памяти Redis...")
    
    # Получаем информацию о памяти
    try:
        info = await client.info("memory")
        used_memory = info.get("used_memory_human", "N/A")
        used_memory_peak = info.get("used_memory_peak_human", "N/A")
        max_memory = info.get("maxmemory_human", "N/A")
        max_memory_policy = info.get("maxmemory_policy", "N/A")
        
        logger.info(f"📊 Использование памяти Redis:")
        logger.info(f"   💾 Используется: {used_memory}")
        logger.info(f"   📈 Пик использования: {used_memory_peak}")
        logger.info(f"   🔒 Максимум: {max_memory}")
        logger.info(f"   ⚙️ Политика: {max_memory_policy}")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось получить информацию о памяти: {e}")
    
    # Анализируем ключи по паттернам
    patterns = {
        "parsed_item:*": "Кэш распарсенных предметов",
        "proxy:last_used:*": "Время последнего использования прокси (БЕЗ TTL!)",
        "proxy:blocked:*": "Заблокированные прокси",
        "proxy:in_use:*": "Резервированные прокси",
        "parsing:pages:task_*": "Очереди страниц для парсинга",
        "parsing_task_running:*": "Флаги выполнения задач",
        "sticker_price:*": "Кэш цен наклеек",
        "proxies:active": "Кэш активных прокси",
    }
    
    logger.info("\n🔍 Анализируем ключи по паттернам...")
    
    total_keys = 0
    total_memory = 0
    keys_by_pattern = defaultdict(lambda: {"count": 0, "memory": 0, "keys": []})
    
    for pattern, description in patterns.items():
        try:
            # Используем SCAN для безопасного перебора ключей
            cursor = 0
            keys = []
            while True:
                cursor, batch = await client.scan(cursor, match=pattern, count=1000)
                keys.extend(batch)
                if cursor == 0:
                    break
            
            if keys:
                count = len(keys)
                # Получаем размер памяти для каждого ключа
                memory = 0
                sample_keys = []
                for key in keys[:10]:  # Берем первые 10 для примера
                    try:
                        key_memory = await client.memory_usage(key)
                        if key_memory:
                            memory += key_memory
                        sample_keys.append(key.decode() if isinstance(key, bytes) else key)
                    except Exception:
                        pass
                
                # Оцениваем общий размер (примерно)
                if count > 0:
                    avg_memory = memory / min(count, 10)
                    estimated_total = avg_memory * count
                else:
                    estimated_total = 0
                
                keys_by_pattern[pattern] = {
                    "count": count,
                    "memory": estimated_total,
                    "keys": sample_keys,
                    "description": description
                }
                
                total_keys += count
                total_memory += estimated_total
                
                logger.info(f"   📋 {description}:")
                logger.info(f"      Ключей: {count}")
                logger.info(f"      Примерный размер: {estimated_total / 1024 / 1024:.2f} MB")
                if sample_keys:
                    logger.info(f"      Примеры: {', '.join(sample_keys[:3])}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при анализе паттерна {pattern}: {e}")
    
    logger.info(f"\n📊 Итого:")
    logger.info(f"   Всего ключей: {total_keys}")
    logger.info(f"   Примерный размер: {total_memory / 1024 / 1024:.2f} MB")
    
    # Проверяем зависшие ключи
    logger.info("\n🔍 Проверяем зависшие ключи...")
    
    # Проверяем зависшие флаги выполнения задач
    try:
        cursor = 0
        hung_flags = []
        while True:
            cursor, batch = await client.scan(cursor, match="parsing_task_running:*", count=1000)
            for key in batch:
                key_str = key.decode() if isinstance(key, bytes) else key
                ttl = await client.ttl(key_str)
                if ttl == -1:  # Нет TTL - это проблема!
                    hung_flags.append(key_str)
                elif ttl > 3600:  # TTL больше часа - странно
                    hung_flags.append(f"{key_str} (TTL: {ttl}с)")
            if cursor == 0:
                break
        
        if hung_flags:
            logger.warning(f"⚠️ Найдено {len(hung_flags)} зависших флагов выполнения задач:")
            for flag in hung_flags[:10]:
                logger.warning(f"   - {flag}")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при проверке зависших флагов: {e}")
    
    # Проверяем зависшие очереди страниц
    try:
        cursor = 0
        hung_queues = []
        while True:
            cursor, batch = await client.scan(cursor, match="parsing:pages:task_*", count=1000)
            for key in batch:
                key_str = key.decode() if isinstance(key, bytes) else key
                queue_len = await client.llen(key_str)
                if queue_len > 0:
                    hung_queues.append((key_str, queue_len))
            if cursor == 0:
                break
        
        if hung_queues:
            logger.warning(f"⚠️ Найдено {len(hung_queues)} зависших очередей страниц:")
            for queue, length in hung_queues[:10]:
                logger.warning(f"   - {queue}: {length} элементов")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при проверке зависших очередей: {e}")
    
    # Проверяем ключи без TTL
    logger.info("\n🔍 Проверяем ключи без TTL (потенциальная утечка памяти)...")
    
    problematic_patterns = [
        "proxy:last_used:*",
        "proxy:last_index",
        "proxy:last_smart_check",
    ]
    
    for pattern in problematic_patterns:
        try:
            cursor = 0
            keys_without_ttl = []
            while True:
                cursor, batch = await client.scan(cursor, match=pattern, count=1000)
                for key in batch:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    ttl = await client.ttl(key_str)
                    if ttl == -1:  # Нет TTL
                        keys_without_ttl.append(key_str)
                if cursor == 0:
                    break
            
            if keys_without_ttl:
                logger.warning(f"⚠️ Найдено {len(keys_without_ttl)} ключей без TTL для паттерна {pattern}:")
                for key in keys_without_ttl[:10]:
                    logger.warning(f"   - {key}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при проверке паттерна {pattern}: {e}")
    
    await redis_service.disconnect()


async def cleanup_redis():
    """Очищает старые и зависшие ключи из Redis."""
    redis_service = RedisService()
    await redis_service.connect()
    
    if not redis_service.is_connected():
        logger.error("❌ Не удалось подключиться к Redis")
        return
    
    client = redis_service._client
    if not client:
        logger.error("❌ Redis клиент не инициализирован")
        return
    
    logger.info("🧹 Начинаем очистку Redis...")
    
    cleaned = 0
    
    # Очищаем зависшие флаги выполнения задач (старше 2 часов)
    try:
        cursor = 0
        while True:
            cursor, batch = await client.scan(cursor, match="parsing_task_running:*", count=1000)
            for key in batch:
                key_str = key.decode() if isinstance(key, bytes) else key
                ttl = await client.ttl(key_str)
                if ttl == -1 or ttl > 7200:  # Нет TTL или TTL больше 2 часов
                    await client.delete(key_str)
                    cleaned += 1
                    logger.info(f"   🗑️ Удален зависший флаг: {key_str}")
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при очистке флагов: {e}")
    
    # Очищаем зависшие очереди страниц
    try:
        cursor = 0
        while True:
            cursor, batch = await client.scan(cursor, match="parsing:pages:task_*", count=1000)
            for key in batch:
                key_str = key.decode() if isinstance(key, bytes) else key
                queue_len = await client.llen(key_str)
                if queue_len > 0:
                    # Проверяем, не активна ли задача (можно улучшить проверку)
                    await client.delete(key_str)
                    cleaned += 1
                    logger.info(f"   🗑️ Удалена зависшая очередь: {key_str} ({queue_len} элементов)")
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при очистке очередей: {e}")
    
    # Очищаем старые ключи proxy:last_used (старше 7 дней)
    try:
        cursor = 0
        week_ago = (datetime.now() - timedelta(days=7)).timestamp()
        while True:
            cursor, batch = await client.scan(cursor, match="proxy:last_used:*", count=1000)
            for key in batch:
                key_str = key.decode() if isinstance(key, bytes) else key
                try:
                    value = await client.get(key_str)
                    if value:
                        timestamp = float(value)
                        if timestamp < week_ago:
                            await client.delete(key_str)
                            cleaned += 1
                            logger.debug(f"   🗑️ Удален старый ключ: {key_str}")
                except Exception:
                    pass
            if cursor == 0:
                break
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при очистке proxy:last_used: {e}")
    
    logger.info(f"✅ Очистка завершена. Удалено ключей: {cleaned}")
    
    await redis_service.disconnect()


async def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Проверка и очистка Redis")
    parser.add_argument("--cleanup", action="store_true", help="Выполнить очистку старых ключей")
    args = parser.parse_args()
    
    if args.cleanup:
        await cleanup_redis()
    else:
        await analyze_redis_memory()
        logger.info("\n💡 Для очистки запустите с флагом --cleanup")


if __name__ == "__main__":
    asyncio.run(main())

