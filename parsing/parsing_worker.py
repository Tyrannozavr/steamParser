"""
Сервис парсинга - отдельный воркер для выполнения задач парсинга.
Общается с Telegram ботом через Redis.
Поддерживает параллельную обработку нескольких задач одновременно.
"""
import asyncio
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Set, Dict, Any
from loguru import logger

from core import Config, DatabaseManager
from core.logger import setup_logging, get_task_logger, set_task_id
from services import MonitoringService, ProxyManager, ParsingService, ResultsProcessorService
from services.redis_service import RedisService
from services.rabbitmq_service import RabbitMQService

# Импорт версии
try:
    from version import get_version, get_version_info
    VERSION = get_version()
    VERSION_INFO = get_version_info()
except ImportError:
    VERSION = "unknown"
    VERSION_INFO = {"version": "unknown", "last_updated": "unknown", "changelog": ""}

# Настройка логирования
setup_logging(service_name="parsing_worker", enable_task_logging=True, enable_console=True)


class ParsingWorker:
    """Воркер для выполнения задач парсинга."""
    
    def __init__(self):
        """Инициализация воркера."""
        self.db_manager: Optional[DatabaseManager] = None
        self.db_session = None
        self.proxy_manager: Optional[ProxyManager] = None
        self.parsing_service: Optional[ParsingService] = None
        self.redis_service: Optional[RedisService] = None
        self.rabbitmq_service: Optional[RabbitMQService] = None
        self.monitoring_service: Optional[MonitoringService] = None
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # Параллельная обработка задач
        # Максимальное количество одновременных задач (можно настроить через переменную окружения)
        # По умолчанию 10 для эффективной параллельной обработки I/O операций
        max_concurrent = int(os.getenv("MAX_CONCURRENT_TASKS", "10"))
        self._task_semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"🔧 ParsingWorker: Инициализирован с MAX_CONCURRENT_TASKS={max_concurrent}")
        self._active_tasks: set[asyncio.Task] = set()  # Отслеживание активных задач
        self._tasks_lock = asyncio.Lock()  # Блокировка для безопасного доступа к _active_tasks
        
        # Обработка сигналов
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов."""
        logger.info(f"Получен сигнал {signum}, завершение работы...")
        self._shutdown_event.set()
    
    async def initialize(self):
        """Инициализирует все компоненты."""
        logger.info("=" * 80)
        logger.info("Инициализация Parsing Worker...")
        logger.info(f"📦 Версия: {VERSION}")
        logger.info(f"📅 Обновлено: {VERSION_INFO.get('last_updated', 'unknown')}")
        logger.info("=" * 80)
        
        # Инициализируем БД
        self.db_manager = DatabaseManager(Config.DATABASE_URL)
        await self.db_manager.init_db()
        self.db_session = await self.db_manager.get_session()
        
        # Инициализируем Redis (для кэширования и других операций)
        if Config.REDIS_ENABLED:
            try:
                self.redis_service = RedisService(redis_url=Config.REDIS_URL)
                await self.redis_service.connect()
                logger.info(f"✅ Redis подключен: {Config.REDIS_URL}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}, продолжаем без Redis")
                self.redis_service = None
        else:
            logger.info("ℹ️ Redis отключен в конфигурации")
            self.redis_service = None
        
        # Инициализируем RabbitMQ (обязательно для воркера)
        if not Config.RABBITMQ_ENABLED:
            logger.error("❌ RabbitMQ должен быть включен для Parsing Worker!")
            logger.error("   Установите RABBITMQ_ENABLED=true в .env")
            raise ValueError("RabbitMQ должен быть включен для Parsing Worker")
        
        # Пытаемся подключиться к RabbitMQ с retry механизмом
        # Это позволяет воркеру ждать, пока RabbitMQ запустится (например, после перезагрузки)
        self.rabbitmq_service = RabbitMQService(rabbitmq_url=Config.RABBITMQ_URL)
        max_retries = 30  # Максимум 30 попыток
        retry_delay = 5  # Задержка 5 секунд между попытками
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                await self.rabbitmq_service.connect()
                logger.info(f"✅ RabbitMQ подключен: {Config.RABBITMQ_URL}")
                break
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"❌ Не удалось подключиться к RabbitMQ после {max_retries} попыток: {e}")
                    logger.error(f"   Проверьте, что RabbitMQ запущен и доступен по адресу: {Config.RABBITMQ_URL}")
                    raise
                else:
                    logger.warning(
                        f"⚠️ Не удалось подключиться к RabbitMQ (попытка {retry_count}/{max_retries}): {e}"
                    )
                    logger.info(f"   Повторная попытка через {retry_delay} секунд...")
                    await asyncio.sleep(retry_delay)
        
        # Инициализируем менеджер прокси с Redis для кэширования (после инициализации Redis)
        # Инициализируем менеджер прокси через фабрику
        from services.proxy_manager_factory import ProxyManagerFactory
        self.proxy_manager = await ProxyManagerFactory.get_instance(
            db_session=self.db_session,
            redis_service=self.redis_service,
            default_delay=0.2,  # Оптимальная частота из RATE_LIMITS_ANALYSIS.md
            site="steam"
        )
        
        # ВАЖНО: Выполняем полную проверку всех прокси при запуске для актуализации статусов в Redis
        # Это гарантирует, что get_active_proxies вернет только действительно работающие прокси
        logger.info("🔍 Выполняем полную проверку всех прокси при запуске для актуализации статусов...")
        try:
            check_result = await self.proxy_manager.check_and_update_all_proxies_status(max_concurrent=20)
            logger.info(
                f"✅ Проверка прокси завершена: "
                f"всего={check_result.get('total', 0)}, "
                f"работают={check_result.get('working', 0)}, "
                f"rate_limited={check_result.get('rate_limited', 0)}, "
                f"заблокировано в Redis={check_result.get('blocked_count', 0)}, "
                f"разблокировано в Redis={check_result.get('unblocked_count', 0)}"
            )
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при проверке прокси при запуске: {e}, продолжаем работу")
        
        # Запускаем фоновую проверку заблокированных прокси
        self.proxy_manager.start_background_proxy_check()
        
        # Инициализируем сервис парсинга с Redis для кэширования
        self.parsing_service = ParsingService(proxy_manager=self.proxy_manager, redis_service=self.redis_service)
        
        # Инициализируем сервис мониторинга (для получения задач из БД)
        self.monitoring_service = MonitoringService(
            self.db_session,
            self.proxy_manager,
            notification_callback=None,  # Уведомления отправляет Telegram бот
            parsing_service=self.parsing_service,
            redis_service=self.redis_service,
            rabbitmq_service=self.rabbitmq_service
        )
        
        logger.info("✅ Parsing Worker инициализирован")
    
    async def shutdown(self):
        """Корректно завершает работу."""
        logger.info("Завершение работы Parsing Worker...")
        
        self._running = False
        
        if self.monitoring_service:
            await self.monitoring_service.stop()
        
        # Останавливаем фоновую проверку прокси
        if self.proxy_manager:
            self.proxy_manager.stop_background_proxy_check()
        
        if self.redis_service:
            try:
                await self.redis_service.disconnect()
            except Exception as e:
                logger.warning(f"Ошибка при остановке Redis: {e}")
        
        if self.rabbitmq_service:
            try:
                await self.rabbitmq_service.disconnect()
            except Exception as e:
                logger.warning(f"Ошибка при остановке RabbitMQ: {e}")
        
        if self.db_session:
            await self.db_session.close()
        
        if self.db_manager:
            await self.db_manager.close()
        
        logger.info("Parsing Worker завершен")
    
    # Метод _handle_parsing_task больше не используется - задачи обрабатываются напрямую из очереди в run()
    
    async def _process_parsing_task(self, message: dict):
        """
        Обрабатывает задачу парсинга (внутренний метод, вызывается асинхронно).
        
        Args:
            message: Словарь с данными задачи
        """
        task_id = None
        task_logger = None
        task_db_session = None  # Инициализируем заранее для finally блока
        
        try:
            # Проверяем, что message является словарем
            if not isinstance(message, dict):
                logger.warning(f"⚠️ ParsingWorker: Получено некорректное сообщение (не словарь): {type(message)}")
                return
            
            # Проверяем, что это задача парсинга
            if message.get("type") != "parsing_task":
                logger.debug(f"   ⏭️ Пропускаем сообщение (не parsing_task): type={message.get('type')}")
                return
            
            task_id = message.get("task_id")
            
            if not task_id:
                logger.warning(f"⚠️ ParsingWorker: Сообщение не содержит task_id: {message}")
                return
            
            # Детальное логирование начала обработки задачи
            logger.info(f"🚀 ParsingWorker: ===== НАЧАЛО ОБРАБОТКИ ЗАДАЧИ {task_id} =====")
            logger.info(f"   📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"   📋 Данные задачи: item_name='{message.get('item_name', 'N/A')}', appid={message.get('appid', 'N/A')}")
            
            # ВАЖНО: Используем атомарную операцию SET NX для установки флага "задача выполняется"
            # Это предотвращает параллельный запуск нескольких экземпляров (race condition)
            task_running_key = f"parsing_task_running:{task_id}"
            is_already_running = False
            heartbeat_task = None  # Фоновая задача для обновления TTL
            heartbeat_stop_event = asyncio.Event()  # Событие для остановки heartbeat
            
            try:
                if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                    # Атомарная операция: SET key value NX EX timeout
                    # NX = set only if not exists (атомарно)
                    # EX = expire after timeout seconds
                    # Возвращает True если ключ был установлен, False если уже существовал
                    # TTL увеличен до 60 минут для длительных задач (до 100 страниц)
                    # Сохраняем время начала выполнения в значении флага для отслеживания зависших задач
                    task_start_timestamp = datetime.now().isoformat()
                    result = await self.redis_service._client.set(
                        task_running_key, 
                        task_start_timestamp,  # Сохраняем время начала выполнения
                        nx=True,  # Только если не существует (атомарно)
                        ex=3600   # TTL 60 минут для длительных задач
                    )
                    if not result:
                        # Ключ уже существует - задача уже выполняется
                        # ВАЖНО: Проверяем, существует ли задача в БД (защита от "зависших" флагов после удаления задачи)
                        is_already_running = True
                        logger.warning(f"⏸️ ParsingWorker: Задача {task_id} - флаг выполнения УЖЕ УСТАНОВЛЕН")
                        logger.warning(f"   🔍 Проверяем, действительно ли задача выполняется другим воркером или это зависший флаг...")
                        
                        # Проверяем время начала выполнения для обнаружения зависших задач
                        STUCK_TASK_TIMEOUT = 10 * 60  # 10 минут - максимальное время выполнения задачи
                        try:
                            if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                                flag_value = await self.redis_service._client.get(task_running_key)
                                if flag_value:
                                    try:
                                        # Пытаемся извлечь время начала выполнения
                                        flag_str = flag_value.decode('utf-8') if isinstance(flag_value, bytes) else flag_value
                                        task_start_time = datetime.fromisoformat(flag_str)
                                        elapsed_time = (datetime.now() - task_start_time).total_seconds()
                                        
                                        if elapsed_time > STUCK_TASK_TIMEOUT:
                                            logger.warning(f"⚠️ ParsingWorker: Обнаружен ЗАВИСШИЙ флаг для задачи {task_id}!")
                                            logger.warning(f"   ⏱️ Время выполнения: {elapsed_time/60:.1f} минут (превышен лимит {STUCK_TASK_TIMEOUT/60:.0f} минут)")
                                            logger.warning(f"   🔄 Удаляем зависший флаг...")
                                            
                                            # Удаляем зависший флаг
                                            deleted = await self.redis_service._client.delete(task_running_key)
                                            if deleted:
                                                logger.info(f"✅ ParsingWorker: Зависший флаг для задачи {task_id} УДАЛЕН")
                                                # Продолжаем выполнение - попробуем установить флаг заново
                                                result = await self.redis_service._client.set(
                                                    task_running_key,
                                                    datetime.now().isoformat(),
                                                    nx=True,
                                                    ex=3600
                                                )
                                                if result:
                                                    logger.info(f"✅ ParsingWorker: Флаг выполнения УСТАНОВЛЕН заново для задачи {task_id}")
                                                else:
                                                    logger.warning(f"⚠️ ParsingWorker: Не удалось установить флаг для задачи {task_id} (возможно, другой воркер уже взял задачу)")
                                                    return
                                            else:
                                                logger.warning(f"⚠️ ParsingWorker: Не удалось удалить зависший флаг для задачи {task_id}")
                                                return
                                    except (ValueError, AttributeError):
                                        # Не удалось распарсить timestamp - проверяем через БД
                                        pass
                        except Exception as stuck_check_error:
                            logger.debug(f"⚠️ ParsingWorker: Ошибка при проверке зависшей задачи {task_id}: {stuck_check_error}")
                        
                        # Создаем временную сессию для проверки
                        temp_db_session = await self.db_manager.get_session()
                        try:
                            from core import MonitoringTask
                            task = await temp_db_session.get(MonitoringTask, task_id)
                            if not task:
                                # Задача не существует - удаляем "зависший" флаг
                                logger.warning(f"⚠️ ParsingWorker: Задача {task_id} НЕ НАЙДЕНА в БД - это ЗАВИСШИЙ флаг!")
                                try:
                                    if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                                        await self.redis_service._client.delete(task_running_key)
                                        logger.info(f"✅ ParsingWorker: Зависший флаг для задачи {task_id} УДАЛЕН, задача может быть выполнена")
                                except Exception as delete_error:
                                    logger.warning(f"⚠️ ParsingWorker: Не удалось удалить зависший флаг для задачи {task_id}: {delete_error}")
                                return
                            else:
                                # Задача существует - действительно выполняется другим воркером
                                logger.info(f"✅ ParsingWorker: Задача {task_id} существует в БД - выполняется другим воркером")
                                logger.info(f"   ℹ️ Пропускаем эту задачу, дождемся завершения текущего выполнения")
                                return
                        except Exception as check_error:
                            logger.warning(f"⚠️ ParsingWorker: Ошибка при проверке задачи {task_id} в БД: {check_error}")
                            # В случае ошибки просто пропускаем задачу
                            return
                        finally:
                            await temp_db_session.close()
                    else:
                        logger.info(f"🔒 ParsingWorker: ✅ ФЛАГ ВЫПОЛНЕНИЯ УСТАНОВЛЕН для задачи {task_id}")
                        logger.info(f"   ⏱️ TTL: 60 минут (автоматически обновляется heartbeat)")
                        logger.info(f"   🚀 Задача {task_id} готова к выполнению")
                        
                        # Запускаем фоновую задачу для обновления TTL (heartbeat)
                        async def heartbeat_loop():
                            """Периодически обновляет TTL флага выполнения, чтобы задача не истекла во время длительного парсинга."""
                            try:
                                while not heartbeat_stop_event.is_set():
                                    # Ждем 5 минут перед обновлением TTL
                                    try:
                                        await asyncio.wait_for(heartbeat_stop_event.wait(), timeout=300.0)
                                        break  # Событие установлено, выходим
                                    except asyncio.TimeoutError:
                                        # Таймаут - обновляем TTL
                                        if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                                            try:
                                                # Проверяем, что флаг еще существует
                                                exists = await self.redis_service._client.exists(task_running_key)
                                                if exists:
                                                    # Обновляем TTL до 60 минут
                                                    await self.redis_service._client.expire(task_running_key, 3600)
                                                    logger.debug(f"💓 ParsingWorker: Heartbeat - обновлен TTL флага для задачи {task_id} (60 минут)")
                                                    if task_logger:
                                                        task_logger.debug(f"💓 Heartbeat - флаг выполнения обновлен")
                                                else:
                                                    logger.warning(f"⚠️ ParsingWorker: Флаг для задачи {task_id} не существует, останавливаем heartbeat")
                                                    break
                                            except Exception as heartbeat_error:
                                                logger.warning(f"⚠️ ParsingWorker: Ошибка при обновлении TTL для задачи {task_id}: {heartbeat_error}")
                            except Exception as e:
                                logger.error(f"❌ ParsingWorker: Критическая ошибка в heartbeat для задачи {task_id}: {e}")
                        
                        # Запускаем heartbeat в фоне
                        heartbeat_task = asyncio.create_task(heartbeat_loop())
                        logger.debug(f"💓 ParsingWorker: Запущен heartbeat для задачи {task_id}")
            except Exception as e:
                logger.warning(f"⚠️ ParsingWorker: Не удалось установить/проверить флаг выполнения для задачи {task_id}: {e}")
            
            # Устанавливаем task_id в контексте и получаем логгер для задачи
            task_logger = None
            try:
                set_task_id(task_id)
                task_logger = get_task_logger(task_id)
            except Exception as logger_error:
                logger.warning(f"⚠️ Не удалось создать логгер для задачи {task_id}: {logger_error}")
            
            logger.info(f"📥 ParsingWorker: Получена задача парсинга: task_id={task_id}")
            if task_logger:
                task_logger.info(f"📥 Получена задача парсинга из Redis")
            logger.debug(f"   Данные задачи: {message}")
            
            # Получаем задачу из БД
            # ВАЖНО: Создаем отдельную сессию для каждой задачи, чтобы избежать конфликтов при параллельной обработке
            from core import MonitoringTask, SearchFilters
            logger.info(f"🔍 ParsingWorker: Загружаем задачу {task_id} из БД")
            task_logger.info(f"🔍 Загружаем задачу из БД")
            
            # Создаем отдельную сессию для этой задачи, чтобы избежать конфликтов при параллельной обработке
            task_db_session = await self.db_manager.get_session()
            try:
                task = await task_db_session.get(MonitoringTask, task_id)
                
                if not task:
                    logger.error(f"❌ ParsingWorker: Задача {task_id} не найдена в БД")
                    task_logger.error(f"❌ Задача не найдена в БД")
                    # Удаляем флаг, если задача не найдена
                    try:
                        if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                            await self.redis_service._client.delete(task_running_key)
                    except:
                        pass
                    return
                
                logger.info(f"✅ ParsingWorker: Задача {task_id} найдена: {task.name}, активна: {task.is_active}")
                task_logger.info(f"✅ Задача найдена: {task.name}, активна: {task.is_active}")
                
                if not task.is_active:
                    logger.warning(f"⚠️ ParsingWorker: Задача {task_id} неактивна, пропускаем")
                    task_logger.warning(f"⚠️ Задача неактивна, пропускаем")
                    # Удаляем флаг, если задача неактивна
                    try:
                        if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                            await self.redis_service._client.delete(task_running_key)
                    except:
                        pass
                    return
                
                # Загружаем фильтры
                logger.info(f"🔍 DEBUG: Загружаем фильтры из задачи {task_id}")
                task_logger.debug(f"Загружаем фильтры из задачи")
                logger.info(f"🔍 DEBUG: task.filters_json = {task.filters_json}")
                task_logger.debug(f"task.filters_json = {task.filters_json}")
                # ВАЖНО: filters_json может быть строкой JSON или словарем (JSONB)
                filters_json = task.filters_json
                if isinstance(filters_json, str):
                    import json
                    filters_json = json.loads(filters_json)
                filters = SearchFilters.model_validate(filters_json)
                filters.item_name = task.item_name
                filters.appid = task.appid
                filters.currency = task.currency
                
                # Логируем значения фильтров наклеек
                if filters.stickers_filter:
                    logger.info(f"🔍 DEBUG: filters.stickers_filter.min_stickers_price = {filters.stickers_filter.min_stickers_price}")
                    task_logger.debug(f"filters.stickers_filter.min_stickers_price = {filters.stickers_filter.min_stickers_price}")
                    logger.info(f"🔍 DEBUG: filters.stickers_filter.max_overpay_coefficient = {filters.stickers_filter.max_overpay_coefficient}")
                    task_logger.debug(f"filters.stickers_filter.max_overpay_coefficient = {filters.stickers_filter.max_overpay_coefficient}")
                
                # Детальное логирование фильтров
                logger.info(f"🔍 DEBUG: filters.pattern_list = {filters.pattern_list}")
                task_logger.debug(f"filters.pattern_list = {filters.pattern_list}")
                logger.info(f"🔍 DEBUG: filters.pattern_range = {filters.pattern_range}")
                task_logger.debug(f"filters.pattern_range = {filters.pattern_range}")
                if filters.pattern_list:
                    logger.info(f"🔍 DEBUG: pattern_list.patterns = {filters.pattern_list.patterns}")
                    task_logger.debug(f"pattern_list.patterns = {filters.pattern_list.patterns}")
                    logger.info(f"🔍 DEBUG: pattern_list.item_type = {filters.pattern_list.item_type}")
                    task_logger.debug(f"pattern_list.item_type = {filters.pattern_list.item_type}")
                
                logger.info(f"🔍 ParsingWorker: Выполняем парсинг для задачи {task_id}: '{filters.item_name}'")
                task_logger.info(f"🔍 Выполняем парсинг: '{filters.item_name}'")
                
                # Выполняем парсинг
                task_logger.info(f"🚀 Начинаем парсинг предметов")
                parse_start_time = datetime.now()
                logger.info(f"⏱️ ParsingWorker: ===== НАЧАЛО ПАРСИНГА задачи {task_id} =====")
                logger.info(f"   📅 Время начала: {parse_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"   📋 Параметры: item_name='{filters.item_name}', appid={filters.appid}, currency={filters.currency}")
                if task_logger:
                    task_logger.info(f"⏱️ Начало выполнения в {parse_start_time.strftime('%H:%M:%S')}")
                
                # Передаем task, db_session, redis_service в parsing_service для доступа в parse_all_listings
                # ВАЖНО: parsing_service должен установить их в parser перед вызовом search_items
                logger.info(f"🚀 ParsingWorker: [КРИТИЧЕСКИЙ ШАГ] Вызываем parsing_service.parse_items() для задачи {task_id}...")
                logger.info(f"   📋 Параметры: item_name='{filters.item_name}', appid={filters.appid}, start=0, count=10")
                logger.info(f"   🔧 parsing_service={self.parsing_service is not None}, db_session={task_db_session is not None}, redis_service={self.redis_service is not None}")
                try:
                    result = await self.parsing_service.parse_items(
                        filters, 
                        start=0, 
                        count=10,
                        task=task,
                        db_session=task_db_session,
                        redis_service=self.redis_service,
                        db_manager=self.db_manager
                    )
                    logger.info(f"✅ ParsingWorker: [КРИТИЧЕСКИЙ ШАГ] parsing_service.parse_items() завершен для задачи {task_id}")
                except Exception as e:
                    logger.error(f"❌ ParsingWorker: [КРИТИЧЕСКИЙ ШАГ] ОШИБКА в parsing_service.parse_items() для задачи {task_id}: {e}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    raise
                parse_end_time = datetime.now()
                parse_duration = (parse_end_time - parse_start_time).total_seconds()
                logger.info(f"⏱️ ParsingWorker: ===== ПАРСИНГ ЗАВЕРШЕН для задачи {task_id} =====")
                logger.info(f"   📅 Время завершения: {parse_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"   ⏱️ Длительность: {parse_duration:.1f} секунд ({parse_duration/60:.1f} минут)")
                logger.info(f"   📊 Результат: success={result.get('success', False)}, items_count={len(result.get('items', []))}")
                if task_logger:
                    task_logger.info(f"⏱️ Выполнение завершено за {parse_duration:.1f} секунд ({parse_duration/60:.1f} минут)")
                
                items_count = len(result.get('items', []))
                logger.info(
                    f"📊 Результат парсинга для задачи {task_id}: "
                    f"success={result.get('success')}, "
                    f"total={result.get('total_count', 0)}, "
                    f"filtered={result.get('filtered_count', 0)}, "
                    f"items={items_count}"
                )
                task_logger.info(
                    f"📊 Результат парсинга: "
                    f"success={result.get('success')}, "
                    f"total={result.get('total_count', 0)}, "
                    f"filtered={result.get('filtered_count', 0)}, "
                    f"items={items_count}"
                )
                
                # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ для диагностики
                if items_count > 0:
                    items_list = result.get('items', [])
                    logger.info(f"🔍 DEBUG: Первые 3 предмета из result.get('items'):")
                    for idx, item in enumerate(items_list[:3]):
                        item_name = item.get('name', item.get('asset_description', {}).get('market_hash_name', 'Unknown'))
                        listing_id = item.get('listingid') or item.get('parsed_data', {}).get('listing_id')
                        price = item.get('parsed_data', {}).get('item_price') or item.get('sell_price_text', 'N/A')
                        logger.info(f"  [{idx+1}] {item_name}, listing_id={listing_id}, price={price}")
                        task_logger.info(f"  [{idx+1}] {item_name}, listing_id={listing_id}, price={price}")
                else:
                    # ВАЖНО: Пустой items - это нормально, если success=True (просто не нашлось подходящих лотов)
                    # Предупреждение только если success=False или items отсутствует в результате
                    if not result.get('success', False):
                        logger.warning(f"⚠️ DEBUG: result.get('items') пустой или None при success=False! result.keys()={list(result.keys())}")
                        task_logger.warning(f"⚠️ result.get('items') пустой или None при success=False!")
                    elif 'items' not in result:
                        logger.warning(f"⚠️ DEBUG: Ключ 'items' отсутствует в result! result.keys()={list(result.keys())}")
                        task_logger.warning(f"⚠️ Ключ 'items' отсутствует в result!")
                    else:
                        # success=True и items=[], это нормально - просто не нашлось подходящих лотов
                        logger.debug(f"ℹ️ DEBUG: result.get('items') пустой, но success=True (не нашлось подходящих лотов) - это нормально")
                        task_logger.debug(f"ℹ️ result.get('items') пустой, но success=True (не нашлось подходящих лотов) - это нормально")
                
                # Обновляем статистику задачи (всегда, даже если предметы не найдены)
                # ВАЖНО: Обновляем объект через refresh перед изменением, чтобы избежать проблем с async контекстом
                try:
                    await task_db_session.refresh(task)
                except Exception as refresh_error:
                    # Если refresh не удался (например, задача была удалена), делаем rollback и выходим
                    logger.warning(f"⚠️ Не удалось обновить задачу {task_id} из БД: {refresh_error}")
                    try:
                        await task_db_session.rollback()
                    except Exception:
                        pass
                    # Пытаемся загрузить задачу заново
                    task = await task_db_session.get(MonitoringTask, task_id)
                    if not task:
                        logger.error(f"❌ Задача {task_id} не найдена в БД после ошибки refresh")
                        return
                    logger.info(f"✅ Задача {task_id} перезагружена из БД")
                
                task.total_checks += 1
                task.last_check = datetime.now()
                
                # ВАЖНО: Обновляем next_check после завершения парсинга
                # Это гарантирует, что задача будет запускаться повторно через заданный интервал
                from datetime import timedelta
                task.next_check = datetime.now() + timedelta(seconds=task.check_interval)
                logger.info(f"⏰ ParsingWorker: Установлена следующая проверка для задачи {task_id}: {task.next_check.strftime('%Y-%m-%d %H:%M:%S')}")
                if task_logger:
                    task_logger.info(f"⏰ Следующая проверка в {task.next_check.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # ВАЖНО: После успешного выполнения добавляем задачу обратно в RabbitMQ очередь
                # с задержкой равной check_interval для повторного запуска
                if self.rabbitmq_service and self.rabbitmq_service.is_connected():
                    try:
                        # Формируем данные задачи для повторной публикации
                        task_data_for_requeue = {
                            "type": "parsing_task",
                            "task_id": task_id,
                            "filters_json": task.filters_json,
                            "item_name": task.item_name,
                            "appid": task.appid,
                            "currency": task.currency
                        }
                        
                        # Публикуем задачу с задержкой (в секундах)
                        delay_seconds = max(task.check_interval, 10)  # Минимум 10 секунд
                        await self.rabbitmq_service.requeue_task(task_data_for_requeue, delay_seconds=delay_seconds)
                        logger.info(f"🔄 ParsingWorker: Задача {task_id} добавлена обратно в очередь для повторного запуска через {delay_seconds}с")
                        if task_logger:
                            task_logger.info(f"🔄 Задача добавлена обратно в очередь для повторного запуска через {delay_seconds}с")
                    except Exception as requeue_error:
                        logger.warning(f"⚠️ ParsingWorker: Не удалось добавить задачу {task_id} обратно в очередь: {requeue_error}")
                        if task_logger:
                            task_logger.warning(f"⚠️ Не удалось добавить задачу обратно в очередь: {requeue_error}")
                
                # Обрабатываем результаты парсинга через универсальный сервис
                # ВАЖНО: Если результаты уже обработаны в параллельном парсере (сразу после нахождения),
                # то items_list будет пустым, и ResultsProcessorService не будет вызываться
                # Это предотвращает повторную публикацию уведомлений
                found_count = 0
                if result.get('success') and result.get('items'):
                    items_list = result.get('items', [])
                    logger.info(f"📦 ParsingWorker: Получено {len(items_list)} предметов для обработки")
                    task_logger.info(f"📦 Получено {len(items_list)} предметов для обработки")
                    
                    if len(items_list) > 0:
                        # Используем ResultsProcessorService только если есть необработанные результаты
                        # Если результаты уже обработаны в параллельном парсере, items_list будет пустым
                        results_processor = ResultsProcessorService(
                            db_session=task_db_session,
                            redis_service=self.redis_service
                        )
                        
                        found_count = await results_processor.process_results(
                            task=task,
                            items=items_list,
                            task_logger=task_logger
                        )
                        # results_processor.process_results уже делает commit, который сохранит все изменения задачи
                    else:
                        logger.info(f"ℹ️ ParsingWorker: Список предметов пуст - результаты уже обработаны в параллельном парсере (уведомления отправлены сразу)")
                        task_logger.info(f"ℹ️ Результаты уже обработаны, уведомления отправлены сразу")
                else:
                    if not result.get('success'):
                        logger.warning(f"⚠️ Парсинг неуспешен для задачи {task_id}: {result.get('error', 'Unknown error')}")
                        task_logger.warning(f"⚠️ Парсинг неуспешен: {result.get('error', 'Unknown error')}")
                    else:
                        logger.info(f"ℹ️ Предметы не найдены для задачи {task_id} (после фильтрации)")
                        task_logger.info(f"ℹ️ Предметы не найдены (после фильтрации)")
                    
                    # Если предметы не найдены, results_processor не вызывается, нужно сохранить изменения вручную
                    try:
                        await task_db_session.commit()
                        logger.info(f"✅ ParsingWorker: Задача {task_id} обновлена в БД: проверок={task.total_checks}, найдено={task.items_found}, next_check={task.next_check.strftime('%Y-%m-%d %H:%M:%S')}")
                        if task_logger:
                            task_logger.info(f"✅ Задача обновлена: проверок={task.total_checks}, найдено={task.items_found}")
                    except Exception as commit_error:
                        logger.error(f"❌ ParsingWorker: Ошибка при сохранении задачи {task_id} в БД: {commit_error}")
                        if task_logger:
                            task_logger.error(f"❌ Ошибка при сохранении задачи: {commit_error}")
                        try:
                            await task_db_session.rollback()
                        except Exception:
                            pass
                
            except Exception as e:
                logger.error(f"❌ Ошибка при обработке задачи парсинга: {e}")
                if task_logger:
                    task_logger.exception(f"❌ Ошибка при обработке задачи парсинга: {e}")
                import traceback
                logger.debug(f"Traceback: {traceback.format_exc()}")
            # Откатываем транзакцию при ошибке
            try:
                await task_db_session.rollback()
                logger.debug("✅ Транзакция откачена после ошибки")
                if task_logger:
                    task_logger.debug("✅ Транзакция откачена после ошибки")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате транзакции: {rollback_error}")
                if task_logger:
                    task_logger.error(f"❌ Ошибка при откате транзакции: {rollback_error}")
        finally:
            # Останавливаем heartbeat перед очисткой флага
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_stop_event.set()
                try:
                    await asyncio.wait_for(heartbeat_task, timeout=2.0)
                    logger.debug(f"💓 ParsingWorker: Heartbeat для задачи {task_id} остановлен")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ ParsingWorker: Heartbeat для задачи {task_id} не остановился вовремя, отменяем")
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                except Exception as e:
                    logger.warning(f"⚠️ ParsingWorker: Ошибка при остановке heartbeat для задачи {task_id}: {e}")
            
            # Закрываем сессию БД для этой задачи (если она была создана)
            if task_db_session is not None:
                try:
                    await task_db_session.close()
                    logger.debug(f"✅ Сессия БД для задачи {task_id} закрыта")
                except Exception as close_error:
                    logger.warning(f"⚠️ Ошибка при закрытии сессии БД для задачи {task_id}: {close_error}")
            
            # ВАЖНО: Удаляем флаг "задача выполняется" из Redis
            # Это гарантирует, что флаг будет удален даже при ошибках
            if task_id:
                task_running_key = f"parsing_task_running:{task_id}"
                try:
                    if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                        await self.redis_service._client.delete(task_running_key)
                        logger.info(f"🔓 ParsingWorker: ===== ЗАДАЧА {task_id} ЗАВЕРШЕНА =====")
                        logger.info(f"   ✅ Флаг выполнения УДАЛЕН из Redis")
                        logger.info(f"   📅 Время завершения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        if task_logger:
                            task_logger.info(f"🔓 Задача завершена, флаг выполнения удален")
                except Exception as e:
                    logger.error(f"❌ ParsingWorker: КРИТИЧЕСКАЯ ОШИБКА - не удалось удалить флаг выполнения для задачи {task_id}: {e}")
                    # Пытаемся еще раз через небольшую задержку
                    try:
                        await asyncio.sleep(0.5)
                        if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                            await self.redis_service._client.delete(task_running_key)
                            logger.info(f"🔓 ParsingWorker: Флаг для задачи {task_id} удален после повторной попытки")
                    except Exception as retry_error:
                        logger.error(f"❌ ParsingWorker: Не удалось удалить флаг для задачи {task_id} даже после повторной попытки: {retry_error}")
            
            # Очищаем task_id из контекста
            set_task_id(None)
    
    async def _process_task_with_semaphore_rabbitmq(self, task_data: dict, message: Any):
        """
        Обрабатывает задачу из RabbitMQ с использованием семафора.
        
        Args:
            task_data: Данные задачи
            message: Сообщение RabbitMQ (для подтверждения - не используется здесь, подтверждается в task_handler)
        """
        async with self._task_semaphore:
            # Обрабатываем задачу
            # Сообщение будет подтверждено в task_handler после успешной обработки
            await self._process_parsing_task(task_data)
    
    async def _remove_task(self, task: asyncio.Task):
        """
        Удаляет задачу из отслеживания после завершения.
        
        Args:
            task: Завершенная задача
        """
        async with self._tasks_lock:
            self._active_tasks.discard(task)
            logger.debug(f"📊 ParsingWorker: Активных задач: {len(self._active_tasks)}")
    
    async def run(self):
        """Запускает воркер."""
        try:
            await self.initialize()
            
            # Запускаем сервис мониторинга только если включен (по умолчанию включен)
            # Это позволяет иметь несколько воркеров, но только один запускает мониторинг
            if Config.ENABLE_MONITORING_SERVICE:
                logger.info("🚀 ParsingWorker: Запускаем сервис мониторинга...")
                await self.monitoring_service.start()
                logger.info("✅ ParsingWorker: Сервис мониторинга запущен")
            else:
                logger.info("⏭️ ParsingWorker: Мониторинг отключен (ENABLE_MONITORING_SERVICE=false), только обработка задач из очереди")
            
            self._running = True
            logger.info("🚀 ParsingWorker: Запущен и готов к работе")
            logger.info("   📡 Ожидаем задачи из RabbitMQ очереди 'parsing_tasks'...")
            
            # Параллельная обработка: несколько задач могут выполняться одновременно
            logger.info(f"🚀 ParsingWorker: Параллельная обработка включена (макс. {self._task_semaphore._value} одновременных задач)")
            
            # Запускаем потребителя RabbitMQ
            import socket
            consumer_name = f"worker-{socket.gethostname()}"
            
            async def task_handler(task_data: Dict[str, Any], message: Any):
                """
                Обработчик задач из RabbitMQ.
                
                Args:
                    task_data: Данные задачи
                    message: Сообщение RabbitMQ (для подтверждения)
                """
                try:
                    # Проверяем, что task_data является словарем
                    if not isinstance(task_data, dict):
                        logger.warning(f"⚠️ ParsingWorker: Получено некорректное сообщение (не словарь): {type(task_data)}")
                        await message.ack()  # Подтверждаем некорректное сообщение, чтобы оно не застряло
                        return
                    
                    task_id = task_data.get('task_id')
                    logger.debug(f"📥 ParsingWorker: Получена задача из RabbitMQ: {task_data.get('type')}, task_id={task_id}")
                    
                    # Запускаем обработку задачи в фоне (параллельно)
                    # Используем семафор для ограничения количества одновременных задач
                    task = asyncio.create_task(
                        self._process_task_with_semaphore_rabbitmq(task_data, message)
                    )
                    
                    # Добавляем задачу в отслеживание
                    async with self._tasks_lock:
                        self._active_tasks.add(task)
                    
                    # Удаляем задачу из отслеживания после завершения
                    task.add_done_callback(lambda t: asyncio.create_task(self._remove_task(t)))
                    
                    # Ждем завершения задачи перед подтверждением сообщения
                    try:
                        await task
                        # Подтверждаем сообщение только после успешной обработки
                        await message.ack()
                        logger.debug(f"✅ ParsingWorker: Задача {task_id} успешно обработана и подтверждена")
                    except Exception as task_error:
                        # Ошибка при обработке - пробрасываем для retry механизма
                        logger.error(f"❌ ParsingWorker: Ошибка при обработке задачи {task_id}: {task_error}")
                        raise
                except Exception as e:
                    logger.error(f"❌ ParsingWorker: Ошибка в обработчике задач: {e}")
                    # При ошибке сообщение будет обработано механизмом retry в RabbitMQ
                    raise  # Пробрасываем ошибку, чтобы RabbitMQ обработал retry
            
            # Запускаем потребителя RabbitMQ
            await self.rabbitmq_service.consume_tasks(
                callback=task_handler,
                consumer_name=consumer_name
            )
            
            # Ждем сигнала завершения
            await self._shutdown_event.wait()
            
            # Ждем завершения всех активных задач перед выходом
            logger.info("⏳ ParsingWorker: Ожидаем завершения активных задач...")
            async with self._tasks_lock:
                if self._active_tasks:
                    logger.info(f"   Активных задач: {len(self._active_tasks)}")
                    await asyncio.gather(*self._active_tasks, return_exceptions=True)
                    logger.info("✅ ParsingWorker: Все активные задачи завершены")
            
            logger.info("🛑 ParsingWorker: Остановка обработки задач из очереди")
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise
        finally:
            await self.shutdown()


async def main():
    """Точка входа."""
    worker = ParsingWorker()
    exit_code = 0
    
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.exception(f"Необработанная ошибка: {e}")
        exit_code = 1
    finally:
        # ВАЖНО: Всегда закрываем соединения перед выходом
        try:
            await worker.shutdown()
        except Exception as e:
            logger.error(f"Ошибка при завершении работы: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
    
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())

