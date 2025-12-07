"""
Скрипт для тестирования частоты запросов к Steam Community API.
Цель: выявить оптимальную частоту запросов для избежания 429 ошибок.
Параллельно тестирует разные интервалы одновременно.
"""
import asyncio
import httpx
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))

from core import DatabaseManager, Config, Proxy
from loguru import logger

# Настройка логирования
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>", level="INFO")

# Домены Steam Community для тестирования
TEST_URLS = [
    "https://steamcommunity.com/market/search/render/",
    "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20%28Field-Tested%29/render/",
    "https://steamcommunity.com/market/searchsuggestionsresults",
]

# Параметры для разных URL
URL_PARAMS = {
    "https://steamcommunity.com/market/search/render/": {
        "query": "AK-47",
        "appid": 730,
        "start": 0,
        "count": 1,
        "norender": 1
    },
    "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20%28Field-Tested%29/render/": {
        "query": "",
        "start": 0,
        "count": 1,
        "country": "US",
        "language": "english",
        "currency": 1
    },
    "https://steamcommunity.com/market/searchsuggestionsresults": {
        "q": "AK-47"
    }
}

# Разные интервалы для тестирования (в секундах)
TEST_INTERVALS = [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0]

# Количество запросов для каждого интервала
REQUESTS_PER_INTERVAL = 20

# Заголовки для запросов
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://steamcommunity.com/market/",
    "Origin": "https://steamcommunity.com",
}


async def make_request(
    client: httpx.AsyncClient,
    url: str,
    proxy_url: Optional[str] = None
) -> Dict[str, any]:
    """
    Выполняет запрос к Steam API.
    
    Args:
        client: HTTP клиент
        url: URL для запроса
        proxy_url: URL прокси (опционально)
        
    Returns:
        Словарь с результатами запроса
    """
    params = URL_PARAMS.get(url, {})
    
    try:
        response = await client.get(url, params=params, headers=HEADERS, timeout=15.0)
        
        return {
            "status_code": response.status_code,
            "success": response.status_code == 200,
            "is_429": response.status_code == 429,
            "error": None,
            "response_time": response.elapsed.total_seconds()
        }
    except httpx.TimeoutException as e:
        return {
            "status_code": None,
            "success": False,
            "is_429": False,
            "error": "Timeout",
            "response_time": None
        }
    except Exception as e:
        return {
            "status_code": None,
            "success": False,
            "is_429": False,
            "error": f"{type(e).__name__}: {str(e)[:100]}",
            "response_time": None
        }




async def test_single_proxy_with_interval(
    interval: float,
    proxy: Proxy,
    url: str,
    interval_name: str
) -> Dict[str, any]:
    """
    Тестирует ОДИН прокси с фиксированной частотой запросов.
    
    Args:
        interval: Интервал между запросами в секундах (частота)
        proxy: Прокси для тестирования (один прокси на одну частоту)
        url: URL для тестирования
        interval_name: Название интервала для логирования
        
    Returns:
        Словарь с результатами тестирования
    """
    logger.info(f"[{interval_name}] 🚀 Прокси ID={proxy.id} | Частота: {interval} сек между запросами")
    
    results = {
        "interval": interval,
        "interval_name": interval_name,
        "proxy_id": proxy.id,
        "proxy_url": proxy.url[:50] + "..." if len(proxy.url) > 50 else proxy.url,
        "url": url,
        "requests": [],
        "successful": 0,
        "failed": 0,
        "429_errors": 0,
        "other_errors": 0,
        "avg_response_time": 0.0,
        "first_429_at": None
    }
    
    # Создаем клиент для этого прокси
    async with httpx.AsyncClient(
        proxy=proxy.url,
        timeout=15.0,
        headers=HEADERS,
        follow_redirects=True
    ) as client:
        
        # Делаем запросы с заданным интервалом (фиксированная частота для этого прокси)
        for request_num in range(1, REQUESTS_PER_INTERVAL + 1):
            result = await make_request(client, url, proxy.url)
            
            results["requests"].append(result)
            
            if result["success"]:
                results["successful"] += 1
                logger.info(f"[{interval_name}] Прокси ID={proxy.id} | Запрос {request_num}/{REQUESTS_PER_INTERVAL} ✅ {result['status_code']} ({result['response_time']:.2f}s)")
            elif result["is_429"]:
                results["429_errors"] += 1
                results["failed"] += 1
                if results["first_429_at"] is None:
                    results["first_429_at"] = request_num
                logger.warning(f"[{interval_name}] Прокси ID={proxy.id} | Запрос {request_num}/{REQUESTS_PER_INTERVAL} 🚫 429 Too Many Requests")
                # При 429 ошибке прекращаем тестирование этого прокси
                break
            else:
                results["other_errors"] += 1
                results["failed"] += 1
                error_msg = result.get("error", "Unknown")
                logger.error(f"[{interval_name}] Прокси ID={proxy.id} | Запрос {request_num}/{REQUESTS_PER_INTERVAL} ❌ {error_msg}")
            
            # Задержка перед следующим запросом (кроме последнего)
            if request_num < REQUESTS_PER_INTERVAL and not result["is_429"]:
                await asyncio.sleep(interval)
    
    # Вычисляем среднее время ответа
    response_times = [r["response_time"] for r in results["requests"] if r["response_time"] is not None]
    if response_times:
        results["avg_response_time"] = sum(response_times) / len(response_times)
    
    logger.info(f"[{interval_name}] ✅ Завершено: Прокси ID={proxy.id} | Успешно: {results['successful']}/{len(results['requests'])}, 429: {results['429_errors']}")
    
    return results


