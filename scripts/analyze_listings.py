"""
Скрипт для анализа листингов Steam Market и поиска наиболее продуктивного render endpoint.
Анализирует разные варианты предметов и определяет, какой листинг содержит больше всего страниц.
"""
import asyncio
import httpx
from urllib.parse import quote
from typing import Dict, List, Tuple

def log(msg: str):
    """Простая функция логирования."""
    print(msg)

# Варианты AK-47 | Slate из результатов поиска
LISTING_VARIANTS = [
    ("AK-47 | Slate (Minimal Wear)", 733),
    ("AK-47 | Slate (Battle-Scarred)", 892),
    ("AK-47 | Slate (Field-Tested)", 1534),
    ("AK-47 | Slate (Well-Worn)", 989),
    ("AK-47 | Slate (Factory New)", 353),
    ("StatTrak™ AK-47 | Slate (Battle-Scarred)", 140),
    ("StatTrak™ AK-47 | Slate (Minimal Wear)", 146),
    ("StatTrak™ AK-47 | Slate (Well-Worn)", 125),
    ("StatTrak™ AK-47 | Slate (Field-Tested)", 237),
    ("StatTrak™ AK-47 | Slate (Factory New)", 63),
]

APPID = 730
BASE_RENDER_URL = "https://steamcommunity.com/market/listings/{appid}/{hash_name}/render/"


async def get_listing_pages_count(
    client: httpx.AsyncClient,
    hash_name: str,
    appid: int = APPID
) -> Tuple[int, int, Dict]:
    """
    Получает количество страниц для листинга.
    
    Args:
        client: HTTP клиент
        hash_name: Название предмета (hash name)
        appid: ID приложения
        
    Returns:
        Tuple: (количество страниц, общее количество предметов, данные первой страницы)
    """
    # Формируем URL для render endpoint
    encoded_name = quote(hash_name, safe="")
    url = BASE_RENDER_URL.format(appid=appid, hash_name=encoded_name)
    
    # Пробуем разные значения count, чтобы понять правильный формат
    # На странице листинга обычно показывается по 10 результатов на страницу
    params = {
        "query": "",
        "start": 0,
        "count": 10,  # На странице листинга показывается по 10 результатов
        "currency": 1,
        "language": "english",
        "country": "US"  # Добавляем country как в коде
    }
    
    try:
        # Делаем запрос с реалистичными заголовками
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": f"https://steamcommunity.com/market/listings/{appid}/{encoded_name}",
            "Origin": "https://steamcommunity.com",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        
        response = await client.get(url, params=params, headers=headers, timeout=30.0)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get("success"):
            log(f"  ❌ Запрос неуспешен: {data.get('error', 'Unknown error')}")
            return 0, 0, {}
        
        total_count = data.get("total_count", 0)
        results = data.get("results", [])
        listinginfo = data.get("listinginfo", {})
        
        # На странице листинга показывается по 10 результатов на страницу
        # Но в listinginfo может быть больше данных
        max_per_page = 10  # На странице листинга показывается по 10 результатов
        pages_count = (total_count + max_per_page - 1) // max_per_page if total_count > 0 else 0
        
        # Также проверяем listinginfo - там может быть реальное количество
        if listinginfo:
            listinginfo_count = len(listinginfo)
            # Если listinginfo больше, используем его для расчета
            if listinginfo_count > 0:
                pages_count_from_listinginfo = (listinginfo_count + max_per_page - 1) // max_per_page
                # Используем большее значение
                if pages_count_from_listinginfo > pages_count:
                    pages_count = pages_count_from_listinginfo
                    total_count = listinginfo_count
        
        return pages_count, total_count, data
        
    except httpx.HTTPStatusError as e:
        log(f"  ❌ HTTP ошибка {e.response.status_code}: {e}")
        return 0, 0, {}
    except Exception as e:
        log(f"  ❌ Ошибка: {e}")
        return 0, 0, {}


async def analyze_all_listings():
    """Анализирует все варианты листингов."""
    log("🔍 Анализ листингов для AK-47 | Slate\n")
    log("=" * 80)
    
    results: List[Tuple[str, int, int, int]] = []  # (name, market_qty, pages, total_count)
    
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for hash_name, market_qty in LISTING_VARIANTS:
            log(f"\n📦 Анализируем: {hash_name}")
            log(f"   Количество на маркете (из поиска): {market_qty}")
            
            # Небольшая задержка между запросами
            await asyncio.sleep(1.0)
            
            pages, total_count, data = await get_listing_pages_count(client, hash_name)
            
            if pages > 0:
                log(f"   ✅ Найдено: {total_count} предметов, {pages} страниц")
                results.append((hash_name, market_qty, pages, total_count))
            else:
                log(f"   ⚠️ Не удалось получить данные")
    
    # Сортируем результаты по количеству страниц
    results.sort(key=lambda x: x[2], reverse=True)
    
    log("\n" + "=" * 80)
    log("📊 РЕЗУЛЬТАТЫ АНАЛИЗА (отсортировано по количеству страниц):\n")
    
    for idx, (hash_name, market_qty, pages, total_count) in enumerate(results, 1):
        log(f"{idx}. {hash_name}")
        log(f"   📈 Страниц: {pages} | Предметов: {total_count} | На маркете: {market_qty}")
    
    if results:
        best = results[0]
        log("\n" + "=" * 80)
        log(f"🏆 НАИБОЛЕЕ ПРОДУКТИВНЫЙ ЛИСТИНГ:")
        log(f"   Название: {best[0]}")
        log(f"   Страниц: {best[2]}")
        log(f"   Предметов: {best[3]}")
        log(f"   URL: https://steamcommunity.com/market/listings/{APPID}/{quote(best[0], safe='')}")
        log(f"   Render: https://steamcommunity.com/market/listings/{APPID}/{quote(best[0], safe='')}/render/")
        log("=" * 80)
        
        # Дополнительный анализ: проверяем структуру данных лучшего листинга
        log("\n🔬 Детальный анализ лучшего листинга:")
        log(f"   Проверяем структуру данных для: {best[0]}")
        
        async with httpx.AsyncClient(follow_redirects=True) as detail_client:
            await asyncio.sleep(1.0)
            _, _, data = await get_listing_pages_count(detail_client, best[0])
            
            if data:
                log(f"   Структура ответа:")
                log(f"   - success: {data.get('success')}")
                log(f"   - total_count: {data.get('total_count')}")
                log(f"   - results: {len(data.get('results', []))} элементов")
                log(f"   - assets: {len(data.get('assets', {}))} asset'ов")
                log(f"   - listinginfo: {len(data.get('listinginfo', {}))} листингов")
                
                # Проверяем, есть ли пагинация
                if data.get('total_count', 0) > len(data.get('results', [])):
                    log(f"   ✅ Пагинация доступна (total_count > results)")
                else:
                    log(f"   ℹ️ Все результаты на одной странице")


if __name__ == "__main__":
    asyncio.run(analyze_all_listings())

