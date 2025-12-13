"""
Утилиты для параллельного парсинга лотов.
"""
import json
import random
from typing import Optional, List
from datetime import datetime as dt
from loguru import logger

from core import Proxy
from sqlalchemy.orm import make_transient


async def get_available_proxies(parser, log_func) -> List[Proxy]:
    """
    Получает список доступных прокси из Redis кэша или через ProxyManager.
    
    Args:
        parser: Экземпляр SteamMarketParser
        log_func: Функция для логирования
        
    Returns:
        Список доступных прокси
    """
    available_proxies = []
    
    if not parser.proxy_manager:
        log_func("error", "❌ ProxyManager не доступен")
        return []
    
    # Получаем прокси напрямую из Redis кэша, минуя БД
    if parser.proxy_manager.redis_service:
        try:
            log_func("debug", "🔍 Получаем прокси из Redis кэша...")
            cached_proxies_data = await parser.proxy_manager.redis_service.get(parser.proxy_manager.REDIS_CACHE_KEY)
            if cached_proxies_data:
                cached_proxies = json.loads(cached_proxies_data)
                
                for p_data in cached_proxies:
                    # Проверяем блокировку через Redis
                    proxy_id = p_data["id"]
                    blocked_key = f"{parser.proxy_manager.REDIS_BLOCKED_PREFIX}{proxy_id}"
                    blocked_until = await parser.proxy_manager.redis_service.get(blocked_key)
                    
                    is_blocked = False
                    if blocked_until:
                        try:
                            blocked_until_dt = dt.fromisoformat(blocked_until)
                            if dt.now() < blocked_until_dt:
                                is_blocked = True
                        except:
                            pass
                    
                    if not is_blocked and p_data.get("is_active", True):
                        # Создаем объект Proxy без привязки к сессии
                        proxy = Proxy(
                            id=proxy_id,
                            url=p_data["url"],
                            is_active=p_data.get("is_active", True),
                            delay_seconds=p_data.get("delay_seconds", 0.2),
                            success_count=p_data.get("success_count", 0),
                            fail_count=p_data.get("fail_count", 0),
                            last_used=dt.fromisoformat(p_data["last_used"]) if p_data.get("last_used") else None,
                            last_error=p_data.get("last_error")
                        )
                        make_transient(proxy)
                        available_proxies.append(proxy)
        except Exception as e:
            log_func("warning", f"⚠️ Ошибка при получении прокси из Redis: {e}")
    
    # Если не получилось из Redis, пробуем через get_active_proxies (но без force_refresh)
    if not available_proxies:
        try:
            log_func("debug", "🔍 Получаем прокси через get_active_proxies...")
            active_proxies = await parser.proxy_manager.get_active_proxies(force_refresh=False)
            if active_proxies:
                # Фильтруем только не заблокированные прокси
                for proxy in active_proxies:
                    is_blocked = False
                    if parser.proxy_manager.redis_service:
                        try:
                            blocked_key = f"{parser.proxy_manager.REDIS_BLOCKED_PREFIX}{proxy.id}"
                            blocked_until = await parser.proxy_manager.redis_service.get(blocked_key)
                            if blocked_until:
                                try:
                                    blocked_until_dt = dt.fromisoformat(blocked_until)
                                    if dt.now() < blocked_until_dt:
                                        is_blocked = True
                                except:
                                    pass
                        except:
                            pass
                    
                    if not is_blocked:
                        available_proxies.append(proxy)
        except Exception as e:
            log_func("error", f"❌ Ошибка при получении прокси: {e}")
    
    return available_proxies


def get_random_proxy(available_proxies: List[Proxy]) -> Optional[Proxy]:
    """
    Получает случайный прокси из доступных.
    
    Args:
        available_proxies: Список доступных прокси
        
    Returns:
        Случайный прокси или None
    """
    if not available_proxies:
        return None
    return random.choice(available_proxies)

