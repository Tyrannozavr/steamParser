"""
Сервис для парсинга предметов Steam Market.
Отдельный сервис для разделения ответственности.
"""
import asyncio
from typing import Optional, Dict, Any
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import SearchFilters
from services.proxy_manager import ProxyManager

# Ленивый импорт для избежания циклических зависимостей
def _get_steam_parser():
    from core.steam_parser import SteamMarketParser
    return SteamMarketParser

def _get_redis_service():
    from services.redis_service import RedisService
    return RedisService


class ParsingService:
    """Сервис для парсинга предметов на Steam Market."""
    
    def __init__(self, proxy_manager: Optional[ProxyManager] = None, redis_service=None):
        """
        Инициализация сервиса парсинга.
        
        Args:
            proxy_manager: Менеджер прокси (опционально)
            redis_service: Сервис Redis для кэширования (опционально)
        """
        self.proxy_manager = proxy_manager
        self.redis_service = redis_service
    
    async def parse_items(
        self,
        filters: SearchFilters,
        start: int = 0,
        count: int = 20,
        task = None,
        db_session = None,
        redis_service = None,
        db_manager = None
    ) -> Dict[str, Any]:
        """
        Парсит предметы на Steam Market согласно фильтрам.
        
        Args:
            filters: Параметры поиска и фильтрации
            start: Начальная позиция результатов
            count: Количество результатов
            
        Returns:
            Словарь с результатами парсинга:
            - success: bool
            - total_count: int
            - filtered_count: int
            - items: List[Dict]
            - error: str (если success=False)
        """
        # Получаем прокси (если есть)
        # Используем Redis кэш для быстрого доступа (обновляется при добавлении/удалении)
        proxy = None
        proxy_url = None
        if self.proxy_manager:
            logger.info(f"🔍 ParsingService: [ШАГ 1/4] Пытаемся получить прокси через ProxyManager...")
            try:
                # ВАЖНО: Добавляем таймаут для получения прокси, чтобы не зависать надолго
                # Если все прокси заняты, проверка может занять время, но не должно быть бесконечного ожидания
                PROXY_TIMEOUT = 30.0  # 30 секунд - максимальное время ожидания прокси
                try:
                    proxy = await asyncio.wait_for(
                        self.proxy_manager.get_next_proxy(force_refresh=False),
                        timeout=PROXY_TIMEOUT
                    )
                    logger.info(f"✅ ParsingService: [ШАГ 1/4] Прокси получен: ID={proxy.id if proxy else 'None'}")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ ParsingService: [ШАГ 1/4] Таймаут при получении прокси ({PROXY_TIMEOUT} сек)")
                    logger.warning(f"   💡 Все прокси могут быть заняты или заблокированы. Пробуем получить прокси из кэша...")
                    # Пробуем получить прокси из кэша (без обращения к БД)
                    # ВАЖНО: Используем force_refresh=False, чтобы не обращаться к БД
                    # Данные в кэше актуальны, так как они обновляются при блокировке/разблокировке прокси
                    try:
                        logger.info(f"   🔄 ParsingService: [ШАГ 1/4] Пробуем получить прокси из кэша...")
                        proxy = await asyncio.wait_for(
                            self.proxy_manager.get_next_proxy(force_refresh=False),
                            timeout=10.0  # Короткий таймаут для повторной попытки
                        )
                        if proxy:
                            logger.info(f"   ✅ ParsingService: [ШАГ 1/4] Прокси получен после обновления: ID={proxy.id}")
                        else:
                            logger.warning(f"   ⚠️ ParsingService: [ШАГ 1/4] Прокси все еще недоступен после обновления")
                    except (asyncio.TimeoutError, Exception) as e2:
                        logger.warning(f"   ⚠️ ParsingService: [ШАГ 1/4] Не удалось получить прокси после обновления: {e2}")
                        logger.warning(f"   💡 Продолжаем без прокси (с ограничениями)")
                        proxy = None
                        
                        # ВАЖНО: Отправляем уведомление в Telegram если все прокси недоступны (429)
                        if proxy is None and self.proxy_manager:
                            try:
                                # Проверяем, все ли прокси заблокированы (429)
                                active_proxies = await self.proxy_manager.get_active_proxies(force_refresh=False)
                                if active_proxies:
                                    blocked_count = 0
                                    for p in active_proxies:
                                        if await self.proxy_manager._is_proxy_temporarily_blocked(p.id):
                                            blocked_count += 1
                                    
                                    # Если все прокси заблокированы - отправляем уведомление
                                    if blocked_count == len(active_proxies) and blocked_count > 0:
                                        from services.telegram_notifier import send_proxy_unavailable_notification
                                        # Получаем минимальное время до разблокировки
                                        min_delay = 600.0  # 10 минут по умолчанию
                                        for p in active_proxies:
                                            if p.blocked_until:
                                                from datetime import datetime
                                                delay = (p.blocked_until - datetime.now()).total_seconds()
                                                if delay > 0 and delay < min_delay:
                                                    min_delay = delay
                                        
                                        asyncio.create_task(
                                            send_proxy_unavailable_notification(
                                                blocked_count=blocked_count,
                                                total_count=len(active_proxies),
                                                oldest_proxy_delay=min_delay
                                            )
                                        )
                                        logger.warning(f"📢 ParsingService: Отправлено уведомление в Telegram - все {blocked_count} прокси заблокированы (429)")
                            except Exception as notify_error:
                                logger.debug(f"⚠️ ParsingService: Ошибка при отправке уведомления: {notify_error}")
            except Exception as e:
                logger.error(f"❌ ParsingService: [ШАГ 1/4] ОШИБКА при получении прокси: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                # Не поднимаем исключение - продолжаем без прокси
                proxy = None
            if proxy:
                proxy_url = proxy.url if proxy else None
                logger.debug(f"🌐 ParsingService: Получен прокси ID={proxy.id}: {proxy_url[:50]}... (активен: {proxy.is_active}, задержка: {proxy.delay_seconds}с)")
            else:
                logger.warning("⚠️ ParsingService: ProxyManager вернул None - прокси не найден или все заняты")
        else:
            logger.debug("⚠️ ParsingService: ProxyManager не инициализирован")
        
        if proxy:
            logger.debug(f"🌐 ParsingService: Используем прокси ID={proxy.id}: {proxy_url[:50]}...")
        else:
            logger.warning("⚠️ ParsingService: Прокси не найден, используем прямые запросы")
        
        try:
            logger.info(f"🚀 ParsingService: [ШАГ 2/4] Начинаем парсинг для '{filters.item_name}' (прокси: {'ID=' + str(proxy.id) if proxy else 'нет'})")
            
            # Создаем парсер с прокси или без, передаем redis_service и proxy_manager для параллельного парсинга
            logger.info(f"🔧 ParsingService: [ШАГ 2/4] Создаем SteamMarketParser...")
            try:
                SteamMarketParser = _get_steam_parser()
                logger.info(f"✅ ParsingService: [ШАГ 2/4] SteamMarketParser класс получен")
            except Exception as e:
                logger.error(f"❌ ParsingService: [ШАГ 2/4] ОШИБКА при получении класса парсера: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                raise
            
            logger.info(f"🔧 ParsingService: [ШАГ 3/4] Инициализируем парсер (proxy={proxy_url[:50] if proxy_url else 'None'}...)...")
            try:
                async with SteamMarketParser(proxy=proxy_url, timeout=30, redis_service=self.redis_service, proxy_manager=self.proxy_manager) as parser:
                    # Устанавливаем db_manager в parser для доступа в параллельном парсере
                    if db_manager:
                        parser.db_manager = db_manager
                    logger.info(f"✅ ParsingService: [ШАГ 3/4] Парсер инициализирован успешно")
                    # Выполняем поиск
                    logger.info(f"🔍 ParsingService: [ШАГ 4/4] Выполняем поиск через SteamMarketParser.search_items()...")
                    # Передаем task, db_session, redis_service в search_items для доступа в parse_all_listings
                    result = await parser.search_items(
                        filters, 
                        start=start, 
                        count=count,
                        task=task,
                        db_session=db_session,
                        redis_service=redis_service
                    )
                    logger.info(f"✅ ParsingService: [ШАГ 4/4] Поиск завершен: success={result.get('success')}, total={result.get('total_count', 0)}, filtered={result.get('filtered_count', 0)}")
                
                    # Отмечаем прокси как использованный (если был)
                    logger.debug(f"🔍 ParsingService: Проверка условий для обновления статистики: proxy={proxy is not None} (ID={proxy.id if proxy else 'None'}), proxy_manager={self.proxy_manager is not None}")
                    if proxy and self.proxy_manager:
                        logger.debug(f"📊 ParsingService: Начинаем обновление статистики прокси ID={proxy.id}")
                        # Успех для прокси определяется по факту успешного HTTP запроса, а не по наличию предметов
                        # Если мы дошли сюда без исключений - HTTP запрос успешен, даже если предметы не прошли фильтры
                        # Парсер возвращает 'error' только при реальных ошибках HTTP/сети
                        # Если success=False но нет 'error' - это нормально (предметы не прошли фильтры, но прокси работал)
                        # ВАЖНО: 429 (Too Many Requests) - это ошибка, которая должна учитываться в статистике и задержке
                        has_error = 'error' in result
                        error_msg = result.get('error', '') if has_error else None
                        
                        # Определяем, является ли это 429 ошибкой
                        is_429_error = False
                        if has_error and error_msg:
                            error_msg_str = str(error_msg)
                            is_429_error = '429' in error_msg_str or 'Too Many Requests' in error_msg_str
                            logger.debug(f"📊 ParsingService: Проверка 429 ошибки: has_error={has_error}, error_msg={error_msg_str[:100]}, is_429_error={is_429_error}")
                        
                        if is_429_error:
                            # 429 - это ошибка, которая должна учитываться в статистике и увеличивать задержку
                            is_success = False
                            error_msg = f"Too Many Requests (429). Steam временно блокирует запросы. Попробуйте позже или используйте прокси."
                            logger.warning(f"📊 ParsingService: Прокси ID={proxy.id} - 429 ошибка (временная блокировка Steam), учитывается как ошибка для увеличения задержки")
                        elif has_error:
                            # Реальная ошибка HTTP/сети - прокси не справился
                            is_success = False
                            logger.warning(f"📊 ParsingService: Прокси ID={proxy.id} - ошибка HTTP/сети: {error_msg}")
                        else:
                            # HTTP запрос успешен, даже если предметы не найдены или не прошли фильтры
                            is_success = True
                            error_msg = None
                            logger.debug(f"📊 ParsingService: Прокси ID={proxy.id} - HTTP запрос успешен (предметов найдено: {result.get('total_count', 0)}, прошло фильтры: {result.get('filtered_count', 0)})")
                        
                        logger.debug(f"📊 ParsingService: Вызываем mark_proxy_used для прокси ID={proxy.id}, success={is_success}, is_429_error={is_429_error}")
                        await self.proxy_manager.mark_proxy_used(
                            proxy,
                            success=is_success,
                            error=error_msg,
                            is_429_error=is_429_error
                        )
                        logger.debug(f"✅ ParsingService: Статистика прокси ID={proxy.id} обновлена (mark_proxy_used завершен)")
                    else:
                        if not proxy:
                            logger.debug("⚠️ ParsingService: Прокси не был использован, статистика не обновляется")
                        if not self.proxy_manager:
                            logger.debug("⚠️ ParsingService: ProxyManager не инициализирован, статистика не обновляется")
                    
                    return result
            except Exception as e:
                logger.error(f"❌ ParsingService: [ШАГ 3/4] ОШИБКА при инициализации парсера: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                raise
                
        except Exception as e:
            logger.error(f"❌ ParsingService: Ошибка при парсинге предметов: {e}")
            # Отмечаем прокси как использованный с ошибкой
            if proxy and self.proxy_manager:
                logger.debug(f"📊 ParsingService: Обновляем статистику прокси ID={proxy.id}: success=False (исключение)")
                await self.proxy_manager.mark_proxy_used(
                    proxy,
                    success=False,
                    error=str(e)
                )
                logger.debug(f"✅ ParsingService: Статистика прокси ID={proxy.id} обновлена (ошибка записана)")
            
            return {
                "success": False,
                "error": str(e),
                "total_count": 0,
                "filtered_count": 0,
                "items": []
            }

