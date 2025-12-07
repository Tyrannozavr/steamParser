"""
Расширенное тестирование частот для listings/render:
- 0.3 сек с 40 запросами
- 0.5 сек с 40 запросами
"""
import asyncio
import httpx
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))

from core import DatabaseManager, Config, Proxy
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>", level="INFO")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://steamcommunity.com/market/",
    "Origin": "https://steamcommunity.com",
}

# URL для тестирования
TEST_URL = "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20%28Field-Tested%29/render/"
TEST_PARAMS = {
    "query": "",
    "start": 0,
    "count": 1,
    "country": "US",
    "language": "english",
    "currency": 1
}

# Тестируемые частоты
TEST_FREQUENCIES = [0.1, 0.2, 0.3]
REQUESTS_COUNT = 50


async def test_frequency(
    interval: float,
    proxy: Proxy,
    url: str,
    params: dict
) -> Dict:
    """Тестирует одну частоту на одном прокси."""
    logger.info(f"\n{'='*80}")
    logger.info(f"🧪 Тестируем частоту: {interval} сек")
    logger.info(f"   Прокси ID: {proxy.id}")
    logger.info(f"   Количество запросов: {REQUESTS_COUNT}")
    logger.info(f"{'='*80}\n")
    
    results = {
        "interval": interval,
        "proxy_id": proxy.id,
        "proxy_url": proxy.url[:50] + "..." if len(proxy.url) > 50 else proxy.url,
        "total_requests": 0,
        "successful": 0,
        "failed": 0,
        "429_errors": 0,
        "other_errors": 0,
        "first_429_at": None,
        "response_times": [],
        "start_time": datetime.now(),
        "end_time": None
    }
    
    async with httpx.AsyncClient(
        proxy=proxy.url,
        timeout=15.0,
        headers=HEADERS,
        follow_redirects=True
    ) as client:
        
        for request_num in range(1, REQUESTS_COUNT + 1):
            try:
                response = await client.get(url, params=params, headers=HEADERS)
                results["total_requests"] += 1
                
                if response.status_code == 200:
                    results["successful"] += 1
                    response_time = response.elapsed.total_seconds()
                    results["response_times"].append(response_time)
                    logger.info(f"   Запрос {request_num}/{REQUESTS_COUNT}: ✅ 200 OK ({response_time:.2f}s)")
                elif response.status_code == 429:
                    results["429_errors"] += 1
                    results["failed"] += 1
                    if results["first_429_at"] is None:
                        results["first_429_at"] = request_num
                    logger.warning(f"   Запрос {request_num}/{REQUESTS_COUNT}: 🚫 429 Too Many Requests")
                    # При 429 прекращаем тестирование
                    break
                else:
                    results["other_errors"] += 1
                    results["failed"] += 1
                    logger.error(f"   Запрос {request_num}/{REQUESTS_COUNT}: ❌ {response.status_code}")
                    break
                
                # Задержка перед следующим запросом (кроме последнего)
                if request_num < REQUESTS_COUNT:
                    await asyncio.sleep(interval)
                    
            except Exception as e:
                results["other_errors"] += 1
                results["failed"] += 1
                logger.error(f"   Запрос {request_num}/{REQUESTS_COUNT}: ❌ Ошибка: {e}")
                break
    
    results["end_time"] = datetime.now()
    duration = (results["end_time"] - results["start_time"]).total_seconds()
    
    # Вычисляем среднее время ответа
    if results["response_times"]:
        results["avg_response_time"] = sum(results["response_times"]) / len(results["response_times"])
        results["min_response_time"] = min(results["response_times"])
        results["max_response_time"] = max(results["response_times"])
    else:
        results["avg_response_time"] = 0
        results["min_response_time"] = 0
        results["max_response_time"] = 0
    
    results["duration"] = duration
    results["success_rate"] = (results["successful"] / results["total_requests"] * 100) if results["total_requests"] > 0 else 0
    
    logger.info(f"\n📊 Результаты для частоты {interval} сек:")
    logger.info(f"   Всего запросов: {results['total_requests']}")
    logger.info(f"   Успешных: {results['successful']} ({results['success_rate']:.1f}%)")
    logger.info(f"   429 ошибок: {results['429_errors']}")
    if results["first_429_at"]:
        logger.info(f"   Первая 429 ошибка: на запросе {results['first_429_at']}")
    logger.info(f"   Среднее время ответа: {results['avg_response_time']:.2f}s")
    logger.info(f"   Общая длительность: {duration:.1f}s")
    
    return results