async def test_url_parallel(
    url: str,
    proxies: List[Proxy]
) -> List[Dict[str, any]]:
    """
    Параллельно тестирует разные частоты на разных прокси.
    Один прокси = одна частота (интервал).
    
    Args:
        url: URL для тестирования
        proxies: Список прокси для тестирования
        
    Returns:
        Список результатов для всех интервалов
    """
    logger.info(f"\n{'#'*80}")
    logger.info(f"🌐 Параллельное тестирование URL: {url}")
    logger.info(f"   Интервалов (частот): {len(TEST_INTERVALS)}")
    logger.info(f"   Прокси: {len(proxies)}")
    logger.info(f"   Запросов на прокси: {REQUESTS_PER_INTERVAL}")
    logger.info(f"   Один прокси = одна частота (без ротации)")
    logger.info(f"{'#'*80}\n")
    
    # Создаем задачи для параллельного выполнения
    # Каждый интервал (частота) тестируется на ОДНОМ отдельном прокси
    tasks = []
    
    for interval_idx, interval in enumerate(TEST_INTERVALS):
        # Выбираем прокси для этого интервала (один прокси на одну частоту)
        proxy_idx = interval_idx % len(proxies)
        proxy = proxies[proxy_idx]
        interval_name = f"FREQ{interval:.1f}s"
        
        task = test_single_proxy_with_interval(interval, proxy, url, interval_name)
        tasks.append(task)
    
    # Запускаем все тесты параллельно
    logger.info(f"🚀 Запускаем {len(tasks)} параллельных тестов (каждый прокси на своей частоте)...\n")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Обрабатываем результаты
    valid_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"❌ Ошибка при тестировании интервала {TEST_INTERVALS[i]}: {result}")
        else:
            valid_results.append(result)
    
    return valid_results


