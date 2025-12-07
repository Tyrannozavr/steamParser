"""
Скрипт для демонстрации URL, которые используются для парсинга.
"""
from urllib.parse import urlencode, quote
from steam_parser import SteamMarketParser


def show_search_url():
    """Показывает URL для поиска предметов через API."""
    print("=" * 70)
    print("1️⃣ URL ДЛЯ ПОИСКА ПРЕДМЕТОВ (Steam Market API)")
    print("=" * 70)
    
    base_url = SteamMarketParser.BASE_URL
    print(f"\nБазовый URL: {base_url}\n")
    
    # Пример параметров
    params = {
        "query": "AK-47 | Redline",
        "start": 0,
        "count": 10,
        "search_descriptions": 0,
        "sort_column": "price",
        "sort_dir": "asc",
        "appid": 730,  # CS:GO/CS2
        "currency": 1,  # USD
        "norender": 1
    }
    
    print("Параметры запроса:")
    for key, value in params.items():
        print(f"  - {key}: {value}")
    
    # Формируем полный URL
    full_url = base_url + "?" + urlencode(params)
    print(f"\n📌 Полный URL запроса:")
    print(f"{full_url}\n")
    
    print("Что возвращает:")
    print("  - JSON с массивом предметов (название, цена, количество)")
    print("  - НО БЕЗ float, паттерна и детальной информации о наклейках\n")


def show_item_page_url():
    """Показывает URL для парсинга страницы конкретного предмета."""
    print("=" * 70)
    print("2️⃣ URL ДЛЯ ПАРСИНГА СТРАНИЦЫ ПРЕДМЕТА (HTML)")
    print("=" * 70)
    
    base_url_template = SteamMarketParser.ITEM_DETAILS_URL
    print(f"\nШаблон URL: {base_url_template}\n")
    
    # Примеры реальных URL
    examples = [
        {
            "appid": 730,
            "hash_name": "AK-47 | Redline (Field-Tested)",
            "description": "AK-47 Redline в состоянии Field-Tested"
        },
        {
            "appid": 730,
            "hash_name": "AWP | Dragon Lore (Factory New)",
            "description": "AWP Dragon Lore в состоянии Factory New"
        },
        {
            "appid": 730,
            "hash_name": "★ Karambit | Fade (Factory New)",
            "description": "Нож Karambit Fade в состоянии Factory New"
        }
    ]
    
    print("Примеры реальных URL:\n")
    for i, example in enumerate(examples, 1):
        appid = example["appid"]
        hash_name = example["hash_name"]
        # URL-кодируем hash_name
        encoded_hash = quote(hash_name, safe='')
        full_url = base_url_template.format(appid=appid, hash_name=encoded_hash)
        
        print(f"{i}. {example['description']}")
        print(f"   Hash name: {hash_name}")
        print(f"   URL: {full_url}\n")
    
    print("Что парсится из этой страницы:")
    print("  ✅ Float-значение (из JavaScript кода)")
    print("  ✅ Паттерн/Paint Seed (из JavaScript кода)")
    print("  ✅ Информация о наклейках (из HTML структуры)")
    print("  ✅ Название и цена предмета\n")


def show_workflow():
    """Показывает процесс работы парсера."""
    print("=" * 70)
    print("🔄 ПРОЦЕСС РАБОТЫ ПАРСЕРА")
    print("=" * 70)
    
    print("\nШаг 1: Поиск предметов через API")
    print("  └─> GET https://steamcommunity.com/market/search/render/")
    print("  └─> Получаем список предметов (JSON)")
    print("  └─> Из каждого предмета берем 'market_hash_name'\n")
    
    print("Шаг 2: Для каждого предмета (если нужны детали)")
    print("  └─> GET https://steamcommunity.com/market/listings/730/{hash_name}")
    print("  └─> Получаем HTML страницу")
    print("  └─> Парсим HTML с помощью BeautifulSoup")
    print("  └─> Извлекаем float, паттерн, наклейки\n")
    
    print("Шаг 3: Фильтрация")
    print("  └─> Проверяем предмет по всем заданным фильтрам")
    print("  └─> Возвращаем только подходящие предметы\n")


def main():
    """Главная функция."""
    print("\n" + "=" * 70)
    print("🔗 URL, ИСПОЛЬЗУЕМЫЕ ДЛЯ ПАРСИНГА STEAM MARKET")
    print("=" * 70 + "\n")
    
    show_search_url()
    show_item_page_url()
    show_workflow()
    
    print("=" * 70)
    print("💡 ПРИМЕЧАНИЕ")
    print("=" * 70)
    print("""
1. API поиска (первый URL) - быстрый, но возвращает только базовую информацию
2. HTML страница (второй URL) - медленнее, но содержит ВСЮ информацию о предмете
3. Парсер автоматически использует оба URL:
   - Сначала ищет через API
   - Потом парсит HTML страницы для детальной информации
    """)


if __name__ == "__main__":
    main()

