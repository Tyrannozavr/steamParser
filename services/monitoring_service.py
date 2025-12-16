"""
Сервис для мониторинга нескольких предметов с использованием БД и прокси.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from loguru import logger

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import MonitoringTask, FoundItem, SearchFilters
from core.database import DatabaseManager
from services.proxy_manager import ProxyManager
from services.parsing_service import ParsingService
from services.redis_service import RedisService
from services.rabbitmq_service import RabbitMQService
from typing import Optional, Callable, TYPE_CHECKING


class MonitoringService:
    """Сервис для мониторинга предметов на Steam Market."""
    
    def __init__(
        self,
        db_session: AsyncSession,
        proxy_manager: ProxyManager,
        notification_callback: Optional[Callable] = None,
        parsing_service: Optional[ParsingService] = None,
        redis_service: Optional[RedisService] = None,
        rabbitmq_service: Optional[RabbitMQService] = None,
        db_manager: Optional[DatabaseManager] = None
    ):
        """
        Инициализация сервиса мониторинга.
        
        Args:
            db_session: Сессия базы данных (используется для синхронных операций)
            proxy_manager: Менеджер прокси
            notification_callback: Функция для отправки уведомлений (item, task) - используется если Redis не доступен
            parsing_service: Сервис парсинга (если None, создается автоматически)
            redis_service: Сервис Redis для асинхронных уведомлений (опционально)
            db_manager: Менеджер БД для создания отдельных сессий в корутинах (опционально, рекомендуется)
        """
        self.db_session = db_session
        self.db_manager = db_manager  # Для создания отдельных сессий в корутинах
        self.proxy_manager = proxy_manager
        self.notification_callback = notification_callback
        self.redis_service = redis_service
        self.rabbitmq_service = rabbitmq_service
        self._running = False
        self._tasks: Dict[int, asyncio.Task] = {}
        self._task_sessions: Dict[int, AsyncSession] = {}  # Отдельные сессии для каждой задачи
        self._recovery_tasks: Dict[int, asyncio.Task] = {}  # Задачи восстановления
        self._session_lock = asyncio.Lock()  # Блокировка для безопасной работы с основной сессией
        # Используем отдельный сервис парсинга с Redis для кэширования
        self.parsing_service = parsing_service or ParsingService(proxy_manager=proxy_manager, redis_service=redis_service)
    
    async def add_monitoring_task(
        self,
        name: str,
        item_name: str,
        filters: SearchFilters,
        check_interval: int = 60  # Интервал проверки в секундах
    ) -> MonitoringTask:
        """
        Добавляет новую задачу мониторинга.
        
        Args:
            name: Название задачи
            item_name: Название предмета
            filters: Фильтры поиска
            check_interval: Интервал проверки в секундах
            
        Returns:
            Созданная задача мониторинга
        """
        # Сохраняем фильтры как JSONB
        filters_dict = filters.model_dump(exclude_none=True)
        
        task = MonitoringTask(
            name=name,
            item_name=item_name,
            appid=filters.appid,
            currency=filters.currency,
            filters_json=filters_dict,  # Теперь сохраняем как dict для JSONB
            check_interval=check_interval,
            is_active=True,
            next_check=None  # Гарантируем, что первая проверка начнется сразу
        )
        
        self.db_session.add(task)
        await self.db_session.commit()
        await self.db_session.refresh(task)
        
        logger.info(f"Добавлена задача мониторинга: {name} (ID: {task.id}), интервал: {check_interval} сек")
        
        # ВАЖНО: При создании новой задачи проверяем и очищаем зависшие флаги
        # Это предотвращает ситуацию, когда новая задача не может выполниться из-за старого флага
        if self.redis_service and self.redis_service.is_connected():
            try:
                task_running_key = f"parsing_task_running:{task.id}"
                existing_flag = await self.redis_service._client.get(task_running_key)
                if existing_flag:
                    logger.warning(f"⚠️ Задача {task.id}: Обнаружен зависший флаг выполнения, удаляем его")
                    await self.redis_service._client.delete(task_running_key)
                    logger.info(f"✅ Задача {task.id}: Зависший флаг удален, задача готова к выполнению")
            except Exception as e:
                logger.warning(f"⚠️ Задача {task.id}: Ошибка при проверке/очистке флага: {e}")
        
        # ВАЖНО: Добавляем задачу в очередь RabbitMQ сразу, даже если сервис не запущен
        # Это позволяет воркерам начать обработку немедленно
        if not self.rabbitmq_service:
            logger.error(f"❌ Задача {task.id}: RabbitMQ сервис не инициализирован, задача не может быть добавлена в очередь")
            raise RuntimeError("RabbitMQ должен быть доступен для добавления задач")
        
        # Пытаемся переподключиться, если соединение потеряно
        if not await self.rabbitmq_service.ensure_connected():
            logger.error(f"❌ Задача {task.id}: RabbitMQ недоступен, задача не может быть добавлена в очередь")
            raise RuntimeError("RabbitMQ должен быть доступен для добавления задач")
        
        try:
            task_data = {
                "type": "parsing_task",
                "task_id": task.id,
                "filters_json": task.filters_json,  # Уже dict (JSONB)
                "item_name": task.item_name,
                "appid": task.appid,
                "currency": task.currency
            }
            await self.rabbitmq_service.publish_task(task_data)
            logger.info(f"📤 Задача {task.id}: Немедленно добавлена в очередь RabbitMQ для обработки воркером")
            logger.info(f"   📋 Данные задачи: item_name='{task.item_name}', appid={task.appid}, currency={task.currency}")
        except Exception as e:
            logger.error(f"❌ Задача {task.id}: Не удалось добавить в очередь RabbitMQ: {e}")
            raise
        
        # Если сервис запущен, начинаем мониторинг (для периодических проверок)
        if self._running:
            logger.info(f"🚀 Задача {task.id}: Сервис запущен, начинаем мониторинг для периодических проверок")
            await self._start_task_monitoring(task)
        else:
            logger.info(f"ℹ️ Задача {task.id}: Сервис не запущен, но задача уже добавлена в очередь для немедленной обработки")
        
        return task
    
    async def update_monitoring_task(
        self,
        task_id: int,
        name: Optional[str] = None,
        filters: Optional[SearchFilters] = None,
        check_interval: Optional[int] = None,
        is_active: Optional[bool] = None
    ) -> Optional[MonitoringTask]:
        """
        Обновляет задачу мониторинга.
        
        Args:
            task_id: ID задачи
            name: Новое название
            filters: Новые фильтры
            check_interval: Новый интервал проверки
            is_active: Активна ли задача
            
        Returns:
            Обновленная задача или None
        """
        result = await self.db_session.execute(
            select(MonitoringTask).where(MonitoringTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        
        if not task:
            logger.error(f"Задача {task_id} не найдена")
            return None
        
        if name is not None:
            task.name = name
        if filters is not None:
            task.filters_json = filters.model_dump(exclude_none=True)
        if check_interval is not None:
            task.check_interval = check_interval
        if is_active is not None:
            task.is_active = is_active
        
        await self.db_session.commit()
        await self.db_session.refresh(task)
        
        logger.info(f"Обновлена задача мониторинга: {task_id}")
        
        # Перезапускаем мониторинг, если сервис запущен
        if self._running:
            await self._stop_task_monitoring(task_id)
            if task.is_active:
                await self._start_task_monitoring(task)
        
        return task
    
    async def delete_monitoring_task(self, task_id: int) -> bool:
        """Удаляет задачу мониторинга."""
        try:
            result = await self.db_session.execute(
                select(MonitoringTask).where(MonitoringTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            
            if not task:
                logger.warning(f"⚠️ MonitoringService: Задача {task_id} не найдена")
                return False
            
            await self._stop_task_monitoring(task_id)
            
            # ВАЖНО: Удаляем все связанные FoundItem перед удалением задачи
            # Это предотвращает ошибки при удалении задачи с связанными записями
            try:
                delete_result = await self.db_session.execute(
                    delete(FoundItem).where(FoundItem.task_id == task_id)
                )
                deleted_items_count = delete_result.rowcount
                if deleted_items_count > 0:
                    logger.info(f"🗑️ MonitoringService: Удалено {deleted_items_count} найденных предметов для задачи {task_id}")
            except Exception as e:
                logger.warning(f"⚠️ MonitoringService: Не удалось удалить найденные предметы для задачи {task_id}: {e}")
                # Продолжаем удаление задачи даже если не удалось удалить предметы
            
            # ВАЖНО: Очищаем флаг выполнения задачи в Redis перед удалением из БД
            # Это позволяет воркеру корректно обработать сообщения из очереди для удаленной задачи
            if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                try:
                    task_running_key = f"parsing_task_running:{task_id}"
                    await self.redis_service._client.delete(task_running_key)
                    logger.debug(f"🔓 MonitoringService: Удален флаг выполнения для задачи {task_id} из Redis")
                except Exception as e:
                    logger.warning(f"⚠️ MonitoringService: Не удалось удалить флаг выполнения для задачи {task_id}: {e}")
            
            await self.db_session.delete(task)
            await self.db_session.commit()
            
            logger.info(f"✅ MonitoringService: Удалена задача мониторинга: {task_id}")
            return True
        except Exception as e:
            logger.error(f"❌ MonitoringService: Ошибка при удалении задачи {task_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            try:
                await self.db_session.rollback()
            except Exception:
                pass
            raise  # Пробрасываем ошибку дальше для обработки в Telegram боте
    
    async def get_all_tasks(self, active_only: bool = False) -> List[MonitoringTask]:
        """
        Получает все задачи мониторинга.
        
        ВАЖНО: Использует отдельную сессию БД для предотвращения ошибок "connection is closed".
        """
        # ВАЖНО: Создаем отдельную сессию для этого запроса, чтобы избежать проблем с закрытыми соединениями
        # Если db_manager доступен, используем его, иначе используем общую сессию с блокировкой
        if self.db_manager:
            session = await self.db_manager.get_session()
            try:
                query = select(MonitoringTask)
                if active_only:
                    query = query.where(MonitoringTask.is_active == True)
                
                result = await session.execute(query.order_by(MonitoringTask.id))
                tasks = list(result.scalars().all())
                
                # ВАЖНО: Не делаем refresh после execute в той же транзакции
                # Это может вызвать ошибку "prepared state"
                # Данные уже актуальны из SELECT запроса
                # Если нужны обновленные данные, используем отдельный запрос
                
                return tasks
            finally:
                await session.close()
        else:
            # Fallback: используем общую сессию с блокировкой (менее надежно)
            async with self._session_lock:
                try:
                    query = select(MonitoringTask)
                    if active_only:
                        query = query.where(MonitoringTask.is_active == True)
                    
                    result = await self.db_session.execute(query.order_by(MonitoringTask.id))
                    tasks = list(result.scalars().all())
                    
                    # Обновляем объекты из БД
                    for task in tasks:
                        try:
                            await self.db_session.refresh(task, attribute_names=['total_checks', 'items_found', 'last_check', 'next_check', 'updated_at'])
                        except Exception as refresh_error:
                            logger.debug(f"⚠️ Не удалось обновить задачу {task.id} через refresh: {refresh_error}")
                    
                    return tasks
                except Exception as e:
                    error_msg = str(e)
                    if "connection is closed" in error_msg.lower() or "InterfaceError" in str(type(e).__name__):
                        logger.error(f"❌ MonitoringService: Соединение с БД закрыто при получении задач: {e}")
                        logger.error("   Это может произойти, если сессия была закрыта в другой корутине")
                        logger.error("   Рекомендуется передать db_manager в MonitoringService для создания отдельных сессий")
                    else:
                        logger.error(f"❌ MonitoringService: Ошибка при получении задач: {e}")
                    import traceback
                    logger.debug(f"Traceback: {traceback.format_exc()}")
                    return []
    
    async def _start_task_monitoring(self, task: MonitoringTask):
        """Запускает мониторинг для задачи."""
        if task.id in self._tasks:
            logger.warning(f"Мониторинг для задачи {task.id} уже запущен")
            return
        
        # При запуске мониторинга сбрасываем next_check, если он в прошлом или не установлен
        # Это гарантирует, что первая проверка выполнится сразу
        # Не коммитим здесь, чтобы избежать конфликтов при одновременном запуске нескольких задач
        now = datetime.now()
        if not task.next_check or task.next_check < now:
            if task.next_check:
                logger.info(f"🔄 Задача {task.id}: next_check в прошлом ({task.next_check.strftime('%Y-%m-%d %H:%M:%S')}), сбрасываем для немедленной проверки")
            else:
                logger.info(f"🆕 Задача {task.id}: next_check не установлен, первая проверка начнется сразу")
            task.next_check = None
            # Не коммитим здесь - задача будет обновлена в цикле мониторинга
        
        async def monitor_loop():
            """Цикл мониторинга для одной задачи."""
            # Сохраняем task_id в локальную переменную, чтобы избежать проблем с доступом к ORM атрибутам после rollback
            task_id = task.id
            task_name = task.name
            
            # ВАЖНО: Создаем отдельную сессию БД для этой корутины
            # Это предотвращает ошибки "concurrent operations are not permitted"
            task_session: Optional[AsyncSession] = None
            if self.db_manager:
                try:
                    task_session = await self.db_manager.get_session()
                    self._task_sessions[task_id] = task_session
                    logger.info(f"✅ Задача {task_id}: Создана отдельная сессия БД для мониторинга")
                except Exception as e:
                    logger.error(f"❌ Задача {task_id}: Не удалось создать сессию БД: {e}")
                    # Fallback на основную сессию
                    task_session = self.db_session
            else:
                # Fallback: используем основную сессию (старый режим)
                task_session = self.db_session
                logger.warning(f"⚠️ Задача {task_id}: Используется общая сессия БД (рекомендуется передать db_manager)")
            
            try:
                logger.info(f"🚀 Запущен мониторинг для задачи: {task_name} (ID: {task_id})")
                logger.info(f"   📋 Интервал проверки: {task.check_interval} сек")
                logger.info(f"   ✅ Задача активна: {task.is_active}")
                logger.info(f"   🔌 Redis доступен: {self.redis_service is not None and (self.redis_service.is_connected() if self.redis_service else False)}")
                if task.next_check:
                    logger.info(f"   ⏰ Следующая проверка: {task.next_check.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    logger.info(f"   ⏰ Первая проверка будет выполнена сразу")
                
                iteration = 0
                consecutive_errors = 0  # Счетчик последовательных ошибок
                MAX_CONSECUTIVE_ERRORS = 5  # Максимум ошибок подряд перед остановкой
                
                while self._running:
                    try:
                        # Периодически обновляем задачу из БД для проверки актуального статуса
                        if iteration % 6 == 0:  # Каждые 6 итераций (примерно минута)
                            try:
                                # Проверяем, существует ли задача в БД используя отдельную сессию
                                from sqlalchemy import select
                                result = await task_session.execute(
                                    select(MonitoringTask).where(MonitoringTask.id == task_id)
                                )
                                db_task = result.scalar_one_or_none()
                                
                                if not db_task:
                                    logger.info(f"🗑️ Задача {task_id}: Удалена из БД, останавливаем мониторинг")
                                    break
                                elif not db_task.is_active:
                                    logger.info(f"🛑 Задача {task_id}: Деактивирована, останавливаем мониторинг")
                                    break
                                else:
                                    # Обновляем объект в памяти
                                    task.is_active = db_task.is_active
                                    task.check_interval = db_task.check_interval
                                    task.next_check = db_task.next_check  # Синхронизируем next_check из БД
                                consecutive_errors = 0  # Сброс счетчика при успешной проверке
                            except Exception as e:
                                consecutive_errors += 1
                                logger.error(f"❌ Ошибка при проверке статуса задачи {task_id}: {e}")
                                import traceback
                                logger.debug(f"Traceback: {traceback.format_exc()}")
                                
                                # Если слишком много ошибок подряд - останавливаем мониторинг
                                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                    logger.error(f"❌ Задача {task_id}: Превышен лимит ошибок ({MAX_CONSECUTIVE_ERRORS}), останавливаем мониторинг")
                                    # Обновляем next_check перед остановкой, чтобы задача могла быть восстановлена
                                    try:
                                        await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                    except Exception:
                                        pass
                                    break
                                
                                # При ошибке обновляем next_check и продолжаем работу
                                try:
                                    await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                except Exception as update_error:
                                    logger.error(f"❌ Задача {task_id}: Не удалось обновить next_check после ошибки: {update_error}")
                                
                                # Ждем перед следующей попыткой
                                await asyncio.sleep(min(task.check_interval, 60))
                                continue
                        
                        iteration += 1
                        
                        # Проверяем, не пора ли проверять
                        now = datetime.now()
                        
                        # Если next_check установлен и еще не наступил - ждем
                        if task.next_check and now < task.next_check:
                            wait_time = (task.next_check - now).total_seconds()
                            if wait_time > 0:
                                logger.debug(f"⏳ Задача {task_id}: Ждем до следующей проверки ({wait_time:.1f} сек)")
                                await asyncio.sleep(min(wait_time, 60))  # Максимум 60 секунд
                                continue
                        
                        # Если next_check в прошлом или не установлен - выполняем проверку сразу
                        if task.next_check and now >= task.next_check:
                            logger.info(f"⏰ Задача {task_id}: Время проверки наступило (next_check был: {task.next_check.strftime('%Y-%m-%d %H:%M:%S')})")
                        elif not task.next_check:
                            logger.info(f"🆕 Задача {task_id}: Первая проверка (next_check не установлен)")
                        
                        logger.info(f"🔍 Задача {task_id}: Начинаем проверку (время: {now.strftime('%Y-%m-%d %H:%M:%S')})")
                        
                        # ВАЖНО: Проверяем, что задача еще существует и активна перед публикацией
                        # Используем отдельную сессию для этой проверки
                        try:
                            from sqlalchemy import select
                            result = await task_session.execute(
                                select(MonitoringTask).where(MonitoringTask.id == task_id)
                            )
                            db_task = result.scalar_one_or_none()
                            
                            if not db_task:
                                logger.info(f"🗑️ Задача {task_id}: Удалена из БД, останавливаем мониторинг")
                                break
                            elif not db_task.is_active:
                                logger.info(f"🛑 Задача {task_id}: Деактивирована, останавливаем мониторинг")
                                break
                            else:
                                # Обновляем объект в памяти
                                task.is_active = db_task.is_active
                                task.check_interval = db_task.check_interval
                                task.next_check = db_task.next_check  # Синхронизируем next_check из БД
                        except Exception as e:
                            consecutive_errors += 1
                            logger.error(f"❌ Ошибка при проверке статуса задачи {task_id} перед публикацией: {e}")
                            import traceback
                            logger.debug(f"Traceback: {traceback.format_exc()}")
                            
                            # Если слишком много ошибок подряд - останавливаем мониторинг
                            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                                logger.error(f"❌ Задача {task_id}: Превышен лимит ошибок ({MAX_CONSECUTIVE_ERRORS}), останавливаем мониторинг")
                                try:
                                    await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                except Exception:
                                    pass
                                break
                            
                            # При ошибке обновляем next_check и пропускаем итерацию
                            try:
                                await self._update_next_check_safe(task_id, task_session, task.check_interval)
                            except Exception as update_error:
                                logger.error(f"❌ Задача {task_id}: Не удалось обновить next_check после ошибки: {update_error}")
                            
                            await asyncio.sleep(min(task.check_interval, 60))
                            continue
                        
                        # Публикуем задачу в RabbitMQ для Parsing Worker
                        # ВАЖНО: Redis используется только для флагов выполнения (parsing_task_running),
                        # а задачи публикуются в RabbitMQ
                        # ВАЖНО: Сначала проверяем, есть ли сервис, затем пытаемся переподключиться
                        if not self.rabbitmq_service:
                            logger.error(f"❌ Задача {task_id}: RabbitMQ сервис не инициализирован, пропускаем эту проверку")
                            await self._update_next_check_safe(task_id, task_session, task.check_interval)
                            await asyncio.sleep(task.check_interval)
                            continue
                        
                        # Пытаемся переподключиться, если соединение потеряно
                        # ВАЖНО: ensure_connected() пытается переподключиться автоматически
                        if not await self.rabbitmq_service.ensure_connected():
                            logger.warning(f"⚠️ Задача {task_id}: RabbitMQ недоступен, пропускаем эту проверку (будет повторная попытка при следующей проверке)")
                            await self._update_next_check_safe(task_id, task_session, task.check_interval)
                            await asyncio.sleep(task.check_interval)
                            continue
                        
                        try:
                            # ВАЖНО: Проверяем, не выполняется ли уже парсинг для этой задачи (через Redis флаги)
                            task_running_key = f"parsing_task_running:{task_id}"
                            is_running = None
                            task_start_time = None
                            try:
                                if self.redis_service and self.redis_service.is_connected() and self.redis_service._client:
                                    flag_value = await self.redis_service._client.get(task_running_key)
                                    # Проверяем TTL флага - если TTL=-2, флаг не существует или некорректен
                                    if flag_value:
                                        ttl_check = await self.redis_service._client.ttl(task_running_key)
                                        # Если TTL=-2, флаг некорректен - удаляем его сразу
                                        if ttl_check == -2:
                                            logger.warning(f"⚠️ Задача {task_id}: Флаг существует, но TTL=-2 (некорректно). Удаляем флаг.")
                                            await self.redis_service._client.delete(task_running_key)
                                            is_running = False
                                            flag_value = None  # Сбрасываем flag_value, чтобы не обрабатывать его дальше
                                            logger.info(f"✅ Задача {task_id}: Флаг удален, is_running=False, задача будет опубликована")
                                        else:
                                            # Флаг считается существующим только если TTL > 0 или TTL = -1 (без TTL)
                                            is_running = ttl_check > 0 or ttl_check == -1
                                    else:
                                        is_running = False
                                    
                                    # Пытаемся извлечь время начала выполнения из значения флага
                                    if flag_value and is_running:
                                        try:
                                            # Значение флага содержит ISO timestamp времени начала выполнения
                                            task_start_time = datetime.fromisoformat(flag_value.decode('utf-8') if isinstance(flag_value, bytes) else flag_value)
                                        except (ValueError, AttributeError):
                                            # Если не удалось распарсить timestamp, используем TTL для оценки
                                            ttl = await self.redis_service._client.ttl(task_running_key)
                                            if ttl > 0:
                                                # Флаг устанавливается с TTL=3600 (60 минут)
                                                elapsed_seconds = 3600 - ttl
                                                task_start_time = now - timedelta(seconds=elapsed_seconds)
                            except Exception as e:
                                logger.debug(f"⚠️ Задача {task_id}: Ошибка при проверке флага выполнения: {e}")
                                
                                if is_running:
                                    # Проверяем, не зависла ли задача (выполняется слишком долго)
                                    STUCK_TASK_TIMEOUT = 10 * 60  # 10 минут - максимальное время выполнения задачи
                                    
                                    if task_start_time:
                                        elapsed_time = (now - task_start_time).total_seconds()
                                        if elapsed_time > STUCK_TASK_TIMEOUT:
                                            logger.warning(f"⚠️ Задача {task_id}: Обнаружена ЗАВИСШАЯ задача!")
                                            logger.warning(f"   ⏱️ Время выполнения: {elapsed_time/60:.1f} минут (превышен лимит {STUCK_TASK_TIMEOUT/60:.0f} минут)")
                                            logger.warning(f"   🔄 Удаляем зависший флаг и перезапускаем задачу...")
                                            
                                            try:
                                                # Удаляем зависший флаг
                                                if self.redis_service._client:
                                                    deleted = await self.redis_service._client.delete(task_running_key)
                                                    if deleted:
                                                        logger.info(f"✅ Задача {task_id}: Зависший флаг удален, задача будет перезапущена")
                                                    else:
                                                        logger.warning(f"⚠️ Задача {task_id}: Не удалось удалить зависший флаг (возможно, уже удален)")
                                                    # Устанавливаем is_running = False, чтобы задача могла быть опубликована
                                                    is_running = False
                                            except Exception as delete_error:
                                                logger.error(f"❌ Задача {task_id}: Ошибка при удалении зависшего флага: {delete_error}")
                                            
                                            # Продолжаем выполнение - задача будет опубликована в очередь
                                        else:
                                            logger.warning(f"⏸️ Задача {task_id}: Парсинг уже выполняется ({elapsed_time/60:.1f} минут), пропускаем эту проверку")
                                            # Обновляем время следующей проверки, но не публикуем задачу
                                            await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                            # Ждем до следующей проверки
                                            logger.debug(f"💤 Задача {task_id}: Ожидание {task.check_interval} сек до следующей проверки")
                                            await asyncio.sleep(task.check_interval)
                                            continue
                                else:
                                    # Не удалось определить время начала, но флаг существует
                                    # Проверяем TTL флага для оценки времени выполнения
                                    try:
                                        if self.redis_service._client:
                                            ttl = await self.redis_service._client.ttl(task_running_key)
                                            if ttl > 0:
                                                # Флаг устанавливается с TTL=3600 (60 минут)
                                                # Если TTL < 3400 (меньше 20 минут осталось), считаем задачу зависшей
                                                elapsed_seconds = 3600 - ttl
                                                if elapsed_seconds > STUCK_TASK_TIMEOUT:
                                                    logger.warning(f"⚠️ Задача {task_id}: Обнаружена ЗАВИСШАЯ задача (TTL={ttl}с, прошло ~{elapsed_seconds/60:.1f} мин)!")
                                                    logger.warning(f"   🔄 Удаляем зависший флаг и перезапускаем задачу...")
                                                    deleted = await self.redis_service._client.delete(task_running_key)
                                                    if deleted:
                                                        logger.info(f"✅ Задача {task_id}: Зависший флаг удален, задача будет перезапущена")
                                                    else:
                                                        logger.warning(f"⚠️ Задача {task_id}: Не удалось удалить зависший флаг")
                                                    # Устанавливаем is_running = False, чтобы задача могла быть опубликована
                                                    is_running = False
                                                    # Продолжаем выполнение - задача будет опубликована в очередь
                                                else:
                                                    logger.warning(f"⏸️ Задача {task_id}: Парсинг уже выполняется (~{elapsed_seconds/60:.1f} минут, TTL={ttl}с), пропускаем эту проверку")
                                                    # Обновляем время следующей проверки, но не публикуем задачу
                                                    await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                                    # Ждем до следующей проверки
                                                    logger.debug(f"💤 Задача {task_id}: Ожидание {task.check_interval} сек до следующей проверки")
                                                    await asyncio.sleep(task.check_interval)
                                                    continue
                                            # TTL = -1 (без TTL) или -2 (ключ не существует) - уже обработано выше
                                            # Этот блок больше не нужен, так как TTL=-2 обрабатывается на строке 417
                                    except Exception as ttl_error:
                                        logger.error(f"❌ Задача {task_id}: Ошибка при проверке TTL флага: {ttl_error}")
                                        # В случае ошибки, пропускаем задачу
                                        logger.warning(f"⏸️ Задача {task_id}: Парсинг уже выполняется (время начала неизвестно, ошибка проверки TTL), пропускаем эту проверку")
                                        # Обновляем время следующей проверки, но не публикуем задачу
                                        await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                        # Ждем до следующей проверки
                                        logger.debug(f"💤 Задача {task_id}: Ожидание {task.check_interval} сек до следующей проверки")
                                        await asyncio.sleep(task.check_interval)
                                        continue
                                
                                # Публикуем задачу только если она не выполняется
                                if not is_running:
                                    logger.debug(f"📋 Задача {task_id}: is_running=False, публикуем задачу в очередь")
                                    task_data = {
                                        "type": "parsing_task",
                                        "task_id": task_id,
                                        "filters_json": task.filters_json,  # Уже dict (JSONB)
                                        "item_name": task.item_name,
                                        "appid": task.appid,
                                        "currency": task.currency
                                    }
                                    
                                    # Публикуем задачу в RabbitMQ
                                    if not self.rabbitmq_service:
                                        logger.error(f"❌ Задача {task_id}: RabbitMQ сервис не инициализирован, задача не может быть добавлена в очередь")
                                        await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                        await asyncio.sleep(task.check_interval)
                                        continue

                                    # Пытаемся переподключиться, если соединение потеряно
                                    # ВАЖНО: ensure_connected() пытается переподключиться автоматически
                                    if not await self.rabbitmq_service.ensure_connected():
                                        logger.warning(f"⚠️ Задача {task_id}: RabbitMQ недоступен, задача не может быть добавлена в очередь (будет повторная попытка при следующей проверке)")
                                        # Пропускаем эту итерацию, попробуем в следующий раз
                                        await self._update_next_check_safe(task_id, task_session, task.check_interval)
                                        await asyncio.sleep(task.check_interval)
                                        continue
                                        continue
                                    
                                    logger.info(f"📤 Задача {task_id}: Добавляем задачу в RabbitMQ очередь 'parsing_tasks'")
                                    logger.debug(f"   Данные задачи: task_id={task_id}, item_name={task.item_name}, appid={task.appid}")
                                    await self.rabbitmq_service.publish_task(task_data)
                                    logger.info(f"✅ Задача {task_id}: Успешно добавлена в очередь RabbitMQ")
                                    
                                    # ВАЖНО: НЕ обновляем next_check сразу - пусть обновится только после завершения обработки
                                    # или при следующей проверке (если парсинг еще выполняется)
                                    # Это предотвращает планирование новой проверки, пока текущая еще не завершена
                                    logger.debug(f"⏳ Задача {task_id}: Задача добавлена в очередь, next_check будет обновлен после завершения обработки")
                        except Exception as e:
                            logger.error(f"❌ Задача {task_id}: Ошибка публикации в RabbitMQ: {e}")
                            import traceback
                            logger.debug(f"Traceback: {traceback.format_exc()}")
                            # Fallback: выполняем проверку напрямую
                            logger.info(f"🔄 Задача {task_id}: Выполняем проверку напрямую (fallback)")
                            await self._check_task(task, task_session)
                            # При fallback обновляем next_check после завершения проверки
                            await self._update_next_check_safe(task_id, task_session, task.check_interval)
                        
                        # Ждем до следующей проверки (внутри основного try, вне вложенного try-except)
                        logger.debug(f"💤 Задача {task_id}: Ожидание {task.check_interval} сек до следующей проверки")
                        await asyncio.sleep(task.check_interval)
                    
                    except asyncio.CancelledError:
                        logger.info(f"Мониторинг задачи {task_id} остановлен")
                        break
                    except Exception as e:
                        consecutive_errors += 1
                        # Используем сохраненный task_id вместо task.id, чтобы избежать проблем с ORM после rollback
                        logger.error(f"Ошибка в мониторинге задачи {task_id}: {e}")
                        import traceback
                        logger.debug(f"Traceback: {traceback.format_exc()}")
                        
                        # Пытаемся откатить транзакцию, если она в плохом состоянии
                        try:
                            await task_session.rollback()
                        except Exception:
                            pass
                        
                        # Если слишком много ошибок подряд - останавливаем мониторинг
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            logger.error(f"❌ Задача {task_id}: Превышен лимит ошибок ({MAX_CONSECUTIVE_ERRORS}), останавливаем мониторинг")
                            try:
                                await self._update_next_check_safe(task_id, task_session, task.check_interval)
                            except Exception:
                                pass
                            break
                        
                        # Обновляем next_check и ждем перед повтором
                        try:
                            await self._update_next_check_safe(task_id, task_session, task.check_interval)
                        except Exception:
                            pass
                        await asyncio.sleep(60)  # Ждем перед повтором
            finally:
                # Закрываем сессию задачи при выходе из цикла
                if task_session and task_session != self.db_session:
                    try:
                        await task_session.close()
                        logger.info(f"✅ Задача {task_id}: Сессия БД закрыта")
                    except Exception as e:
                        logger.warning(f"⚠️ Задача {task_id}: Ошибка при закрытии сессии: {e}")
                    finally:
                        # Удаляем сессию из словаря
                        self._task_sessions.pop(task_id, None)
                
                # Если мониторинг остановился из-за ошибки, запускаем восстановление
                if self._running and task_id not in self._recovery_tasks:
                    logger.warning(f"🔄 Задача {task_id}: Мониторинг остановился, запускаем восстановление...")
                    await self._start_task_recovery(task_id)
        
        self._tasks[task.id] = asyncio.create_task(monitor_loop())
    
    async def _update_next_check_safe(self, task_id: int, session: AsyncSession, check_interval: int):
        """
        Безопасно обновляет next_check для задачи.
        
        Args:
            task_id: ID задачи
            session: Сессия БД для использования
            check_interval: Интервал проверки в секундах
        """
        try:
            now = datetime.now()
            next_check = now + timedelta(seconds=check_interval)
            
            # Обновляем через UPDATE запрос, чтобы избежать проблем с ORM
            # ВАЖНО: Добавляем таймаут для предотвращения долгих блокировок
            # ВАЖНО: Уменьшен таймаут до 5 секунд для быстрого обнаружения блокировок
            try:
                logger.debug(f"🔄 MonitoringService: Обновляем next_check для задачи {task_id} через атомарный UPDATE")
                start_time = datetime.now()
                
                await asyncio.wait_for(
                    session.execute(
                        update(MonitoringTask)
                        .where(MonitoringTask.id == task_id)
                        .values(next_check=next_check)
                    ),
                    timeout=5.0  # Уменьшен таймаут до 5 секунд для быстрого обнаружения блокировок
                )
                
                update_duration = (datetime.now() - start_time).total_seconds()
                if update_duration > 1.0:
                    logger.warning(f"⚠️ Задача {task_id}: UPDATE next_check занял {update_duration:.2f}с (медленно, возможна блокировка)")
                
                commit_start = datetime.now()
                await asyncio.wait_for(
                    session.commit(),
                    timeout=3.0  # Уменьшен таймаут до 3 секунд для commit
                )
                
                commit_duration = (datetime.now() - commit_start).total_seconds()
                if commit_duration > 1.0:
                    logger.warning(f"⚠️ Задача {task_id}: COMMIT next_check занял {commit_duration:.2f}с (медленно, возможна блокировка)")
                
                logger.info(f"⏰ Задача {task_id}: Следующая проверка в {next_check.strftime('%Y-%m-%d %H:%M:%S')}")
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Задача {task_id}: Таймаут при обновлении next_check (5с), возможна блокировка БД")
                logger.error(f"   Это может означать, что другой процесс (parsing-worker или другой monitoring-service) обновляет эту задачу одновременно")
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise  # Пробрасываем исключение для обработки выше
        except Exception as e:
            logger.error(f"❌ Задача {task_id}: Ошибка при обновлении next_check: {e}")
            try:
                await session.rollback()
            except Exception:
                pass
    
    async def _start_task_recovery(self, task_id: int):
        """
        Запускает механизм восстановления для остановившейся задачи.
        
        Args:
            task_id: ID задачи для восстановления
        """
        if task_id in self._recovery_tasks:
            logger.debug(f"🔄 Задача {task_id}: Восстановление уже запущено")
            return
        
        async def recovery_loop():
            """Цикл восстановления задачи."""
            recovery_delay = 60  # Начальная задержка перед восстановлением (секунды)
            max_delay = 600  # Максимальная задержка (10 минут)
            max_attempts = 10  # Максимум попыток восстановления
            
            attempt = 0
            while self._running and attempt < max_attempts:
                try:
                    await asyncio.sleep(recovery_delay)
                    attempt += 1
                    
                    # Проверяем, что задача все еще активна
                    session = None
                    try:
                        if self.db_manager:
                            session = await self.db_manager.get_session()
                        else:
                            session = self.db_session
                        
                        result = await session.execute(
                            select(MonitoringTask).where(MonitoringTask.id == task_id)
                        )
                        task = result.scalar_one_or_none()
                        
                        if not task:
                            logger.info(f"🔄 Задача {task_id}: Задача удалена, прекращаем восстановление")
                            break
                        
                        if not task.is_active:
                            logger.info(f"🔄 Задача {task_id}: Задача деактивирована, прекращаем восстановление")
                            break
                        
                        # Проверяем, не запущен ли уже мониторинг
                        if task_id in self._tasks:
                            task_obj = self._tasks[task_id]
                            if not task_obj.done():
                                logger.info(f"🔄 Задача {task_id}: Мониторинг уже запущен, прекращаем восстановление")
                                break
                            else:
                                # Задача завершилась, удаляем её
                                del self._tasks[task_id]
                        
                        logger.info(f"🔄 Задача {task_id}: Попытка восстановления #{attempt}/{max_attempts}")
                        
                        # Перезапускаем мониторинг
                        await self._start_task_monitoring(task)
                        logger.info(f"✅ Задача {task_id}: Мониторинг успешно восстановлен")
                        break
                        
                    except Exception as e:
                        logger.error(f"❌ Задача {task_id}: Ошибка при восстановлении (попытка {attempt}): {e}")
                        # Увеличиваем задержку экспоненциально
                        recovery_delay = min(recovery_delay * 2, max_delay)
                    finally:
                        if session and session != self.db_session:
                            try:
                                await session.close()
                            except Exception:
                                pass
                        
                except asyncio.CancelledError:
                    logger.info(f"🔄 Задача {task_id}: Восстановление отменено")
                    break
                except Exception as e:
                    logger.error(f"❌ Задача {task_id}: Критическая ошибка в цикле восстановления: {e}")
                    recovery_delay = min(recovery_delay * 2, max_delay)
            
            # Удаляем задачу восстановления из словаря
            self._recovery_tasks.pop(task_id, None)
            if attempt >= max_attempts:
                logger.error(f"❌ Задача {task_id}: Превышен лимит попыток восстановления ({max_attempts})")
        
        self._recovery_tasks[task_id] = asyncio.create_task(recovery_loop())
        logger.info(f"🔄 Задача {task_id}: Запущено восстановление")
    
    async def _stop_task_monitoring(self, task_id: int):
        """Останавливает мониторинг для задачи."""
        if task_id in self._tasks:
            self._tasks[task_id].cancel()
            try:
                await self._tasks[task_id]
            except asyncio.CancelledError:
                pass
            del self._tasks[task_id]
            logger.info(f"Остановлен мониторинг для задачи {task_id}")
        
        # Останавливаем восстановление, если оно запущено
        if task_id in self._recovery_tasks:
            self._recovery_tasks[task_id].cancel()
            try:
                await self._recovery_tasks[task_id]
            except asyncio.CancelledError:
                pass
            del self._recovery_tasks[task_id]
        
        # Закрываем сессию задачи, если она существует
        if task_id in self._task_sessions:
            session = self._task_sessions[task_id]
            if session != self.db_session:
                try:
                    await session.close()
                except Exception:
                    pass
            del self._task_sessions[task_id]
    
    async def _check_task(self, task: MonitoringTask, session: Optional[AsyncSession] = None):
        """
        Выполняет одну проверку для задачи.
        
        Args:
            task: Задача мониторинга
            session: Сессия БД для использования (если None, используется self.db_session)
        """
        if session is None:
            session = self.db_session
        
        logger.debug(f"Проверка задачи: {task.name} (ID: {task.id})")
        
        try:
            # Загружаем фильтры
            # ВАЖНО: filters_json может быть строкой JSON или словарем (JSONB)
            filters_json = task.filters_json
            if isinstance(filters_json, str):
                import json
                filters_json = json.loads(filters_json)
            filters = SearchFilters.model_validate(filters_json)
            filters.item_name = task.item_name
            filters.appid = task.appid
            filters.currency = task.currency
            
            # Используем сервис парсинга (он сам управляет прокси)
            logger.info(f"🔍 MonitoringService: Начинаем проверку задачи '{task.name}' (ID: {task.id})")
            logger.info(f"   Предмет: {filters.item_name}")
            logger.info(f"   Интервал проверки: {task.check_interval} сек")
            
            result = await self.parsing_service.parse_items(filters, start=0, count=10)
            
            logger.info(
                f"📊 MonitoringService: Результат поиска для '{filters.item_name}': "
                f"success={result.get('success')}, "
                f"total={result.get('total_count', 0)}, "
                f"filtered={result.get('filtered_count', 0)}, "
                f"items={len(result.get('items', []))}"
            )
            
            if result.get('success') and result.get('items'):
                # Найдены предметы
                logger.info(f"💾 MonitoringService: Начинаем сохранение {len(result['items'])} найденных предметов")
                found_count = 0
                for idx, item in enumerate(result['items'], 1):
                    item_name = item.get('name', item.get('asset_description', {}).get('market_hash_name', 'Unknown'))
                    logger.info(f"   [{idx}/{len(result['items'])}] Сохраняем предмет: {item_name}")
                    saved = await self._save_found_item(task, item)
                    if saved:
                        found_count += 1
                        logger.info(f"      ✅ Предмет сохранен в БД")
                    else:
                        logger.info(f"      ⚠️ Предмет уже существует (дубликат)")
                
                task.items_found += found_count
                await session.commit()
                logger.info(f"✅ MonitoringService: Найдено и сохранено {found_count} предметов для задачи '{task.name}' (всего найдено: {task.items_found})")
                
                # Отправляем уведомления (только для новых предметов, которые еще не отправлялись)
                if found_count > 0:
                    # Получаем только те предметы, которые еще не отправлялись
                    from sqlalchemy import select
                    found_items_result = await session.execute(
                        select(FoundItem)
                        .where(
                            (FoundItem.task_id == task.id) &
                            (FoundItem.notification_sent == False)
                        )
                        .order_by(FoundItem.found_at.desc())
                        .limit(found_count)
                    )
                    found_items = found_items_result.scalars().all()
                    
                    # Используем Redis для асинхронных уведомлений, если доступен
                    if self.redis_service:
                        for found_item in found_items:
                            try:
                                # Публикуем в Redis канал для асинхронной обработки
                                await self.redis_service.publish("found_items", {
                                    "type": "found_item",
                                    "item_id": found_item.id,
                                    "task_id": task.id,
                                    "item_name": found_item.item_name,
                                    "price": found_item.price,
                                    "market_url": found_item.market_url,
                                    "item_data_json": found_item.item_data_json,
                                    "task_name": task.name
                                })
                                logger.debug(f"📤 Опубликовано уведомление в Redis для предмета {found_item.id}")
                            except Exception as e:
                                logger.error(f"Ошибка публикации в RabbitMQ: {e}")
                                # Fallback на прямой callback
                                if self.notification_callback:
                                    try:
                                        await self.notification_callback(found_item, task)
                                        found_item.notification_sent = True
                                        found_item.notification_sent_at = datetime.now()
                                        await session.commit()
                                    except Exception as e2:
                                        logger.error(f"Ошибка отправки уведомления через callback: {e2}")
                    elif self.notification_callback:
                        # Используем прямой callback, если Redis не доступен
                        for found_item in found_items:
                            try:
                                await self.notification_callback(found_item, task)
                                # Отмечаем как отправленное сразу после успешной отправки
                                found_item.notification_sent = True
                                found_item.notification_sent_at = datetime.now()
                                await session.commit()
                            except Exception as e:
                                logger.error(f"Ошибка отправки уведомления: {e}")
            else:
                if not result.get('success'):
                    logger.warning(f"⚠️ Поиск неуспешен для '{filters.item_name}': {result.get('error', 'Unknown error')}")
                else:
                    logger.debug(f"ℹ️ Предметы не найдены для задачи '{task.name}' (после фильтрации)")
            
            task.total_checks += 1
            task.last_check = datetime.now()
            await session.commit()
                
        except Exception as e:
            logger.error(f"Ошибка при проверке задачи {task.id}: {e}")
            # Ошибка уже обработана в parsing_service
    
    async def _save_found_item(self, task: MonitoringTask, item: Dict[str, Any]) -> bool:
        """
        Сохраняет найденный предмет в БД.
        
        Returns:
            True если предмет был сохранен, False если уже существует
        """
        # Проверяем, не был ли уже сохранен этот предмет
        price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
        try:
            price = float(price_text)
        except (ValueError, AttributeError):
            price = 0.0
        
        # Получаем данные предмета
        parsed_data = item.get('parsed_data', {})
        item_name = item.get('name', task.item_name)
        
        # Используем сессию задачи, если доступна, иначе основную
        session = self._task_sessions.get(task.id, self.db_session)
        
        # Проверяем дубликаты (по названию и цене)
        from sqlalchemy import select
        existing = await session.execute(
            select(FoundItem).where(
                FoundItem.task_id == task.id,
                FoundItem.item_name == item_name,
                FoundItem.price == price
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            logger.debug(f"Предмет уже сохранен: {item_name} (${price:.2f})")
            return False
        
        # Сохраняем в БД
        import json
        item_data = parsed_data if parsed_data else {}
        found_item = FoundItem(
            task_id=task.id,
            item_name=item_name,
            price=price,
            item_data_json=json.dumps(item_data, ensure_ascii=False),
            market_url=item.get('asset_description', {}).get('market_hash_name'),
            notification_sent=False
        )
        
        session.add(found_item)
        await session.commit()
        await session.refresh(found_item)
        
        logger.info(f"💾 Сохранен найденный предмет: {found_item.item_name} (${found_item.price:.2f})")
        return True
    
    async def start(self):
        """Запускает сервис мониторинга."""
        if self._running:
            logger.warning("⚠️ Сервис мониторинга уже запущен")
            return
        
        self._running = True
        logger.info("🚀 Запуск сервиса мониторинга")
        logger.info(f"   🔌 Redis доступен: {self.redis_service is not None and (self.redis_service.is_connected() if self.redis_service else False)}")
        
        # Загружаем все активные задачи
        tasks = await self.get_all_tasks(active_only=True)
        logger.info(f"   📋 Найдено активных задач: {len(tasks)}")
        
        for task in tasks:
            logger.info(f"   ▶️ Запускаем мониторинг задачи #{task.id}: {task.name}")
            await self._start_task_monitoring(task)
        
        logger.info(f"✅ Сервис мониторинга запущен, активных задач: {len(tasks)}")
    
    async def stop(self):
        """Останавливает сервис мониторинга."""
        if not self._running:
            return
        
        self._running = False
        logger.info("Остановка сервиса мониторинга")
        
        # Останавливаем все задачи
        for task_id in list(self._tasks.keys()):
            await self._stop_task_monitoring(task_id)
        
        # Останавливаем все задачи восстановления
        for task_id in list(self._recovery_tasks.keys()):
            self._recovery_tasks[task_id].cancel()
            try:
                await self._recovery_tasks[task_id]
            except asyncio.CancelledError:
                pass
            del self._recovery_tasks[task_id]
        
        # Закрываем все сессии задач
        for task_id, session in list(self._task_sessions.items()):
            if session != self.db_session:
                try:
                    await session.close()
                except Exception:
                    pass
            del self._task_sessions[task_id]
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Получает статистику мониторинга."""
        tasks = await self.get_all_tasks()
        
        return {
            "total_tasks": len(tasks),
            "active_tasks": len([t for t in tasks if t.is_active]),
            "running_tasks": len(self._tasks),
            "tasks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "item_name": t.item_name,
                    "is_active": t.is_active,
                    "total_checks": t.total_checks,
                    "items_found": t.items_found,
                    "last_check": t.last_check.isoformat() if t.last_check else None,
                    "next_check": t.next_check.isoformat() if t.next_check else None
                }
                for t in tasks
            ]
        }

