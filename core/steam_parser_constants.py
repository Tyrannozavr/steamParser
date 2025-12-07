"""
Константы и утилиты для Steam Market парсера.
"""

# Актуальный список User-Agent для ротации (имитация разных браузеров и версий)
# Обновлены до актуальных версий для лучшей совместимости
USER_AGENTS = [
    # Chrome на Windows 11 (самые популярные)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Chrome на macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Firefox на Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    # Safari на macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    # Chrome на Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Edge на Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]


def _get_base_price_manager():
    """Ленивый импорт для избежания циклических зависимостей."""
    from services.base_price_manager import BasePriceManager
    return BasePriceManager


def _get_config():
    """Ленивый импорт для избежания циклических зависимостей."""
    from core.config import Config
    return Config


def get_random_user_agent() -> str:
    """Возвращает случайный User-Agent из списка."""
    import random
    return random.choice(USER_AGENTS)


def get_browser_headers(user_agent: str) -> dict:
    """
    Генерирует реалистичные заголовки для имитации браузера Chrome.
    
    Args:
        user_agent: User-Agent строка
        
    Returns:
        Словарь с заголовками HTTP
    """
    import random
    
    # Определяем платформу из User-Agent для правильных Sec-CH-UA заголовков
    if "Windows" in user_agent:
        accept_language = random.choice([
            "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "en-US,en;q=0.9,ru;q=0.8"
        ])
        sec_ch_ua_platform = '"Windows"'
    elif "Macintosh" in user_agent:
        accept_language = random.choice([
            "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "en-US,en;q=0.9,ru;q=0.8"
        ])
        sec_ch_ua_platform = '"macOS"'
    else:
        accept_language = "en-US,en;q=0.9,ru;q=0.8"
        sec_ch_ua_platform = '"Linux"'
    
    # Определяем версию браузера из User-Agent
    chrome_version = "131"  # По умолчанию
    if "Chrome/" in user_agent:
        try:
            chrome_version = user_agent.split("Chrome/")[1].split(".")[0]
        except:
            pass
    
    # Формируем реалистичные заголовки как у Chrome
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://steamcommunity.com",
        "Referer": "https://steamcommunity.com/market/search?appid=730",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-CH-UA": f'"Google Chrome";v="{chrome_version}", "Chromium";v="{chrome_version}", "Not_A Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": sec_ch_ua_platform,
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
    }
    
    return headers