async def main():
    """Основная функция."""
    logger.info("🚀 Расширенное тестирование частот для listings/render")
    logger.info("="*80)
    
    # Подключение к БД
    database_url = Config.DATABASE_URL
    if "localhost" in database_url or "127.0.0.1" in database_url:
        database_url = database_url.replace("localhost", "127.0.0.1")
    
    db_manager = DatabaseManager(database_url)
    await db_manager.init_db()
    
    try:
        session = await db_manager.get_session()
        
        # Получаем активные прокси
        result = await session.execute(
            select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)
        )
        all_proxies = list(result.scalars().all())
        
        if len(all_proxies) < len(TEST_FREQUENCIES):
            logger.error(f"❌ Недостаточно прокси: нужно {len(TEST_FREQUENCIES)}, доступно {len(all_proxies)}")
            return
        
        # Выбираем прокси для тестирования
        selected_proxies = all_proxies[:len(TEST_FREQUENCIES)]
        
        logger.info(f"✅ Выбрано {len(selected_proxies)} прокси для тестирования")
        for i, proxy in enumerate(selected_proxies):
            logger.info(f"   {i+1}. ID={proxy.id}: {proxy.url[:60]}...")
        
        # Запускаем тесты параллельно
        tasks = []
        for freq, proxy in zip(TEST_FREQUENCIES, selected_proxies):
            task = test_frequency(freq, proxy, TEST_URL, TEST_PARAMS)
            tasks.append(task)
        
        logger.info(f"\n🚀 Запускаем {len(tasks)} параллельных тестов...\n")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обрабатываем результаты
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ Ошибка при тестировании частоты {TEST_FREQUENCIES[i]}: {result}")
            else:
                valid_results.append(result)
        
        # Финальный отчет
        logger.info(f"\n\n{'='*80}")
        logger.info("📊 ФИНАЛЬНЫЙ ОТЧЕТ")
        logger.info(f"{'='*80}\n")
        
        for result in valid_results:
            logger.info(f"\nЧастота {result['interval']} сек:")
            logger.info(f"  Прокси ID: {result['proxy_id']}")
            logger.info(f"  Всего запросов: {result['total_requests']}")
            logger.info(f"  Успешных: {result['successful']} ({result['success_rate']:.1f}%)")
            logger.info(f"  429 ошибок: {result['429_errors']}")
            if result['first_429_at']:
                logger.info(f"  Первая 429: на запросе {result['first_429_at']}")
            logger.info(f"  Среднее время ответа: {result['avg_response_time']:.2f}s")
            logger.info(f"  Общая длительность: {result['duration']:.1f}s")
            
            if result['429_errors'] == 0:
                logger.info(f"  ✅ Статус: БЕЗ 429 ОШИБОК - частота безопасна")
            elif result['successful'] >= 30:
                logger.info(f"  ⚠️ Статус: Частично работает ({result['successful']} успешных)")
            else:
                logger.info(f"  ❌ Статус: Много ошибок ({result['429_errors']} ошибок 429)")
        
        # Сохраняем результаты в файл
        import json
        results_file = Path(__file__).parent / "docs" / "extended_frequency_test_results.json"
        results_file.parent.mkdir(exist_ok=True)
        
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump({
                "test_date": datetime.now().isoformat(),
                "test_url": TEST_URL,
                "requests_count": REQUESTS_COUNT,
                "results": [
                    {
                        "interval": r["interval"],
                        "proxy_id": r["proxy_id"],
                        "total_requests": r["total_requests"],
                        "successful": r["successful"],
                        "429_errors": r["429_errors"],
                        "first_429_at": r["first_429_at"],
                        "avg_response_time": r["avg_response_time"],
                        "duration": r["duration"],
                        "success_rate": r["success_rate"]
                    }
                    for r in valid_results
                ]
            }, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n💾 Результаты сохранены в: {results_file}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())