async def main():
    """Основная функция."""
    logger.info("🚀 Запуск параллельного тестирования частоты запросов к Steam Community API")
    logger.info("="*80)
    
    # Подключение к БД
    database_url = Config.DATABASE_URL
    if "localhost" in database_url or "127.0.0.1" in database_url:
        database_url = database_url.replace("localhost", "127.0.0.1")
        logger.info(f"📡 Используем DATABASE_URL: {database_url.replace(Config.DATABASE_URL.split('@')[1] if '@' in Config.DATABASE_URL else '', '***')}")
    
    db_manager = DatabaseManager(database_url)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        
        # Получаем активные прокси
        result = await session.execute(
            select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        logger.info(f"📋 Найдено {len(all_proxies)} активных прокси в БД")
        
        if len(all_proxies) == 0:
            logger.error("❌ Нет активных прокси в базе данных")
            return
        
        # Берем 10 прокси для тестирования (как просил пользователь)
        num_proxies = min(10, len(all_proxies))
        selected_proxies = all_proxies[:num_proxies]
        
        logger.info(f"✅ Выбрано {len(selected_proxies)} прокси для тестирования")
        for i, proxy in enumerate(selected_proxies, 1):
            logger.info(f"   {i}. ID={proxy.id}: {proxy.url[:60]}...")
        
        # Если интервалов больше, чем прокси, используем прокси по кругу
        if len(TEST_INTERVALS) > len(selected_proxies):
            logger.warning(f"⚠️ Интервалов ({len(TEST_INTERVALS)}) больше, чем прокси ({len(selected_proxies)}). Прокси будут использоваться по кругу.")
        
        # Результаты всех тестов
        all_results = []
        
        # Тестируем каждый URL
        for url in TEST_URLS:
            results = await test_url_parallel(url, selected_proxies)
            all_results.extend(results)
            
            # Небольшая задержка между тестами разных URL
            if url != TEST_URLS[-1]:
                logger.info(f"\n⏳ Пауза 10 секунд перед следующим URL...\n")
                await asyncio.sleep(10.0)
        
        # Финальный отчет
        logger.info(f"\n\n{'='*80}")
        logger.info("📊 ФИНАЛЬНЫЙ ОТЧЕТ")
        logger.info(f"{'='*80}\n")
        
        # Группируем результаты по интервалам
        for interval in TEST_INTERVALS:
            interval_results = [r for r in all_results if r["interval"] == interval]
            if not interval_results:
                continue
            
            total_429 = sum(r["429_errors"] for r in interval_results)
            total_success = sum(r["successful"] for r in interval_results)
            total_requests = sum(len(r["requests"]) for r in interval_results)
            first_429_list = [r["first_429_at"] for r in interval_results if r["first_429_at"] is not None]
            
            success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0
            
            logger.info(f"Интервал {interval:5.1f} сек: "
                       f"Успешно: {total_success}/{total_requests} ({success_rate:.1f}%), "
                       f"429 ошибок: {total_429}")
            
            if first_429_list:
                avg_first_429 = sum(first_429_list) / len(first_429_list)
                logger.info(f"   └─ Первая 429 ошибка в среднем на запросе: {avg_first_429:.1f}")
        
        # Рекомендации
        logger.info(f"\n\n{'='*80}")
        logger.info("💡 РЕКОМЕНДАЦИИ")
        logger.info(f"{'='*80}\n")
        
        # Находим минимальный интервал без 429 ошибок
        safe_intervals = []
        for interval in TEST_INTERVALS:
            interval_results = [r for r in all_results if r["interval"] == interval]
            if interval_results:
                total_429 = sum(r["429_errors"] for r in interval_results)
                if total_429 == 0:
                    safe_intervals.append(interval)
        
        if safe_intervals:
            min_safe = min(safe_intervals)
            logger.info(f"✅ Минимальный безопасный интервал (без 429 ошибок): {min_safe} сек")
            logger.info(f"   Рекомендуется использовать интервал не менее {min_safe} сек между запросами")
            
            # Находим оптимальный интервал (самый короткий без 429)
            optimal = min_safe
            logger.info(f"\n🎯 ОПТИМАЛЬНЫЙ ИНТЕРВАЛ: {optimal} сек")
            logger.info(f"   Это самый короткий интервал, при котором не было 429 ошибок")
        else:
            logger.warning(f"⚠️ Все протестированные интервалы дали 429 ошибки")
            logger.warning(f"   Рекомендуется увеличить интервал до {max(TEST_INTERVALS) + 10} сек или более")
        
        # Детальная статистика по каждому интервалу
        logger.info(f"\n\n{'='*80}")
        logger.info("📈 ДЕТАЛЬНАЯ СТАТИСТИКА ПО ИНТЕРВАЛАМ")
        logger.info(f"{'='*80}\n")
        
        for interval in sorted(TEST_INTERVALS):
            interval_results = [r for r in all_results if r["interval"] == interval]
            if not interval_results:
                continue
            
            total_429 = sum(r["429_errors"] for r in interval_results)
            total_success = sum(r["successful"] for r in interval_results)
            total_requests = sum(len(r["requests"]) for r in interval_results)
            avg_response_time = sum(r["avg_response_time"] for r in interval_results) / len(interval_results) if interval_results else 0
            
            logger.info(f"\nИнтервал {interval:5.1f} сек:")
            logger.info(f"  Всего запросов: {total_requests}")
            logger.info(f"  Успешных: {total_success} ({total_success/total_requests*100:.1f}%)")
            logger.info(f"  429 ошибок: {total_429}")
            logger.info(f"  Среднее время ответа: {avg_response_time:.2f} сек")
            
            if total_429 > 0:
                first_429_list = [r["first_429_at"] for r in interval_results if r["first_429_at"] is not None]
                if first_429_list:
                    logger.info(f"  Первая 429 ошибка: на запросе {min(first_429_list)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
