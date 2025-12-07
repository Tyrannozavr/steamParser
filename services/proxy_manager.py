"""
Менеджер прокси-серверов с ротацией и управлением задержками.
"""
import asyncio
import random
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import Proxy
from loguru import logger
from services.proxy_context import ProxyContext
from services.telegram_notifier import send_proxy_unavailable_notification


class ProxyManager:
    """Менеджер для работы с пулом прокси-серверов."""
    
    REDIS_CACHE_KEY = "proxies:active"  # Ключ для кэша в Redis
    REDIS_CACHE_TTL = 300  # TTL кэша в секундах (5 минут)
    REDIS_LAST_USED_PREFIX = "proxy:last_used:"  # Префикс для хранения времени последнего использования
    REDIS_BLOCKED_PREFIX = "proxy:blocked:"  # Префикс для временно заблокированных прокси
    REDIS_LAST_PROXY_INDEX_KEY = "proxy:last_index"  # Ключ для хранения индекса последнего использованного прокси
    REDIS_IN_USE_PREFIX = "proxy:in_use:"  # Префикс для резервирования прокси (атомарная блокировка)
    REDIS_LAST_SMART_CHECK_KEY = "proxy:last_smart_check"  # Ключ для хранения времени последней умной проверки
    
    # Настройки временной блокировки прокси с 429 ошибками
    BLOCK_DURATION_429_FIRST = 600  # Блокировка на 10 минут (600 сек) при первой 429 ошибке - Steam обычно разблокирует через 5-10 минут
    BLOCK_DURATION_429_MULTIPLE = 3600  # Блокировка на 1 час (3600 сек) при множественных 429 ошибках
    MAX_429_ERRORS_BEFORE_LONG_BLOCK = 3  # Максимум 3 подряд 429 ошибки перед длительной блокировкой
    EARLY_UNBLOCK_THRESHOLD = 300  # Если прошло 5 минут (300 сек) с момента блокировки, можно попробовать использовать прокси снова
    
    # Настройки фоновой проверки заблокированных прокси
    BACKGROUND_CHECK_INTERVAL = 300  # Проверка каждые 5 минут (300 сек) - проверяем чаще для быстрой разблокировки
    BACKGROUND_CHECK_INTERVAL_FAST = 60  # Быстрая проверка каждую минуту (60 сек) если >50% прокси заблокировано
    BACKGROUND_CHECK_TIMEOUT = 8  # Таймаout для фоновых проверок (8 сек) - быстрее
    BACKGROUND_CHECK_DELAY_BETWEEN_PROXIES = 0.5  # Минимальная задержка между группами прокси (0.5 сек)
    BLOCKED_PROXIES_THRESHOLD_FOR_FAST_CHECK = 0.5  # Если >50% прокси заблокировано, используем быструю проверку
    BACKGROUND_CHECK_MAX_CONCURRENT = 20  # Максимум 20 прокси проверяем одновременно - параллельно, как в Telegram!
    
    def __init__(self, db_session: AsyncSession, default_delay: float = 10.0, redis_service=None):
        """
        Инициализация менеджера прокси.
        
        Args:
            db_session: Сессия базы данных
            default_delay: Задержка по умолчанию между запросами (секунды)
            redis_service: Сервис Redis для кэширования (опционально)
        """
        self.db_session = db_session
        self.default_delay = default_delay
        self.redis_service = redis_service
        self._last_used: Dict[int, datetime] = {}  # Локальный кэш (fallback если Redis недоступен)
        self._blocked_proxies: Dict[int, datetime] = {}  # Локальный кэш заблокированных прокси
        self._lock = asyncio.Lock()  # Блокировка для потокобезопасности
        self._last_proxy_refresh: Optional[datetime] = None  # Время последнего обновления списка прокси
        self._proxy_refresh_interval = timedelta(minutes=5)  # Интервал обновления списка прокси
        self._background_check_task: Optional[asyncio.Task] = None  # Фоновая задача проверки прокси
        self._background_check_running = False  # Флаг работы фоновой проверки
        self._prechecked_proxies: List[Proxy] = []  # Предварительно проверенные прокси
        self._precheck_lock = asyncio.Lock()  # Блокировка для предварительной проверки
        self._precheck_batch_size = 5  # Количество прокси для предварительной проверки
        self._check_all_proxies_lock = asyncio.Lock()  # Блокировка для предотвращения множественных одновременных проверок всех прокси
        self._check_all_proxies_running = False  # Флаг выполнения проверки всех прокси
        
        # Очереди для прокси (для контроля частоты использования)
        self._proxy_queues: Dict[int, asyncio.Queue] = {}  # Очередь задач для каждого прокси
        self._proxy_queue_locks: Dict[int, asyncio.Lock] = {}  # Блокировки для очередей
        self._last_notification_time: Optional[datetime] = None  # Время последнего уведомления о недоступности прокси
        self._notification_cooldown = timedelta(minutes=30)  # Задержка между уведомлениями (30 минут)
    
    @staticmethod
    def _normalize_proxy_url(url: str) -> str:
        """
        Нормализует URL прокси для проверки уникальности.
        Убирает лишние параметры после порта и добавляет префикс http:// если нужно.
        
        Args:
            url: Исходный URL прокси
            
        Returns:
            Нормализованный URL
        """
        normalized = url.strip()
        
        # Убираем параметры после порта
        if '@' in normalized:
            # Есть авторизация: user:pass@host:port:extra
            auth_part, rest = normalized.split('@', 1)
            if ':' in rest:
                host_port_parts = rest.split(':')
                if len(host_port_parts) > 2:  # host:port:extra
                    rest = ':'.join(host_port_parts[:2])  # Берем только host:port
            normalized = f"{auth_part}@{rest}"
        else:
            # Нет авторизации: host:port:extra
            if ':' in normalized:
                parts = normalized.split(':')
                if len(parts) > 2:  # host:port:extra
                    normalized = ':'.join(parts[:2])  # Берем только host:port
        
        # Добавляем префикс http:// если его нет
        if not normalized.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
            normalized = f"http://{normalized}"
        
        return normalized
    
    async def add_proxy(self, url: str, delay: Optional[float] = None) -> Proxy:
        """
        Добавляет новый прокси в базу данных и обновляет кэш в Redis.
        Проверяет уникальность по нормализованному URL.
        
        Args:
            url: URL прокси в формате "http://user:pass@host:port"
            delay: Задержка между запросами для этого прокси
            
        Returns:
            Созданный или существующий объект Proxy
        """
        async with self._lock:
            # Нормализуем URL для проверки уникальности
            normalized_url = ProxyManager._normalize_proxy_url(url)
            
            # Проверяем, не существует ли уже такой прокси (по нормализованному URL)
            # Получаем все прокси и проверяем нормализованные URL
            result = await self.db_session.execute(
                select(Proxy)
            )
            all_proxies = result.scalars().all()
            
            for existing_proxy in all_proxies:
                existing_normalized = ProxyManager._normalize_proxy_url(existing_proxy.url)
                if existing_normalized == normalized_url:
                    logger.warning(f"⚠️ Прокси уже существует (нормализованный URL совпадает): {normalized_url} (ID: {existing_proxy.id}, оригинальный URL: {existing_proxy.url})")
                    return existing_proxy
            
            # Прокси не найден, создаем новый
            proxy = Proxy(
                url=normalized_url,  # Сохраняем нормализованный URL
                is_active=True,
                delay_seconds=delay or self.default_delay,
                success_count=0,  # Явно инициализируем статистику
                fail_count=0      # Явно инициализируем статистику
            )
            self.db_session.add(proxy)
            await self.db_session.commit()
            await self.db_session.refresh(proxy)
            
            logger.debug(f"✅ Добавлен новый прокси: {normalized_url} (ID: {proxy.id})")
            
            # Обновляем кэш в Redis
            logger.debug("🔄 ProxyManager: Обновление кэша в Redis после добавления прокси...")
            await self._update_redis_cache()
            logger.debug("✅ ProxyManager: Завершено обновление кэша в Redis")
            
            return proxy
    
    async def _get_proxies_from_redis(self) -> Optional[List[Dict]]:
        """
        Получает список прокси из Redis кэша.
        
        Returns:
            Список словарей с данными прокси или None
        """
        if not self.redis_service or not self.redis_service.is_connected():
            return None
        
        try:
            if self.redis_service._client is None:
                return None
            
            cached_data = await self.redis_service._client.get(self.REDIS_CACHE_KEY)
            if cached_data:
                proxies_data = json.loads(cached_data)
                logger.debug(f"📥 ProxyManager: Получено {len(proxies_data)} прокси из Redis кэша")
                return proxies_data
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Не удалось получить прокси из Redis: {e}")
        
        return None
    
    async def _update_redis_cache(self):
        """
        Обновляет кэш прокси в Redis.
        """
        if not self.redis_service:
            logger.debug("⚠️ ProxyManager: Redis service не инициализирован, пропускаем кэширование")
            return
        
        if not self.redis_service.is_connected():
            logger.debug("⚠️ ProxyManager: Redis не подключен, пропускаем кэширование")
            return
        
        try:
            # Получаем актуальный список из БД
            # ВАЖНО: Проверяем состояние сессии перед выполнением запроса
            try:
                # Пытаемся выполнить простой запрос для проверки состояния сессии
                await self.db_session.execute(select(1))
            except Exception:
                # Если сессия была откачена, делаем rollback
                try:
                    await self.db_session.rollback()
                    logger.debug("🔄 ProxyManager: Сессия БД откачена в _update_redis_cache, выполнен rollback")
                except Exception:
                    pass  # Игнорируем ошибки rollback
            
            result = await self.db_session.execute(
                select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)
            )
            proxies = list(result.scalars().all())
            
            # Сериализуем данные прокси
            proxies_data = [
                {
                    "id": p.id,
                    "url": p.url,
                    "is_active": p.is_active,
                    "delay_seconds": p.delay_seconds,
                    "success_count": p.success_count,
                    "fail_count": p.fail_count,
                    "last_used": p.last_used.isoformat() if p.last_used else None,
                    "last_error": p.last_error
                }
                for p in proxies
            ]
            
            # Сохраняем в Redis
            if self.redis_service._client:
                await self.redis_service._client.setex(
                    self.REDIS_CACHE_KEY,
                    self.REDIS_CACHE_TTL,
                    json.dumps(proxies_data, ensure_ascii=False)
                )
                logger.debug(f"💾 ProxyManager: Обновлен кэш в Redis ({len(proxies_data)} прокси)")
            else:
                logger.warning("⚠️ ProxyManager: Redis client не доступен")
        except Exception as e:
            logger.warning(f"⚠️ ProxyManager: Не удалось обновить кэш в Redis: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
    
    async def get_active_proxies(self, force_refresh: bool = False) -> List[Proxy]:
        """
        Получает список всех активных прокси.
        Сначала пытается получить из Redis кэша, затем из БД.
        
        Args:
            force_refresh: Принудительно обновить список из БД (игнорируя кэш)
        """
        # Пытаемся получить из Redis кэша (если не принудительное обновление)
        if not force_refresh:
            cached_proxies = await self._get_proxies_from_redis()
            if cached_proxies:
                # Восстанавливаем объекты Proxy из кэша (detached объекты)
                proxies = []
                for p_data in cached_proxies:
                    # Создаем объект Proxy без привязки к сессии (expunge)
                    proxy = Proxy(
                        id=p_data["id"],
                        url=p_data["url"],
                        is_active=p_data["is_active"],
                        delay_seconds=p_data["delay_seconds"],
                        success_count=p_data.get("success_count", 0),
                        fail_count=p_data.get("fail_count", 0),
                        last_used=datetime.fromisoformat(p_data["last_used"]) if p_data.get("last_used") else None,
                        last_error=p_data.get("last_error")
                    )
                    # Делаем объект detached (не привязан к сессии)
                    from sqlalchemy.orm import make_transient
                    make_transient(proxy)
                    proxies.append(proxy)
                
                # ВАЖНО: Исключаем временно заблокированные прокси из списка активных
                # НО: Если Redis недоступен или есть ошибки, НЕ исключаем прокси (чтобы не блокировать рабочие прокси)
                active_proxies = []
                blocked_count = 0
                redis_available = self.redis_service and self.redis_service.is_connected() and self.redis_service._client is not None
                
                logger.info(f"🔍 ProxyManager.get_active_proxies: Redis доступен: {redis_available}, всего прокси в кэше: {len(proxies)}")
                
                for proxy in proxies:
                    # Проверяем блокировку только если Redis доступен
                    if redis_available:
                        is_blocked = await self._is_proxy_temporarily_blocked(proxy.id)
                        if is_blocked:
                            blocked_count += 1
                            logger.debug(f"   🚫 Прокси ID={proxy.id}: временно заблокирован, исключаем из активных")
                        else:
                            active_proxies.append(proxy)
                            logger.debug(f"   ✅ Прокси ID={proxy.id}: активен и не заблокирован")
                    else:
                        # Redis недоступен - включаем все активные прокси (чтобы не блокировать рабочие прокси)
                        active_proxies.append(proxy)
                        logger.debug(f"   ⚠️ Redis недоступен, включаем прокси ID={proxy.id} в активные (без проверки блокировки)")
                
                if redis_available:
                    logger.info(f"✅ ProxyManager: Использован кэш из Redis ({len(proxies)} прокси, из них {blocked_count} заблокированы, доступно {len(active_proxies)})")
                else:
                    logger.warning(f"⚠️ ProxyManager: Redis недоступен, используем все {len(proxies)} прокси из кэша без проверки блокировок")
                
                # ВАЖНО: Если после фильтрации не осталось прокси - это проблема, но НЕ используем заблокированные
                if len(active_proxies) == 0 and len(proxies) > 0:
                    logger.error(f"❌ ProxyManager: Все {len(proxies)} прокси из кэша заблокированы!")
                    logger.error(f"   Заблокировано: {blocked_count} из {len(proxies)}")
                    logger.debug(f"   🔍 DEBUG: Redis доступен: {redis_available}")
                    
                    # ВАЖНО: Запускаем проверку прокси в ФОНЕ, чтобы не блокировать другие задачи
                    # Проверка может занять 45+ секунд, поэтому не ждем её завершения
                    async def background_check_proxies():
                        """Фоновая проверка всех прокси для разблокировки."""
                        try:
                            logger.warning(f"   🔄 Запускаем фоновую проверку всех прокси для разблокировки...")
                            check_result = await self.check_all_proxies_parallel(
                                max_concurrent=20,
                                update_redis_status=True  # Обновляем статусы в Redis (разблокируем работающие)
                            )
                            working_after_check = check_result.get('working', 0)
                            unblocked = check_result.get('unblocked_count', 0)
                            rate_limited = check_result.get('rate_limited', 0)
                            
                            logger.info(f"📊 ProxyManager: Результаты фоновой проверки всех прокси:")
                            logger.info(f"   ✅ Работающих: {working_after_check}")
                            logger.info(f"   🚫 Rate limited (429): {rate_limited}")
                            logger.info(f"   🔓 Разблокировано в Redis: {unblocked}")
                            
                            if working_after_check > 0:
                                logger.info(f"✅ ProxyManager: После проверки найдено {working_after_check} работающих прокси, разблокировано в Redis: {unblocked}")
                                # Обновляем кэш
                                await self._update_redis_cache()
                            else:
                                logger.warning(f"⚠️ ProxyManager: После проверки не найдено работающих прокси.")
                                logger.warning(f"   🔍 Все {len(proxies)} прокси rate limited (429) - Steam временно блокирует все прокси")
                        except Exception as check_error:
                            logger.error(f"❌ ProxyManager: Ошибка при фоновой проверке прокси: {check_error}")
                            import traceback
                            logger.error(f"   Traceback: {traceback.format_exc()}")
                        finally:
                            # ВАЖНО: Сбрасываем флаг после завершения проверки
                            self._check_all_proxies_running = False
                            logger.debug(f"   ✅ Фоновая проверка прокси завершена, флаг сброшен")
                    
                    # Запускаем проверку в фоне, если она еще не запущена
                    if not self._check_all_proxies_running:
                        try:
                            # Проверяем, не запущена ли уже проверка
                            async with self._check_all_proxies_lock:
                                if not self._check_all_proxies_running:
                                    self._check_all_proxies_running = True
                                    asyncio.create_task(background_check_proxies())
                                    logger.debug(f"   ✅ Фоновая проверка прокси запущена")
                        except Exception as bg_error:
                            logger.warning(f"⚠️ ProxyManager: Не удалось запустить фоновую проверку прокси: {bg_error}")
                    
                    logger.warning(f"   ⚠️ Система будет ждать разблокировки прокси. НЕ используем заблокированные прокси - это приведет к постоянным 429 ошибкам!")
                    # НЕ используем заблокированные прокси - это приведет к постоянным 429 ошибкам
                    # Система должна ждать разблокировки или использовать только незаблокированные прокси
                
                return active_proxies
        
        # Если кэш не доступен или force_refresh, получаем из БД
        try:
            # Проверяем состояние сессии и делаем rollback при необходимости
            try:
                # Пытаемся выполнить простой запрос для проверки состояния сессии
                await self.db_session.execute(select(1))
            except Exception:
                # Если сессия была откачена, делаем rollback
                try:
                    await self.db_session.rollback()
                    logger.debug("🔄 ProxyManager: Сессия БД откачена, выполнен rollback")
                except Exception:
                    pass  # Игнорируем ошибки rollback
            
            result = await self.db_session.execute(
                select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)
            )
            proxies = list(result.scalars().all())
            logger.info(f"📊 ProxyManager: Получено {len(proxies)} активных прокси из БД (force_refresh={force_refresh})")
        except Exception as e:
            logger.error(f"❌ ProxyManager: Ошибка при получении прокси из БД: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Пытаемся откатить транзакцию
            try:
                await self.db_session.rollback()
            except Exception:
                pass
            # Возвращаем пустой список
            proxies = []
        
        self._last_proxy_refresh = datetime.now()
        
        # Обновляем кэш в Redis
        await self._update_redis_cache()
        
        # ВАЖНО: Исключаем временно заблокированные прокси из списка активных
        # НО: Если Redis недоступен или есть ошибки, НЕ исключаем прокси (чтобы не блокировать рабочие прокси)
        active_proxies = []
        blocked_count = 0
        redis_available = self.redis_service and self.redis_service.is_connected() and self.redis_service._client is not None
        
        for proxy in proxies:
            # Проверяем блокировку только если Redis доступен
            if redis_available:
                is_blocked = await self._is_proxy_temporarily_blocked(proxy.id)
                if is_blocked:
                    blocked_count += 1
                    logger.debug(f"   🚫 Прокси ID={proxy.id}: временно заблокирован, исключаем из активных")
                else:
                    active_proxies.append(proxy)
            else:
                # Redis недоступен - включаем все активные прокси (чтобы не блокировать рабочие прокси)
                active_proxies.append(proxy)
                logger.debug(f"   ⚠️ Redis недоступен, включаем прокси ID={proxy.id} в активные (без проверки блокировки)")
        
        # Логируем обновление списка прокси
        if proxies:
            if redis_available:
                logger.info(f"🔄 ProxyManager: Обновлен список прокси из БД. Найдено {len(proxies)} активных, из них {blocked_count} заблокированы, доступно {len(active_proxies)}")
            else:
                logger.warning(f"⚠️ ProxyManager: Redis недоступен, используем все {len(proxies)} активных прокси без проверки блокировок")
            for p in active_proxies[:5]:  # Показываем только первые 5 для краткости
                logger.debug(f"   - Прокси ID={p.id}: {p.url[:50]}...")
            if len(active_proxies) > 5:
                logger.debug(f"   ... и еще {len(active_proxies) - 5} прокси")
            
                # ВАЖНО: Если после фильтрации не осталось прокси - это проблема, но НЕ используем заблокированные
                if len(active_proxies) == 0 and len(proxies) > 0:
                    logger.error(f"❌ ProxyManager: КРИТИЧЕСКАЯ ПРОБЛЕМА! Все {len(proxies)} прокси исключены как заблокированные!")
                    logger.debug(f"   Redis доступен: {redis_available}")
                    logger.error(f"   Заблокировано: {blocked_count} из {len(proxies)}")
                    
                    # ВАЖНО: Запускаем проверку прокси в ФОНЕ, чтобы не блокировать другие задачи
                    async def background_check_proxies():
                        """Фоновая проверка всех прокси для разблокировки."""
                        try:
                            logger.warning(f"   🔄 Запускаем фоновую проверку всех прокси для разблокировки...")
                            check_result = await self.check_all_proxies_parallel(
                                max_concurrent=20,
                                update_redis_status=True  # Обновляем статусы в Redis (разблокируем работающие)
                            )
                            working_after_check = check_result.get('working', 0)
                            unblocked = check_result.get('unblocked_count', 0)
                            
                            logger.info(f"📊 ProxyManager: Результаты фоновой проверки всех прокси:")
                            logger.info(f"   ✅ Работающих: {working_after_check}")
                            logger.info(f"   🔓 Разблокировано в Redis: {unblocked}")
                            
                            if working_after_check > 0:
                                logger.info(f"✅ ProxyManager: После проверки найдено {working_after_check} работающих прокси, разблокировано в Redis: {unblocked}")
                                # Обновляем кэш
                                await self._update_redis_cache()
                            else:
                                logger.warning(f"⚠️ ProxyManager: После проверки не найдено работающих прокси.")
                        except Exception as check_error:
                            logger.error(f"❌ ProxyManager: Ошибка при фоновой проверке прокси: {check_error}")
                            import traceback
                            logger.debug(f"Traceback: {traceback.format_exc()}")
                        finally:
                            # ВАЖНО: Сбрасываем флаг после завершения проверки
                            self._check_all_proxies_running = False
                            logger.debug(f"   ✅ Фоновая проверка прокси завершена, флаг сброшен")
                    
                    # Запускаем проверку в фоне, если она еще не запущена
                    if not self._check_all_proxies_running:
                        try:
                            # Проверяем, не запущена ли уже проверка
                            async with self._check_all_proxies_lock:
                                if not self._check_all_proxies_running:
                                    self._check_all_proxies_running = True
                                    asyncio.create_task(background_check_proxies())
                                    logger.debug(f"   ✅ Фоновая проверка прокси запущена")
                        except Exception as bg_error:
                            logger.warning(f"⚠️ ProxyManager: Не удалось запустить фоновую проверку прокси: {bg_error}")
                    
                    logger.warning(f"   ⚠️ Система будет ждать разблокировки прокси. НЕ используем заблокированные прокси - это приведет к постоянным 429 ошибкам!")
                    # НЕ используем заблокированные прокси - это приведет к постоянным 429 ошибкам и замедлению работы
                    # Система должна ждать разблокировки или использовать только незаблокированные прокси
        else:
            logger.warning("⚠️ ProxyManager: В БД нет активных прокси")
        
        return active_proxies
    
    async def _get_proxy_last_used_from_db(self, proxy_id: int) -> Optional[datetime]:
        """
        Получает время последнего использования прокси из БД.
        
        Args:
            proxy_id: ID прокси
            
        Returns:
            datetime или None если не найдено
        """
        # Сначала проверяем локальный кэш (быстрее)
        if proxy_id in self._last_used:
            return self._last_used[proxy_id]
        
        try:
            # Получаем прокси из БД
            from core import Proxy
            result = await self.db_session.execute(
                select(Proxy).where(Proxy.id == proxy_id)
            )
            proxy = result.scalar_one_or_none()
            
            if proxy and proxy.last_used:
                # Обновляем локальный кэш
                self._last_used[proxy_id] = proxy.last_used
                return proxy.last_used
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при получении времени использования прокси {proxy_id} из БД: {e}")
        
        # Fallback на локальный кэш
        return self._last_used.get(proxy_id)
    
    async def _reserve_proxy(self, proxy_id: int, ttl: int = 300) -> bool:
        """
        Атомарно резервирует прокси в Redis (SET NX).
        Предотвращает использование одного прокси несколькими задачами одновременно.
        
        Args:
            proxy_id: ID прокси
            ttl: Время жизни резервирования в секундах (по умолчанию 5 минут)
            
        Returns:
            True если прокси успешно зарезервирован, False если уже используется
        """
        if not self.redis_service or not self.redis_service.is_connected():
            # Если Redis недоступен, разрешаем использование (fallback)
            return True
        
        try:
            if self.redis_service._client is None:
                return True
            
            key = f"{self.REDIS_IN_USE_PREFIX}{proxy_id}"
            # Атомарная операция SET NX EX - устанавливает ключ только если его нет
            result = await self.redis_service._client.set(key, "1", nx=True, ex=ttl)
            return result is True
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при резервировании прокси {proxy_id} в Redis: {e}")
            # При ошибке разрешаем использование (fallback)
            return True
    
    async def _release_proxy(self, proxy_id: int):
        """
        Освобождает резервирование прокси в Redis.
        
        Args:
            proxy_id: ID прокси
        """
        if not self.redis_service or not self.redis_service.is_connected():
            return
        
        try:
            if self.redis_service._client is None:
                return
            
            key = f"{self.REDIS_IN_USE_PREFIX}{proxy_id}"
            await self.redis_service._client.delete(key)
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при освобождении прокси {proxy_id} в Redis: {e}")
    
    async def _is_proxy_in_use(self, proxy_id: int) -> bool:
        """
        Проверяет, используется ли прокси прямо сейчас (зарезервирован).
        
        Args:
            proxy_id: ID прокси
            
        Returns:
            True если прокси используется, False если свободен
        """
        if not self.redis_service or not self.redis_service.is_connected():
            return False
        
        try:
            if self.redis_service._client is None:
                return False
            
            key = f"{self.REDIS_IN_USE_PREFIX}{proxy_id}"
            result = await self.redis_service._client.get(key)
            return result is not None
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при проверке использования прокси {proxy_id} в Redis: {e}")
            return False
    
    async def _set_proxy_last_used_in_db(self, proxy_id: int, timestamp: datetime):
        """
        Сохраняет время последнего использования прокси в БД.
        
        Args:
            proxy_id: ID прокси
            timestamp: Время использования
        """
        try:
            # Обновляем в БД
            from core import Proxy
            from sqlalchemy import update
            
            await self.db_session.execute(
                update(Proxy)
                .where(Proxy.id == proxy_id)
                .values(last_used=timestamp, updated_at=datetime.now())
            )
            await self.db_session.commit()
            
            # Обновляем локальный кэш
            self._last_used[proxy_id] = timestamp
            logger.debug(f"💾 ProxyManager: Сохранено время использования прокси {proxy_id} в БД: {timestamp}")
        except Exception as e:
            logger.warning(f"⚠️ ProxyManager: Ошибка при сохранении времени использования прокси {proxy_id} в БД: {e}")
            # Fallback на локальный кэш
            self._last_used[proxy_id] = timestamp
            try:
                await self.db_session.rollback()
            except Exception:
                pass
    
    async def _get_last_proxy_index(self) -> Optional[int]:
        """
        Получает индекс последнего использованного прокси из Redis.
        
        Returns:
            Индекс прокси или None если не найдено
        """
        if not self.redis_service or not self.redis_service.is_connected():
            return None
        
        try:
            if self.redis_service._client is None:
                return None
            
            index_str = await self.redis_service._client.get(self.REDIS_LAST_PROXY_INDEX_KEY)
            if index_str:
                return int(index_str)
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при получении индекса последнего прокси из Redis: {e}")
        
        return None
    
    async def _set_last_proxy_index(self, index: int):
        """
        Сохраняет индекс последнего использованного прокси в Redis.
        
        Args:
            index: Индекс прокси
        """
        if not self.redis_service or not self.redis_service.is_connected():
            return
        
        try:
            if self.redis_service._client is None:
                return
            
            # Сохраняем без TTL (храним постоянно)
            await self.redis_service._client.set(self.REDIS_LAST_PROXY_INDEX_KEY, str(index))
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при сохранении индекса последнего прокси в Redis: {e}")
    
    async def _is_proxy_temporarily_blocked(self, proxy_id: int) -> bool:
        """
        Проверяет, заблокирован ли прокси временно из-за 429 ошибок.
        Проверяет поле blocked_until в БД.
        
        Args:
            proxy_id: ID прокси
            
        Returns:
            True если прокси заблокирован, False если доступен
        """
        # Сначала проверяем локальный кэш (быстрее)
        if proxy_id in self._blocked_proxies:
            blocked_until = self._blocked_proxies[proxy_id]
            now = datetime.now()
            if now < blocked_until:
                return True
            else:
                # Блокировка истекла в локальном кэше, очищаем в БД
                del self._blocked_proxies[proxy_id]
                try:
                    from core import Proxy
                    from sqlalchemy import update
                    await self.db_session.execute(
                        update(Proxy)
                        .where(Proxy.id == proxy_id)
                        .values(blocked_until=None, updated_at=now)
                    )
                    await self.db_session.commit()
                except Exception:
                    try:
                        await self.db_session.rollback()
                    except Exception:
                        pass
        
        try:
            # Проверяем в БД
            from core import Proxy
            result = await self.db_session.execute(
                select(Proxy).where(Proxy.id == proxy_id)
            )
            proxy = result.scalar_one_or_none()
            
            if proxy and proxy.blocked_until:
                now = datetime.now()
                if now < proxy.blocked_until:
                    # Проверяем, можно ли использовать прокси раньше (ранняя разблокировка)
                    # Если прошло больше EARLY_UNBLOCK_THRESHOLD секунд с момента блокировки, можно попробовать
                    time_blocked = (now - (proxy.blocked_until - timedelta(seconds=self.BLOCK_DURATION_429_FIRST if proxy.fail_count < self.MAX_429_ERRORS_BEFORE_LONG_BLOCK else self.BLOCK_DURATION_429_MULTIPLE))).total_seconds()
                    if time_blocked >= self.EARLY_UNBLOCK_THRESHOLD:
                        # Прошло достаточно времени - разрешаем использовать прокси (ранняя разблокировка)
                        logger.debug(f"🔓 ProxyManager: Прокси ID={proxy_id} доступен для ранней разблокировки (заблокирован {int(time_blocked/60)} мин назад)")
                        return False
                    # Обновляем локальный кэш
                    self._blocked_proxies[proxy_id] = proxy.blocked_until
                    logger.debug(f"🔒 ProxyManager: Прокси ID={proxy_id} заблокирован до {proxy.blocked_until}")
                    return True
                else:
                    # Блокировка истекла, очищаем в БД
                    from sqlalchemy import update
                    await self.db_session.execute(
                        update(Proxy)
                        .where(Proxy.id == proxy_id)
                        .values(blocked_until=None, updated_at=now)
                    )
                    await self.db_session.commit()
                    if proxy_id in self._blocked_proxies:
                        del self._blocked_proxies[proxy_id]
                    logger.debug(f"🔓 ProxyManager: Блокировка прокси ID={proxy_id} истекла, очищена в БД")
            
            return False
        except Exception as e:
            # ВАЖНО: При любой ошибке считаем прокси НЕ заблокированным
            # Это позволяет использовать рабочие прокси даже если БД недоступна
            logger.debug(f"⚠️ ProxyManager: Ошибка при проверке блокировки прокси {proxy_id}: {e}, считаем прокси доступным")
            try:
                await self.db_session.rollback()
            except Exception:
                pass
            return False
    
    async def _block_proxy_temporarily(self, proxy_id: int, duration_seconds: int = None):
        """
        Временно блокирует прокси из-за 429 ошибок.
        Сохраняет blocked_until в БД.
        
        Args:
            proxy_id: ID прокси
            duration_seconds: Длительность блокировки в секундах (по умолчанию BLOCK_DURATION_429_FIRST)
        """
        duration = duration_seconds or self.BLOCK_DURATION_429_FIRST
        blocked_until = datetime.now() + timedelta(seconds=duration)
        
        logger.warning(f"🚫 ProxyManager: Временно блокируем прокси ID={proxy_id} на {duration//60} мин из-за 429 ошибок")
        
        try:
            # Сохраняем в БД
            from core import Proxy
            from sqlalchemy import update
            
            await self.db_session.execute(
                update(Proxy)
                .where(Proxy.id == proxy_id)
                .values(blocked_until=blocked_until, updated_at=datetime.now())
            )
            await self.db_session.commit()
            logger.info(f"✅ ProxyManager: Прокси ID={proxy_id} заблокирован в БД до {blocked_until.isoformat()}")
        except Exception as e:
            logger.error(f"❌ ProxyManager: Ошибка при блокировке прокси {proxy_id} в БД: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            try:
                await self.db_session.rollback()
            except Exception:
                pass
        
        # Обновляем локальный кэш
        self._blocked_proxies[proxy_id] = blocked_until
    
    async def _unblock_proxy(self, proxy_id: int):
        """
        Разблокирует прокси (при успешном запросе).
        Очищает blocked_until в БД.
        
        Args:
            proxy_id: ID прокси
        """
        try:
            # Очищаем в БД
            from core import Proxy
            from sqlalchemy import update
            
            await self.db_session.execute(
                update(Proxy)
                .where(Proxy.id == proxy_id)
                .values(blocked_until=None, updated_at=datetime.now())
            )
            await self.db_session.commit()
            logger.debug(f"🔓 ProxyManager: Прокси ID={proxy_id} разблокирован в БД")
        except Exception as e:
            logger.debug(f"⚠️ ProxyManager: Ошибка при разблокировке прокси {proxy_id} в БД: {e}")
            try:
                await self.db_session.rollback()
            except Exception:
                pass
        
        # Удаляем из локального кэша
        if proxy_id in self._blocked_proxies:
            del self._blocked_proxies[proxy_id]
        
        logger.info(f"✅ ProxyManager: Прокси ID={proxy_id} разблокирован (успешный запрос)")
        
        # ВАЖНО: Обновляем кэш в Redis, чтобы актуальные данные были доступны
        await self._update_redis_cache()
    
    async def get_next_proxy(self, min_delay: float = 0.0, force_refresh: bool = False, skip_delay: bool = False, precheck: bool = False) -> Optional[Proxy]:
        """
        Получает следующий доступный прокси с последовательной ротацией.
        Использует следующий прокси после последнего использованного (по индексу).
        Оптимизирован для быстрого переключения при 429 ошибках.
        
        Args:
            min_delay: Минимальная задержка с момента последнего использования
            force_refresh: Принудительно обновить список прокси из БД
            skip_delay: Пропустить проверку задержки (для быстрого переключения при 429)
            precheck: Предварительно проверить несколько прокси параллельно (для надежности)
            
        Returns:
            Proxy или None, если нет доступных прокси
        """
        async with self._lock:
            # Всегда обновляем список прокси при запросе (для актуальности)
            proxies = await self.get_active_proxies(force_refresh=force_refresh)
            
            if not proxies:
                logger.error("❌ ProxyManager.get_next_proxy: Нет активных прокси в базе данных")
                logger.error("   Это может быть из-за:")
                logger.error("   1. Все прокси заблокированы (429 ошибки)")
                logger.error("   2. Все прокси деактивированы")
                logger.error("   3. В базе данных нет прокси")
                logger.warning("   🔄 ProxyManager должен автоматически проверить все прокси и разблокировать работающие")
                logger.warning("   💡 Добавьте прокси через команду /add_proxy в Telegram боте")
                return None
            
            logger.debug(f"🔍 ProxyManager: Найдено {len(proxies)} активных прокси (ID: {[p.id for p in proxies]})")
            
            # Получаем индекс последнего использованного прокси из Redis
            last_index = await self._get_last_proxy_index()
            
            # Начинаем с следующего индекса
            start_index = (last_index + 1) % len(proxies) if last_index is not None else 0
            
            now = datetime.now()
            checked_count = 0
            
            # Если skip_delay=True (быстрое переключение при 429), просто берем следующий прокси без проверки задержки
            if skip_delay:
                # Пробуем найти свободный прокси (не используемый другой задачей)
                for i in range(len(proxies)):
                    current_index = (start_index + i) % len(proxies)
                    proxy = proxies[current_index]
                    # Проверяем, не используется ли прокси
                    if not await self._is_proxy_in_use(proxy.id):
                        if await self._reserve_proxy(proxy.id):
                            logger.info(f"⚡ ProxyManager: Быстрое переключение - выбран прокси ID={proxy.id} (индекс {current_index}, пропущена проверка задержки)")
                            await self._set_last_proxy_index(current_index)
                            return proxy
                # Если все прокси заняты, берем первый доступный
                current_index = start_index
                proxy = proxies[current_index]
                if await self._reserve_proxy(proxy.id):
                    logger.info(f"⚡ ProxyManager: Быстрое переключение - выбран прокси ID={proxy.id} (индекс {current_index}, пропущена проверка задержки)")
                    await self._set_last_proxy_index(current_index)
                    return proxy
                else:
                    logger.warning(f"⚠️ ProxyManager: Не удалось зарезервировать прокси ID={proxy.id} даже при быстром переключении")
                    return None
            
            # Если precheck=True, предварительно проверяем несколько прокси параллельно
            if precheck and len(proxies) > 1:
                precheck_count = min(self._precheck_batch_size, len(proxies))
                precheck_proxies = []
                for i in range(precheck_count):
                    idx = (start_index + i) % len(proxies)
                    precheck_proxies.append(proxies[idx])
                
                logger.debug(f"🔍 ProxyManager: Предварительная проверка {precheck_count} прокси параллельно")
                tasks = [self._check_single_proxy_background(p) for p in precheck_proxies]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Ищем первый рабочий прокси
                for proxy, result in zip(precheck_proxies, results):
                    if not isinstance(result, Exception) and result:
                        # Прокси работает
                        proxy_index = proxies.index(proxy)
                        await self._set_last_proxy_index(proxy_index)
                        logger.info(f"✅ ProxyManager: Предварительная проверка - выбран рабочий прокси ID={proxy.id}")
                        return proxy
                
                logger.debug(f"⚠️ ProxyManager: Предварительная проверка - все {precheck_count} прокси заблокированы, используем обычную логику")
            
            # Проверяем прокси по кругу, начиная со следующего после последнего использованного
            for i in range(len(proxies)):
                current_index = (start_index + i) % len(proxies)
                proxy = proxies[current_index]
                checked_count += 1
                
                # ВАЖНО: Проверяем, не истекла ли блокировка прокси (автоматическая разблокировка)
                if await self._is_proxy_temporarily_blocked(proxy.id):
                    # Прокси заблокирован, пропускаем
                    continue
                
                # Проверяем задержку
                last_used = await self._get_proxy_last_used_from_db(proxy.id)
                
                # ВАЖНО: Проверяем, не используется ли прокси прямо сейчас (атомарная блокировка)
                is_in_use = await self._is_proxy_in_use(proxy.id)
                if is_in_use:
                    logger.debug(f"   Прокси ID={proxy.id} (индекс {current_index}): используется другой задачей, пропускаем")
                    continue
                
                if last_used is None:
                    # Прокси еще не использовался - доступен, резервируем его
                    if await self._reserve_proxy(proxy.id):
                        logger.debug(f"✅ ProxyManager: Выбран прокси ID={proxy.id} (индекс {current_index}, еще не использовался)")
                        await self._set_last_proxy_index(current_index)
                        return proxy
                    else:
                        logger.debug(f"   Прокси ID={proxy.id} (индекс {current_index}): не удалось зарезервировать (взял другой процесс)")
                        continue
                else:
                    # Проверяем, прошло ли достаточно времени
                    time_since_use = (now - last_used).total_seconds()
                    required_delay = max(proxy.delay_seconds, min_delay)
                    
                    if time_since_use >= required_delay:
                        # Прокси доступен, резервируем его
                        if await self._reserve_proxy(proxy.id):
                            logger.debug(f"✅ ProxyManager: Выбран прокси ID={proxy.id} (индекс {current_index}, прошло {time_since_use:.1f}с, требуется {required_delay:.1f}с)")
                            await self._set_last_proxy_index(current_index)
                            return proxy
                        else:
                            logger.debug(f"   Прокси ID={proxy.id} (индекс {current_index}): не удалось зарезервировать (взял другой процесс)")
                            continue
                    else:
                        wait_needed = required_delay - time_since_use
                        logger.debug(f"   Прокси ID={proxy.id} (индекс {current_index}): занят (нужно подождать {wait_needed:.1f}с)")
            
            # Все прокси заняты, выбираем тот, у которого наименьшая задержка
            logger.debug(f"⚠️ ProxyManager: Все прокси заняты, выбираем с наименьшей задержкой")
            proxies_sorted = sorted(proxies, key=lambda p: p.delay_seconds)
            selected_proxy = proxies_sorted[0]
            
            # Находим индекс выбранного прокси
            selected_index = next((i for i, p in enumerate(proxies) if p.id == selected_proxy.id), 0)
            await self._set_last_proxy_index(selected_index)
            
            last_used = await self._get_proxy_last_used_from_db(selected_proxy.id)
            wait_time = 0
            if last_used:
                time_since_use = (now - last_used).total_seconds()
                required_delay = max(selected_proxy.delay_seconds, min_delay)
                wait_time = required_delay - time_since_use
                if wait_time > 0:
                    logger.debug(f"⏳ ProxyManager: Нужно подождать {wait_time:.2f} сек перед использованием прокси ID={selected_proxy.id}")
            
            # ВАЖНО: Освобождаем блокировку перед ожиданием, чтобы другие задачи могли получить прокси
            # Ожидание может быть долгим (до нескольких минут), поэтому не блокируем другие задачи
        
        # Ожидаем вне блокировки, чтобы не блокировать другие задачи
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        
        # Снова захватываем блокировку для резервирования прокси
        async with self._lock:
            # Проверяем, что прокси все еще доступен (может быть взят другой задачей)
            proxies = await self.get_active_proxies(force_refresh=False)
            # Ищем выбранный прокси в обновленном списке
            proxy = next((p for p in proxies if p.id == selected_proxy.id), None)
            if not proxy:
                logger.debug(f"⚠️ ProxyManager: Прокси ID={selected_proxy.id} больше не доступен, пробуем следующий")
                return await self.get_next_proxy(min_delay=min_delay, force_refresh=False, skip_delay=False, precheck=False)
            
            # Резервируем прокси перед возвратом
            if await self._reserve_proxy(proxy.id):
                logger.debug(f"✅ ProxyManager: Выбран прокси ID={proxy.id} (после ожидания, delay={proxy.delay_seconds:.1f}с)")
                return proxy
            else:
                logger.debug(f"⚠️ ProxyManager: Не удалось зарезервировать прокси ID={proxy.id} (взял другой процесс), пробуем следующий")
                # Пробуем следующий прокси (рекурсивно, но с ограничением глубины)
                return await self.get_next_proxy(min_delay=min_delay, force_refresh=False, skip_delay=False, precheck=False)
    
    async def mark_proxy_used(self, proxy: Proxy, success: bool = True, error: Optional[str] = None, is_429_error: bool = False):
        """
        Отмечает прокси как использованный.
        Сохраняет время использования в Redis.
        
        Args:
            proxy: Объект Proxy (может быть detached)
            success: Успешен ли запрос
            error: Текст ошибки (если запрос неудачен)
        """
        try:
            async with self._lock:
                # НЕ проверяем состояние транзакции - это вызывает конфликты при параллельном парсинге
                # Просто обновляем объект в памяти, изменения будут сохранены при основном commit()
                
                now = datetime.now()
                # ВАЖНО: Освобождаем резервирование прокси перед обновлением времени использования
                await self._release_proxy(proxy.id)
                # Сохраняем время использования в БД
                await self._set_proxy_last_used_in_db(proxy.id, now)
                
                # Работаем напрямую с переданным объектом proxy (без db_session.get())
                # Это избегает конфликтов с параллельным парсингом
                # Сохраняем старые значения для логирования
                old_success = proxy.success_count
                old_fail = proxy.fail_count
                
                # Обновляем статистику в объекте
                if success:
                    proxy.success_count += 1
                    logger.debug(f"📈 ProxyManager: Прокси ID={proxy.id} - успешный запрос (было: успешно={old_success}, ошибок={old_fail} → стало: успешно={proxy.success_count}, ошибок={proxy.fail_count})")
                    # При успешном запросе разблокируем прокси (если был заблокирован)
                    await self._unblock_proxy(proxy.id)
                else:
                    proxy.fail_count += 1
                    if error:
                        proxy.last_error = error
                    logger.warning(f"📉 ProxyManager: Прокси ID={proxy.id} - ошибка запроса (было: успешно={old_success}, ошибок={old_fail} → стало: успешно={proxy.success_count}, ошибок={proxy.fail_count})")
                    if error:
                        logger.debug(f"   Текст ошибки: {error[:200]}")
                    
                    # Используем переданный параметр is_429_error или проверяем текст ошибки
                    if not is_429_error and error:
                        error_str = str(error)
                        is_429_error = '429' in error_str or 'Too Many Requests' in error_str
                    
                    if is_429_error:
                        # Для 429 ошибок: блокируем прокси сразу при первой ошибке на короткое время
                        # При множественных ошибках - на длительное время
                        last_error = proxy.last_error or ""
                        is_recent_429 = "429" in str(last_error) or "Too Many Requests" in str(last_error)
                        
                        if proxy.fail_count >= self.MAX_429_ERRORS_BEFORE_LONG_BLOCK and is_recent_429:
                            # Множественные 429 ошибки - длительная блокировка
                            await self._block_proxy_temporarily(proxy.id, self.BLOCK_DURATION_429_MULTIPLE)
                            logger.warning(f"🚫 ProxyManager: Прокси ID={proxy.id} временно заблокирован на {self.BLOCK_DURATION_429_MULTIPLE//60} мин из-за множественных 429 ошибок")
                        else:
                            # Первая 429 ошибка - короткая блокировка
                            await self._block_proxy_temporarily(proxy.id, self.BLOCK_DURATION_429_FIRST)
                            logger.warning(f"🚫 ProxyManager: Прокси ID={proxy.id} временно заблокирован на {self.BLOCK_DURATION_429_FIRST//60} мин из-за 429 ошибки")
                    else:
                        # Для других ошибок: увеличиваем задержку
                        if proxy.delay_seconds < 20.0:
                            old_delay = proxy.delay_seconds
                            # Увеличиваем задержку на 1.0 сек за ошибку, но не более 20 сек
                            proxy.delay_seconds = min(proxy.delay_seconds + 1.0, 20.0)
                            logger.debug(f"⏱️ ProxyManager: Увеличена задержка для прокси ID={proxy.id}: {old_delay:.1f}с → {proxy.delay_seconds:.1f}с (из-за ошибки)")
                    
                    # Если успешных запросов больше ошибок, постепенно уменьшаем задержку
                    if proxy.success_count > proxy.fail_count and proxy.delay_seconds > self.default_delay:
                        old_delay = proxy.delay_seconds
                        # Уменьшаем задержку на 0.1 сек за каждые 5 успешных запросов
                        if proxy.success_count % 5 == 0:
                            proxy.delay_seconds = max(proxy.delay_seconds - 0.1, self.default_delay)
                            logger.debug(f"⏱️ ProxyManager: Уменьшена задержка для прокси ID={proxy.id}: {old_delay:.1f}с → {proxy.delay_seconds:.1f}с (после успешных запросов)")
                
                proxy.last_used = now
                
                # Деактивируем прокси, если слишком много ошибок
                # ВАЖНО: Не деактивируем при 429 ошибках (rate limited) - это временная блокировка Steam
                # Деактивируем только при реальных ошибках прокси (timeout, connection error и т.д.)
                # Проверяем, что ошибок больше успешных в 3 раза (было 2), чтобы не деактивировать из-за 429
                if proxy.fail_count > 20 and proxy.fail_count > proxy.success_count * 3:
                    # Дополнительная проверка: если последняя ошибка не 429, то деактивируем
                    last_error = proxy.last_error or ""
                    if "429" not in str(last_error) and "Too Many Requests" not in str(last_error):
                        proxy.is_active = False
                        logger.warning(f"⚠️ ProxyManager: Прокси {proxy.id} деактивирован из-за большого количества ошибок (успешно={proxy.success_count}, ошибок={proxy.fail_count}, последняя ошибка: {last_error[:100]})")
                    else:
                        logger.debug(f"ℹ️ ProxyManager: Прокси {proxy.id} имеет много 429 ошибок, но не деактивируется (это временная блокировка Steam)")
                
                # НЕ делаем commit() или flush() здесь - это должно быть сделано в основном потоке
                # Просто обновляем объект в памяти, изменения будут сохранены при основном commit()
                logger.debug(f"✅ ProxyManager: Статистика прокси ID={proxy.id} обновлена в памяти (успешно={proxy.success_count}, ошибок={proxy.fail_count})")
                
                # Обновляем кэш в Redis (чтобы актуальные данные были в кэше)
                await self._update_redis_cache()
        except Exception as e:
            logger.error(f"❌ ProxyManager: Ошибка при обновлении статистики прокси ID={proxy.id}: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            # Пытаемся откатить транзакцию
            try:
                await self.db_session.rollback()
            except:
                pass
    
    async def check_all_proxies_parallel(self, max_concurrent: int = 15, update_redis_status: bool = False) -> Dict[str, any]:
        """
        Быстрая параллельная проверка всех активных прокси.
        ВАЖНО: Использует блокировку для предотвращения множественных одновременных проверок.
        
        Args:
            max_concurrent: Максимальное количество одновременных проверок
            update_redis_status: Если True, обновляет статусы в Redis (блокирует rate_limited, разблокирует работающие)
            
        Returns:
            Dict с результатами проверки всех прокси
        """
        # Проверяем, не выполняется ли уже проверка
        if self._check_all_proxies_running:
            logger.debug(f"⏳ ProxyManager: Проверка всех прокси уже выполняется, ожидаем завершения...")
            # Ждем завершения текущей проверки (максимум 60 секунд)
            wait_timeout = 60
            start_wait = datetime.now()
            while self._check_all_proxies_running and (datetime.now() - start_wait).total_seconds() < wait_timeout:
                await asyncio.sleep(0.5)
            
            if self._check_all_proxies_running:
                logger.warning(f"⚠️ ProxyManager: Проверка всех прокси все еще выполняется после ожидания, возвращаем пустой результат")
                return {"total": 0, "working": 0, "blocked": 0, "error": 0, "rate_limited": 0, "blocked_count": 0, "unblocked_count": 0, "results": []}
        
        # Блокируем выполнение проверки
        async with self._check_all_proxies_lock:
            if self._check_all_proxies_running:
                logger.debug(f"⏳ ProxyManager: Проверка всех прокси уже выполняется другим потоком, пропускаем")
                return {"total": 0, "working": 0, "blocked": 0, "error": 0, "rate_limited": 0, "blocked_count": 0, "unblocked_count": 0, "results": []}
            
            self._check_all_proxies_running = True
            logger.info(f"🚀 Начинаем параллельную проверку всех прокси (max_concurrent={max_concurrent}, update_redis_status={update_redis_status})")
            
            try:
                import httpx
                
                # Если нужно обновить статусы в Redis, получаем ВСЕ прокси из БД
                # Иначе получаем только активные (как раньше)
                if update_redis_status:
                    try:
                        result = await self.db_session.execute(
                            select(Proxy).order_by(Proxy.id)
                        )
                        all_proxies = list(result.scalars().all())
                    except Exception as e:
                        logger.error(f"❌ Ошибка при получении прокси из БД: {e}")
                        return {"total": 0, "working": 0, "blocked": 0, "error": 0, "rate_limited": 0, "blocked_count": 0, "unblocked_count": 0, "results": []}
                else:
                    # Получаем все активные прокси
                    all_proxies = await self.get_active_proxies(force_refresh=True)
                
                total_proxies = len(all_proxies)
                
                if total_proxies == 0:
                    return {"total": 0, "working": 0, "blocked": 0, "error": 0, "rate_limited": 0, "blocked_count": 0, "unblocked_count": 0, "results": []}
                
                logger.info(f"📊 Проверяем {total_proxies} прокси параллельно...")
                
                # Разбиваем на группы для параллельной проверки
                working_count = 0
                blocked_count = 0
                error_count = 0
                rate_limited_count = 0
                blocked_in_redis = 0
                unblocked_in_redis = 0
                results = []
                
                async def check_single_proxy_full(proxy: Proxy) -> dict:
                    """Проверяет один прокси через Steam API и возвращает детальный результат."""
                    try:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Referer": "https://steamcommunity.com/market/",
                            "Origin": "https://steamcommunity.com",
                        }
                        async with httpx.AsyncClient(proxy=proxy.url, timeout=15, headers=headers) as client:
                            response = await client.get(
                                "https://steamcommunity.com/market/search/render/",
                                params={"query": "AK-47", "appid": 730, "start": 0, "count": 1, "norender": 1}
                            )
                            if response.status_code == 200:
                                return {"proxy": proxy, "status": "ok", "error": None}
                            elif response.status_code == 429:
                                return {"proxy": proxy, "status": "rate_limited", "error": "429 Too Many Requests"}
                            else:
                                return {"proxy": proxy, "status": "error", "error": f"HTTP {response.status_code}"}
                    except httpx.ProxyError as e:
                        return {"proxy": proxy, "status": "error", "error": f"Proxy error: {str(e)[:100]}"}
                    except httpx.TimeoutException:
                        return {"proxy": proxy, "status": "error", "error": "Timeout"}
                    except Exception as e:
                        return {"proxy": proxy, "status": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}
                
                for i in range(0, total_proxies, max_concurrent):
                    batch = all_proxies[i:i + max_concurrent]
                    batch_num = i // max_concurrent + 1
                    total_batches = (total_proxies + max_concurrent - 1) // max_concurrent
                    
                    logger.info(f"🔍 Проверяем группу {batch_num}/{total_batches}: {len(batch)} прокси...")
                    
                    # Создаем задачи для параллельной проверки
                    if update_redis_status:
                        # Используем полную проверку через Steam API
                        tasks = [check_single_proxy_full(proxy) for proxy in batch]
                    else:
                        # Используем быструю фоновую проверку (как раньше)
                        tasks = [self._check_single_proxy_background(proxy) for proxy in batch]
                    
                    # Выполняем все проверки параллельно
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Обрабатываем результаты группы
                    for proxy, result in zip(batch, batch_results):
                        if isinstance(result, Exception):
                            error_count += 1
                            status = "error"
                            error_msg = f"Exception: {str(result)[:100]}"
                            logger.debug(f"❌ Прокси ID={proxy.id}: ошибка проверки")
                        elif update_redis_status and isinstance(result, dict):
                            # Полная проверка возвращает словарь
                            status = result["status"]
                            error_msg = result.get("error")
                        elif not update_redis_status:
                            # Быстрая проверка возвращает bool
                            if result:
                                working_count += 1
                                status = "working"
                                error_msg = None
                                logger.debug(f"✅ Прокси ID={proxy.id}: работает")
                            else:
                                blocked_count += 1
                                status = "blocked"
                                error_msg = None
                                logger.debug(f"🚫 Прокси ID={proxy.id}: заблокирован")
                        else:
                            # Неожиданный формат результата
                            error_count += 1
                            status = "error"
                            error_msg = f"Unexpected result type: {type(result)}"
                            logger.debug(f"❌ Прокси ID={proxy.id}: неожиданный формат результата")
                        
                        # Обновляем статусы в Redis, если нужно
                        if update_redis_status:
                            if status == "ok":
                                working_count += 1
                                # Если прокси был заблокирован, разблокируем его
                                was_blocked = await self._is_proxy_temporarily_blocked(proxy.id)
                                if was_blocked:
                                    await self._unblock_proxy(proxy.id)
                                    unblocked_in_redis += 1
                                    logger.info(f"✅ Прокси ID={proxy.id}: работает, разблокирован в Redis")
                                else:
                                    logger.debug(f"✅ Прокси ID={proxy.id}: работает")
                            elif status == "rate_limited":
                                rate_limited_count += 1
                                blocked_count += 1
                                # Блокируем прокси в Redis (если еще не заблокирован)
                                was_blocked = await self._is_proxy_temporarily_blocked(proxy.id)
                                if not was_blocked:
                                    await self._block_proxy_temporarily(proxy.id, self.BLOCK_DURATION_429_FIRST)
                                    blocked_in_redis += 1
                                    logger.info(f"🚫 Прокси ID={proxy.id}: rate limited (429), заблокирован в Redis")
                                else:
                                    logger.debug(f"⏳ Прокси ID={proxy.id}: rate limited (429), уже заблокирован")
                            else:
                                # Для других ошибок не блокируем (это не 429)
                                error_count += 1
                                logger.debug(f"❌ Прокси ID={proxy.id}: ошибка ({error_msg})")
                        
                        results.append({
                            "proxy_id": proxy.id,
                            "url": proxy.url[:50] + "..." if len(proxy.url) > 50 else proxy.url,
                            "status": status,
                            "error": error_msg
                        })
                    
                    # Небольшая задержка между группами
                    if i + max_concurrent < total_proxies:
                        await asyncio.sleep(1)
                
                if update_redis_status:
                    logger.info(
                        f"✅ Полная проверка завершена: "
                        f"работают={working_count}, "
                        f"rate_limited={rate_limited_count}, "
                        f"ошибок={error_count}, "
                        f"заблокировано в Redis={blocked_in_redis}, "
                        f"разблокировано в Redis={unblocked_in_redis}"
                    )
                    return {
                        "total": total_proxies,
                        "working": working_count,
                        "blocked": blocked_count,
                        "error": error_count,
                        "rate_limited": rate_limited_count,
                        "blocked_count": blocked_in_redis,
                        "unblocked_count": unblocked_in_redis,
                        "results": results
                    }
                else:
                    logger.info(f"✅ Параллельная проверка завершена: {working_count} работают, {blocked_count} заблокированы, {error_count} ошибок")
                    return {
                        "total": total_proxies,
                        "working": working_count,
                        "blocked": blocked_count,
                        "error": error_count,
                        "results": results
                    }
            finally:
                # Снимаем флаг выполнения проверки
                self._check_all_proxies_running = False
                logger.debug(f"✅ ProxyManager: Проверка всех прокси завершена, блокировка снята")
    
    async def check_and_update_all_proxies_status(self, max_concurrent: int = 20) -> Dict[str, any]:
        """
        Полная проверка всех прокси с обновлением статусов в Redis.
        Блокирует прокси с rate_limited (429) в Redis, разблокирует работающие.
        Используется при запуске парсинг сервиса для актуализации статусов.
        
        Args:
            max_concurrent: Максимальное количество одновременных проверок
            
        Returns:
            Dict с результатами проверки и обновления
        """
        # Используем существующий метод с параметром update_redis_status=True
        return await self.check_all_proxies_parallel(max_concurrent=max_concurrent, update_redis_status=True)
    
    async def get_blocked_proxies_info(self) -> Dict[str, any]:
        """
        Получает информацию о временно заблокированных прокси.
        
        Returns:
            Словарь с информацией о заблокированных прокси
        """
        blocked_info = {
            'blocked_count': 0,
            'blocked_proxies': [],
            'total_active': 0
        }
        
        try:
            # ВАЖНО: Получаем ВСЕ активные прокси из БД (включая заблокированные)
            # чтобы правильно посчитать заблокированные
            try:
                result = await self.db_session.execute(
                    select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)
                )
                all_active_proxies = list(result.scalars().all())
            except Exception as e:
                logger.error(f"❌ ProxyManager: Ошибка при получении прокси из БД: {e}")
                all_active_proxies = []
            
            blocked_info['total_active'] = len(all_active_proxies)
            
            # Проверяем каждый прокси на блокировку
            for proxy in all_active_proxies:
                if await self._is_proxy_temporarily_blocked(proxy.id):
                    blocked_info['blocked_count'] += 1
                    
                    # Получаем время разблокировки из БД
                    blocked_until = proxy.blocked_until
                    
                    # Fallback на локальный кэш, если в БД нет данных
                    if not blocked_until and proxy.id in self._blocked_proxies:
                        blocked_until = self._blocked_proxies[proxy.id]
                    
                    blocked_info['blocked_proxies'].append({
                        'id': proxy.id,
                        'url': proxy.url[:50] + '...' if len(proxy.url) > 50 else proxy.url,
                        'blocked_until': blocked_until.isoformat() if blocked_until else None,
                        'minutes_left': int((blocked_until - datetime.now()).total_seconds() / 60) if blocked_until else None
                    })
            
            return blocked_info
            
        except Exception as e:
            logger.error(f"❌ ProxyManager: Ошибка при получении информации о заблокированных прокси: {e}")
            return blocked_info
    
    async def _check_single_proxy_background(self, proxy: Proxy) -> bool:
        """
        Фоновая проверка одного прокси на доступность.
        
        Args:
            proxy: Объект прокси для проверки
            
        Returns:
            True если прокси работает, False если все еще заблокирован
        """
        try:
            import httpx
            
            # ОСТОРОЖНАЯ проверка: минимальный запрос к Steam
            # Используем самый легкий endpoint, чтобы не усугублять блокировку
            test_url = "https://steamcommunity.com/market/search/render/"
            params = {
                'query': '',  # Пустой запрос - минимальная нагрузка
                'start': 0,
                'count': 1,  # Минимальное количество
                'appid': 730,
                'currency': 1
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            }
            
            async with httpx.AsyncClient(
                proxy=proxy.url,
                timeout=self.BACKGROUND_CHECK_TIMEOUT,
                follow_redirects=True
            ) as client:
                response = await client.get(test_url, params=params, headers=headers)
                
                # Если получили не 429, значит прокси разблокирован
                if response.status_code != 429:
                    logger.info(f"✅ Фоновая проверка: Прокси ID={proxy.id} разблокирован (код: {response.status_code})")
                    return True
                else:
                    logger.debug(f"⏳ Фоновая проверка: Прокси ID={proxy.id} все еще заблокирован (429)")
                    return False
                    
        except Exception as e:
            logger.debug(f"⚠️ Фоновая проверка: Ошибка при проверке прокси ID={proxy.id}: {type(e).__name__}")
            return False
    
    async def _background_proxy_checker(self):
        """
        Фоновая задача для периодической проверки заблокированных прокси.
        Работает в отдельном потоке и не блокирует основную работу.
        
        Логика:
        - Всегда проверяет раз в 30 минут (фиксированный интервал)
        - Если все прокси заблокированы - один раз проверяет умно (начиная с самых старых)
        - После умной проверки не трогает заблокированные прокси еще 30 минут
        - Умная проверка начинается с наиболее старого прокси (который давно не проверяли)
        - Если старый прокси разблокировался - продолжает проверять остальные
        """
        logger.info("🔄 ProxyManager: Запущена фоновая проверка заблокированных прокси")
        
        # Выполняем первую проверку немедленно
        first_check = True
        
        while self._background_check_running:
            try:
                # Определяем интервал ожидания в зависимости от количества заблокированных прокси
                # (будет пересчитан внутри цикла, но здесь устанавливаем начальное значение)
                wait_interval = self.BACKGROUND_CHECK_INTERVAL
                # ВАЖНО: Получаем информацию о заблокированных прокси ТОЛЬКО из Redis (без обращения к БД)
                # Это избегает конфликтов с сессией БД при параллельных операциях
                # Получаем список всех заблокированных прокси из БД
                try:
                    from core import Proxy
                    from sqlalchemy import select
                    result = await self.db_session.execute(
                        select(Proxy).where(
                            Proxy.blocked_until.isnot(None),
                            Proxy.blocked_until > datetime.now()
                        )
                    )
                    blocked_proxies = result.scalars().all()
                    blocked_count = len(blocked_proxies)
                except Exception as e:
                    logger.warning(f"⚠️ ProxyManager: Ошибка при получении заблокированных прокси из БД: {e}")
                    blocked_count = 0
                    blocked_proxies = []
                
                # Получаем время последней умной проверки
                last_smart_check = None
                try:
                    last_smart_check_str = await self.redis_service._client.get(self.REDIS_LAST_SMART_CHECK_KEY)
                    if last_smart_check_str:
                        if isinstance(last_smart_check_str, bytes):
                            last_smart_check_str = last_smart_check_str.decode()
                        last_smart_check = datetime.fromisoformat(last_smart_check_str)
                except Exception:
                    pass
                
                # Получаем общее количество активных прокси для определения процента заблокированных
                try:
                    from core import Proxy
                    total_result = await self.db_session.execute(
                        select(func.count(Proxy.id)).where(Proxy.is_active == True)
                    )
                    total_proxies = total_result.scalar() or 0
                    blocked_ratio = blocked_count / total_proxies if total_proxies > 0 else 0
                except Exception:
                    total_proxies = 0
                    blocked_ratio = 0
                
                # Определяем интервал проверки в зависимости от процента заблокированных прокси
                check_interval = self.BACKGROUND_CHECK_INTERVAL_FAST if blocked_ratio >= self.BLOCKED_PROXIES_THRESHOLD_FOR_FAST_CHECK else self.BACKGROUND_CHECK_INTERVAL
                
                # Проверяем, нужно ли делать умную проверку
                should_do_smart_check = False
                if blocked_count > 0:
                    # Если все прокси заблокированы и прошло достаточно времени с последней умной проверки
                    if last_smart_check is None:
                        # Никогда не делали умную проверку - делаем
                        should_do_smart_check = True
                        logger.info(f"🔍 Фоновая проверка: Найдено {blocked_count}/{total_proxies} заблокированных прокси ({blocked_ratio*100:.1f}%), выполняем первую умную проверку")
                    else:
                        time_since_last_check = (datetime.now() - last_smart_check).total_seconds()
                        if time_since_last_check >= check_interval:
                            # Прошло достаточно времени - можно проверить умно
                            should_do_smart_check = True
                            interval_min = int(check_interval / 60)
                            logger.info(f"🔍 Фоновая проверка: Найдено {blocked_count}/{total_proxies} заблокированных прокси ({blocked_ratio*100:.1f}%), выполняем умную проверку (прошло {int(time_since_last_check/60)} мин, интервал {interval_min} мин)")
                        else:
                            # Недавно делали умную проверку - пропускаем
                            minutes_left = int((check_interval - time_since_last_check) / 60)
                            logger.debug(f"⏸️ Фоновая проверка: Найдено {blocked_count}/{total_proxies} заблокированных прокси ({blocked_ratio*100:.1f}%), но умная проверка была {int(time_since_last_check/60)} мин назад. Пропускаем еще {minutes_left} мин")
                
                if should_do_smart_check and blocked_count > 0:
                    # Получаем заблокированные прокси с их временем блокировки из БД
                    blocked_proxies_with_time = []
                    for proxy in blocked_proxies:
                        if proxy.blocked_until:
                            blocked_proxies_with_time.append((proxy.id, proxy.blocked_until))
                    
                    # Сортируем по времени блокировки (самые старые первыми - у них blocked_until раньше)
                    blocked_proxies_with_time.sort(key=lambda x: x[1])
                    
                    # Получаем прокси из кэша Redis (без обращения к БД)
                    all_active_proxies = await self.get_active_proxies(force_refresh=False)
                    proxies_by_id = {p.id: p for p in all_active_proxies}
                    
                    # Собираем заблокированные прокси для проверки (уже отсортированные по времени блокировки)
                    blocked_proxies = []
                    for proxy_id, blocked_until in blocked_proxies_with_time:
                        if proxy_id in proxies_by_id:
                            blocked_proxies.append(proxies_by_id[proxy_id])
                    
                    # Инициализируем счетчики
                    checked_count = 0
                    unblocked_count = 0
                    
                    if blocked_proxies:
                        logger.info(f"🧠 Умная проверка: Начинаем с самых старых заблокированных прокси (всего {len(blocked_proxies)})")
                        
                        # Проверяем прокси начиная с самых старых
                        # Если старый прокси разблокировался - продолжаем проверять остальные
                        for i in range(0, len(blocked_proxies), self.BACKGROUND_CHECK_MAX_CONCURRENT):
                            batch = blocked_proxies[i:i + self.BACKGROUND_CHECK_MAX_CONCURRENT]
                            
                            # Проверяем группу прокси параллельно
                            tasks = []
                            for proxy in batch:
                                logger.debug(f"🔍 Умная проверка: Тестируем прокси ID={proxy.id} (самый старый)")
                                tasks.append(self._check_single_proxy_background(proxy))
                            
                            # Ждем результаты всех проверок в группе
                            results = await asyncio.gather(*tasks, return_exceptions=True)
                            
                            # Обрабатываем результаты
                            for proxy, result in zip(batch, results):
                                checked_count += 1
                                if isinstance(result, Exception):
                                    logger.debug(f"⚠️ Ошибка при проверке прокси ID={proxy.id}: {result}")
                                elif result:
                                    # Прокси работает, разблокируем его
                                    await self._unblock_proxy(proxy.id)
                                    unblocked_count += 1
                                    logger.info(f"✅ Умная проверка: Прокси ID={proxy.id} разблокирован, продолжаем проверять остальные")
                            
                            # Задержка между группами для осторожности
                            if i + self.BACKGROUND_CHECK_MAX_CONCURRENT < len(blocked_proxies):
                                await asyncio.sleep(self.BACKGROUND_CHECK_DELAY_BETWEEN_PROXIES)
                        
                        # Сохраняем время последней умной проверки
                        try:
                            await self.redis_service._client.set(
                                self.REDIS_LAST_SMART_CHECK_KEY,
                                datetime.now().isoformat(),
                                ex=self.BACKGROUND_CHECK_INTERVAL
                            )
                        except Exception as e:
                            logger.debug(f"⚠️ Ошибка при сохранении времени умной проверки: {e}")
                        
                        # Логируем результаты проверки
                        interval_min = int(check_interval / 60)
                        if unblocked_count > 0:
                            logger.info(f"🎉 Умная проверка: Разблокировано {unblocked_count} из {checked_count} прокси. Следующая умная проверка через {interval_min} минут")
                        elif checked_count > 0:
                            logger.info(f"⏳ Умная проверка: Все {checked_count} прокси все еще заблокированы. Следующая умная проверка через {interval_min} минут")
                    else:
                        logger.debug(f"⏳ Умная проверка: Не найдено активных прокси для проверки из {blocked_count} заблокированных")
                elif blocked_count == 0:
                    logger.debug("✅ Фоновая проверка: Нет заблокированных прокси")
                
                # Ждем до следующей проверки (интервал зависит от процента заблокированных прокси)
                if first_check:
                    # Первая проверка - без задержки
                    first_check = False
                    logger.info("🚀 Выполняем первую проверку прокси немедленно")
                else:
                    wait_minutes = int(check_interval / 60)
                    logger.debug(f"⏳ Фоновая проверка: Ожидание {wait_minutes} мин до следующей проверки")
                    await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"❌ Ошибка в фоновой проверке прокси: {e}")
                await asyncio.sleep(60)  # При ошибке ждем минуту
    
    def start_background_proxy_check(self):
        """Запускает фоновую проверку заблокированных прокси."""
        if not self._background_check_running:
            self._background_check_running = True
            self._background_check_task = asyncio.create_task(self._background_proxy_checker())
            logger.info("🚀 ProxyManager: Фоновая проверка прокси запущена")
    
    def stop_background_proxy_check(self):
        """Останавливает фоновую проверку заблокированных прокси."""
        self._background_check_running = False
        if self._background_check_task and not self._background_check_task.done():
            self._background_check_task.cancel()
            logger.info("🛑 ProxyManager: Фоновая проверка прокси остановлена")
    
    async def deactivate_proxy(self, proxy_id: int, reason: str = ""):
        """Деактивирует прокси и обновляет кэш в Redis."""
        await self.db_session.execute(
            update(Proxy)
            .where(Proxy.id == proxy_id)
            .values(is_active=False)
        )
        await self.db_session.commit()
        logger.debug(f"Прокси {proxy_id} деактивирован. Причина: {reason}")
        
        # Обновляем кэш в Redis
        await self._update_redis_cache()
    
    async def delete_proxy(self, proxy_id: int) -> bool:
        """
        Полностью удаляет прокси из базы данных и обновляет кэш в Redis.
        
        Args:
            proxy_id: ID прокси для удаления
            
        Returns:
            True если прокси был удален, False если не найден
        """
        async with self._lock:
            result = await self.db_session.execute(
                select(Proxy).where(Proxy.id == proxy_id)
            )
            proxy = result.scalar_one_or_none()
            
            if not proxy:
                logger.warning(f"Прокси {proxy_id} не найден для удаления")
                return False
            
            await self.db_session.execute(
                delete(Proxy).where(Proxy.id == proxy_id)
            )
            await self.db_session.commit()
            
            # Удаляем из кэша последнего использования
            if proxy_id in self._last_used:
                del self._last_used[proxy_id]
            
            logger.debug(f"✅ Прокси {proxy_id} полностью удален из БД")
            
            # Обновляем кэш в Redis
            await self._update_redis_cache()
            
            return True
    
    async def remove_duplicate_proxies(self) -> Dict[str, int]:
        """
        Удаляет дубликаты прокси на основе нормализованного URL.
        Оставляет прокси с наименьшим ID (самый старый).
        
        Returns:
            Словарь с результатами: {'removed': количество удаленных, 'kept': количество оставленных}
        """
        async with self._lock:
            # Получаем все прокси
            result = await self.db_session.execute(
                select(Proxy).order_by(Proxy.id)
            )
            all_proxies = list(result.scalars().all())
            
            if not all_proxies:
                logger.info("📋 Нет прокси для проверки на дубликаты")
                return {'removed': 0, 'kept': len(all_proxies)}
            
            # Группируем по нормализованному URL
            normalized_groups: Dict[str, List[Proxy]] = {}
            for proxy in all_proxies:
                normalized = ProxyManager._normalize_proxy_url(proxy.url)
                if normalized not in normalized_groups:
                    normalized_groups[normalized] = []
                normalized_groups[normalized].append(proxy)
            
            # Находим дубликаты (группы с более чем одним прокси)
            duplicates_found = 0
            removed_count = 0
            kept_count = 0
            
            for normalized_url, proxies in normalized_groups.items():
                if len(proxies) > 1:
                    duplicates_found += 1
                    # Сортируем по ID, оставляем первый (самый старый)
                    proxies_sorted = sorted(proxies, key=lambda p: p.id)
                    kept_proxy = proxies_sorted[0]
                    duplicates = proxies_sorted[1:]
                    
                    logger.info(f"🔍 Найдены дубликаты для {normalized_url}:")
                    logger.info(f"   ✅ Оставляем: ID={kept_proxy.id} (URL: {kept_proxy.url})")
                    
                    for dup in duplicates:
                        logger.info(f"   ❌ Удаляем дубликат: ID={dup.id} (URL: {dup.url})")
                        await self.db_session.execute(
                            delete(Proxy).where(Proxy.id == dup.id)
                        )
                        removed_count += 1
                    
                    kept_count += 1
                else:
                    kept_count += 1
            
            if removed_count > 0:
                await self.db_session.commit()
                logger.info(f"✅ Удалено {removed_count} дубликатов, оставлено {kept_count} уникальных прокси")
                # Обновляем кэш в Redis
                await self._update_redis_cache()
            else:
                logger.info(f"✅ Дубликатов не найдено. Всего уникальных прокси: {kept_count}")
            
            return {'removed': removed_count, 'kept': kept_count}
    
    async def activate_proxy(self, proxy_id: int):
        """Активирует прокси и обновляет кэш в Redis."""
        await self.db_session.execute(
            update(Proxy)
            .where(Proxy.id == proxy_id)
            .values(is_active=True, fail_count=0, last_error=None)
        )
        await self.db_session.commit()
        logger.debug(f"Прокси {proxy_id} активирован")
        
        # Обновляем кэш в Redis
        await self._update_redis_cache()
    
    async def get_proxy_stats(self) -> Dict:
        """
        Получает статистику по прокси.
        ВАЖНО: Читает напрямую из БД, чтобы получить актуальную статистику (не из кэша).
        """
        # Получаем все прокси напрямую из БД (не из кэша) для актуальной статистики
        all_proxies_result = await self.db_session.execute(select(Proxy))
        all_proxies = list(all_proxies_result.scalars().all())
        
        # Подсчитываем активные прокси
        active_proxies = [p for p in all_proxies if p.is_active]
        
        logger.debug(f"📊 ProxyManager: Получена статистика из БД: всего={len(all_proxies)}, активных={len(active_proxies)}")
        
        return {
            "total": len(all_proxies),
            "active": len(active_proxies),
            "inactive": len(all_proxies) - len(active_proxies),
            "proxies": [
                {
                    "id": p.id,
                    "url": p.url[:30] + "..." if len(p.url) > 30 else p.url,
                    "active": p.is_active,
                    "success_count": p.success_count,
                    "fail_count": p.fail_count,
                    "delay": p.delay_seconds,
                    "delay_seconds": p.delay_seconds,  # Добавляем для совместимости
                    "last_used": p.last_used.isoformat() if p.last_used else None
                }
                for p in all_proxies
            ]
        }
    
    async def use_proxy(self, min_delay: float = 0.0, force_refresh: bool = False) -> ProxyContext:
        """
        Контекстный менеджер для работы с прокси.
        Автоматически управляет резервацией, освобождением и обновлением статистики.
        
        Args:
            min_delay: Минимальная задержка с момента последнего использования
            force_refresh: Принудительно обновить список прокси из БД
            
        Returns:
            ProxyContext для использования в async with
        
        Example:
            async with proxy_manager.use_proxy() as ctx:
                proxy = ctx.proxy
                # Используем proxy для запроса
                result = await make_request(proxy.url)
                await ctx.mark_success()  # или ctx.mark_error() при ошибке
        """
        # Получаем прокси с учетом частоты использования и очереди
        proxy = await self._get_proxy_with_queue(min_delay=min_delay, force_refresh=force_refresh)
        
        if not proxy:
            # Нет доступных прокси - возвращаем контекст с None
            logger.warning("⚠️ ProxyManager.use_proxy: Не удалось получить прокси, возвращаем None")
            return ProxyContext(self, None)
        
        # Создаем и возвращаем контекст
        return ProxyContext(self, proxy)
    
    async def _get_proxy_with_queue(
        self,
        min_delay: float = 0.0,
        force_refresh: bool = False
    ) -> Optional[Proxy]:
        """
        Получает прокси с учетом очереди и частоты использования.
        
        Args:
            min_delay: Минимальная задержка с момента последнего использования
            force_refresh: Принудительно обновить список прокси из БД
            
        Returns:
            Proxy или None если нет доступных
        """
        async with self._lock:
            # Обновляем список прокси при необходимости
            proxies = await self.get_active_proxies(force_refresh=force_refresh)
            
            if not proxies:
                logger.error("❌ ProxyManager._get_proxy_with_queue: Нет активных прокси")
                return None
            
            now = datetime.now()
            
            # Ищем доступный прокси (не заблокирован, прошло достаточно времени с последнего использования)
            available_proxy = None
            wait_time = 0.0
            
            for proxy in proxies:
                # Проверяем блокировку
                if await self._is_proxy_temporarily_blocked(proxy.id):
                    continue
                
                # Проверяем, не используется ли прокси прямо сейчас
                if await self._is_proxy_in_use(proxy.id):
                    continue
                
                # Проверяем частоту использования
                last_used = await self._get_proxy_last_used_from_db(proxy.id)
                
                if last_used is None:
                    # Прокси еще не использовался - доступен
                    if await self._reserve_proxy(proxy.id):
                        logger.debug(f"✅ ProxyManager: Выбран неиспользованный прокси ID={proxy.id}")
                        await self._set_last_proxy_index(proxies.index(proxy))
                        return proxy
                else:
                    # Проверяем, прошло ли достаточно времени
                    time_since_use = (now - last_used).total_seconds()
                    required_delay = max(proxy.delay_seconds, min_delay)
                    
                    if time_since_use >= required_delay:
                        # Прокси доступен
                        if await self._reserve_proxy(proxy.id):
                            logger.debug(
                                f"✅ ProxyManager: Выбран прокси ID={proxy.id} "
                                f"(прошло {time_since_use:.1f}с, требуется {required_delay:.1f}с)"
                            )
                            await self._set_last_proxy_index(proxies.index(proxy))
                            return proxy
                    else:
                        # Прокси еще "свежий" - нужно подождать
                        wait_needed = required_delay - time_since_use
                        if available_proxy is None or wait_needed < wait_time:
                            available_proxy = proxy
                            wait_time = wait_needed
            
        # Если нашли прокси, который нужно подождать - ждем вне блокировки
        if available_proxy:
            logger.debug(
                f"⏳ ProxyManager: Прокси ID={available_proxy.id} еще свежий, "
                f"нужно подождать {wait_time:.1f}с"
            )
            
            # Освобождаем блокировку перед ожиданием
            # (чтобы другие задачи могли получить прокси)
            
            # Ждем нужное время
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            # После ожидания снова проверяем доступность прокси
            async with self._lock:
                # Проверяем, что прокси все еще доступен
                if await self._is_proxy_temporarily_blocked(available_proxy.id):
                    logger.warning(f"⚠️ ProxyManager: Прокси ID={available_proxy.id} заблокирован во время ожидания")
                    # Рекурсивно вызываем для получения другого прокси
                    return await self._get_proxy_with_queue(min_delay=min_delay, force_refresh=False)
                
                if await self._is_proxy_in_use(available_proxy.id):
                    # Прокси все еще используется - ждем еще его delay_seconds
                    additional_wait = available_proxy.delay_seconds
                    logger.debug(
                        f"⏳ ProxyManager: Прокси ID={available_proxy.id} все еще используется, "
                        f"ждем еще {additional_wait:.1f}с"
                    )
                    # Освобождаем блокировку перед дополнительным ожиданием
                    await asyncio.sleep(additional_wait)
                    # Рекурсивно вызываем для получения прокси
                    return await self._get_proxy_with_queue(min_delay=min_delay, force_refresh=False)
                
                # Пробуем зарезервировать прокси
                if await self._reserve_proxy(available_proxy.id):
                    logger.debug(f"✅ ProxyManager: Прокси ID={available_proxy.id} получен после ожидания")
                    proxies = await self.get_active_proxies(force_refresh=False)
                    if available_proxy in proxies:
                        await self._set_last_proxy_index(proxies.index(available_proxy))
                    return available_proxy
                else:
                    logger.warning(f"⚠️ ProxyManager: Не удалось зарезервировать прокси ID={available_proxy.id} после ожидания")
                    # Рекурсивно вызываем для получения другого прокси
                    return await self._get_proxy_with_queue(min_delay=min_delay, force_refresh=False)
        
        # Все прокси заняты или заблокированы - возвращаем самый старый прокси и ждем
        # ВАЖНО: Этот блок выполняется только если available_proxy is None (нет прокси, который нужно просто подождать)
        logger.info("⏳ ProxyManager: Все прокси заняты или заблокированы, находим самый старый прокси и ждем")
        
        # Сортируем прокси по времени последнего использования (самый старый первым)
        proxies_with_time = []
        all_proxies = []
        async with self._lock:
            all_proxies = await self.get_active_proxies(force_refresh=False)
            for proxy in all_proxies:
                # Пропускаем заблокированные прокси
                if await self._is_proxy_temporarily_blocked(proxy.id):
                    continue
                last_used = await self._get_proxy_last_used_from_db(proxy.id)
                if last_used:
                    proxies_with_time.append((proxy, last_used))
                else:
                    # Прокси еще не использовался - приоритет
                    proxies_with_time.append((proxy, datetime.min))
        
        if not proxies_with_time:
            # Все прокси заблокированы - отправляем уведомление
            should_notify = False
            if self._last_notification_time is None:
                should_notify = True
            else:
                time_since_notification = (now - self._last_notification_time).total_seconds()
                if time_since_notification >= self._notification_cooldown.total_seconds():
                    should_notify = True
            
            if should_notify:
                self._last_notification_time = now
                # Запускаем отправку уведомления в фоне (не блокируем)
                blocked_count = len([p for p in all_proxies if await self._is_proxy_temporarily_blocked(p.id)])
                asyncio.create_task(
                    send_proxy_unavailable_notification(
                        blocked_count=blocked_count,
                        total_count=len(all_proxies),
                        oldest_proxy_delay=self.default_delay
                    )
                )
            
            logger.error("❌ ProxyManager: Все прокси заблокированы, нет доступных прокси")
            return None
        
        # Сортируем по времени последнего использования (самый старый первым)
        proxies_with_time.sort(key=lambda x: x[1])
        oldest_proxy, oldest_last_used = proxies_with_time[0]
        
        # Вычисляем время ожидания
        if oldest_last_used == datetime.min:
            # Прокси еще не использовался - доступен сразу
            wait_time = 0.0
        else:
            time_since_use = (now - oldest_last_used).total_seconds()
            required_delay = max(oldest_proxy.delay_seconds, min_delay)
            wait_time = max(0.0, required_delay - time_since_use)
        
        if wait_time > 0:
            logger.info(f"⏳ ProxyManager: Ожидаем {wait_time:.1f}с для самого старого прокси ID={oldest_proxy.id}")
            # Освобождаем блокировку перед ожиданием
            await asyncio.sleep(wait_time)
        
        # После ожидания пытаемся зарезервировать прокси
        async with self._lock:
            # Проверяем, что прокси все еще доступен
            if await self._is_proxy_temporarily_blocked(oldest_proxy.id):
                logger.warning(f"⚠️ ProxyManager: Прокси ID={oldest_proxy.id} заблокирован во время ожидания, пробуем другой")
                return await self._get_proxy_with_queue(min_delay=min_delay, force_refresh=False)
            
            if await self._reserve_proxy(oldest_proxy.id):
                logger.info(f"✅ ProxyManager: Получен самый старый прокси ID={oldest_proxy.id} после ожидания {wait_time:.1f}с")
                proxies = await self.get_active_proxies(force_refresh=False)
                if oldest_proxy in proxies:
                    await self._set_last_proxy_index(proxies.index(oldest_proxy))
                return oldest_proxy
            else:
                # Прокси занят - рекурсивно вызываем для получения другого
                logger.warning(f"⚠️ ProxyManager: Прокси ID={oldest_proxy.id} занят после ожидания, пробуем другой")
                return await self._get_proxy_with_queue(min_delay=min_delay, force_refresh=False)
            
            # Сортируем по времени последнего использования (самый старый первым)
            proxies_with_time.sort(key=lambda x: x[1])
            oldest_proxy, oldest_last_used = proxies_with_time[0]
            
            # Вычисляем время ожидания
            if oldest_last_used == datetime.min:
                # Прокси еще не использовался
                wait_time = 0.0
            else:
                time_since_use = (now - oldest_last_used).total_seconds()
                required_delay = max(oldest_proxy.delay_seconds, min_delay)
                wait_time = max(0.0, required_delay - time_since_use)
            
            logger.info(
                f"⏳ ProxyManager: Используем самый старый прокси ID={oldest_proxy.id}, "
                f"ждем {wait_time:.1f}с перед использованием"
            )
            
            # Отправляем уведомление в Telegram (с задержкой)
            should_notify = False
            if self._last_notification_time is None:
                should_notify = True
            else:
                time_since_notification = (now - self._last_notification_time).total_seconds()
                if time_since_notification >= self._notification_cooldown.total_seconds():
                    should_notify = True
            
            if should_notify:
                self._last_notification_time = now
                # Запускаем отправку уведомления в фоне (не блокируем)
                asyncio.create_task(
                    send_proxy_unavailable_notification(
                        blocked_count=len([p for p in proxies if await self._is_proxy_temporarily_blocked(p.id)]),
                        total_count=len(proxies),
                        oldest_proxy_delay=wait_time
                    )
                )
            
            # Ждем нужное время
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            # Пробуем зарезервировать прокси
            if await self._reserve_proxy(oldest_proxy.id):
                logger.info(f"✅ ProxyManager: Самый старый прокси ID={oldest_proxy.id} зарезервирован после ожидания")
                await self._set_last_proxy_index(proxies.index(oldest_proxy))
                return oldest_proxy
            else:
                logger.warning(f"⚠️ ProxyManager: Не удалось зарезервировать самый старый прокси ID={oldest_proxy.id}")
                return None

