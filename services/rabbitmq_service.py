"""
Сервис для работы с RabbitMQ (очереди задач парсинга).
Обеспечивает гарантии доставки, retry механизм и обработку зависших задач.
"""
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from loguru import logger

try:
    import aio_pika
    from aio_pika import Message, DeliveryMode, ExchangeType
    from aio_pika.abc import AbstractConnection, AbstractChannel, AbstractQueue, AbstractExchange
except ImportError:
    aio_pika = None
    logger.warning("aio-pika не установлен. Установите: pip install aio-pika")


class RabbitMQService:
    """Сервис для работы с RabbitMQ."""
    
    # Имена очередей и exchange
    PARSING_QUEUE = "parsing_tasks"
    PARSING_DLQ = "parsing_tasks_dlq"  # Dead Letter Queue
    PARSING_RETRY_EXCHANGE = "parsing_retry_exchange"  # Для отложенных сообщений
    PARSING_MAIN_EXCHANGE = "parsing_main_exchange"
    
    # Максимальное количество попыток retry
    MAX_RETRY_ATTEMPTS = 5
    
    def __init__(self, rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"):
        """
        Инициализация RabbitMQ сервиса.
        
        Args:
            rabbitmq_url: URL подключения к RabbitMQ (по умолчанию localhost:5672)
        """
        if aio_pika is None:
            raise ImportError("aio-pika не установлен. Установите: pip install aio-pika")
        
        self.rabbitmq_url = rabbitmq_url
        self._connection: Optional[AbstractConnection] = None
        self._channel: Optional[AbstractChannel] = None
        self._parsing_queue: Optional[AbstractQueue] = None
        self._dlq: Optional[AbstractQueue] = None
        self._retry_exchange: Optional[AbstractExchange] = None
        self._main_exchange: Optional[AbstractExchange] = None
        self._is_connected = False
        self._consumers: Dict[str, asyncio.Task] = {}
    
    async def connect(self):
        """Подключается к RabbitMQ и настраивает очереди и exchange."""
        if self._connection and not self._connection.is_closed:
            logger.info("✅ RabbitMQ уже подключен")
            return
        
        try:
            # Подключаемся к RabbitMQ
            self._connection = await aio_pika.connect_robust(self.rabbitmq_url)
            self._channel = await self._connection.channel()
            
            # Настраиваем QoS для ограничения количества неподтвержденных сообщений
            await self._channel.set_qos(prefetch_count=10)  # Максимум 10 неподтвержденных сообщений на воркер
            
            # Создаем main exchange для маршрутизации
            self._main_exchange = await self._channel.declare_exchange(
                self.PARSING_MAIN_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True
            )
            
            # Создаем retry exchange для отложенных сообщений (delayed messages)
            # Используем плагин rabbitmq-delayed-message-exchange или альтернативный подход
            # Для простоты используем TTL + Dead Letter Exchange
            self._retry_exchange = await self._channel.declare_exchange(
                self.PARSING_RETRY_EXCHANGE,
                ExchangeType.DIRECT,
                durable=True
            )
            
            # Создаем Dead Letter Queue для failed задач
            self._dlq = await self._channel.declare_queue(
                self.PARSING_DLQ,
                durable=True
            )
            await self._dlq.bind(self._main_exchange, routing_key="dlq")
            
            # Создаем основную очередь для задач парсинга
            # С настройками для retry и DLQ
            # ВАЖНО: x-consumer-timeout устанавливает таймаут для подтверждения сообщений
            # Если сообщение не подтверждено в течение этого времени, оно автоматически возвращается в очередь
            # Устанавливаем 15 минут (900000 мс) - чуть больше STUCK_TASK_TIMEOUT (10 минут)
            # Это позволяет monitoring_service обнаружить зависшую задачу и перезапустить её,
            # а затем RabbitMQ автоматически вернет старое сообщение в очередь
            self._parsing_queue = await self._channel.declare_queue(
                self.PARSING_QUEUE,
                durable=True,  # Сохранять сообщения при перезапуске
                arguments={
                    # Dead Letter Exchange - для перемещения failed задач
                    "x-dead-letter-exchange": self._main_exchange.name,
                    "x-dead-letter-routing-key": "dlq",
                    # Максимальное количество попыток (через x-max-retries header)
                    "x-max-retries": self.MAX_RETRY_ATTEMPTS,
                    # Consumer timeout - автоматически возвращает неподтвержденные сообщения через 15 минут
                    # Это защита от зависших задач на уровне RabbitMQ
                    "x-consumer-timeout": 15 * 60 * 1000,  # 15 минут в миллисекундах
                }
            )
            await self._parsing_queue.bind(self._main_exchange, routing_key="parsing")
            
            # Создаем retry очередь для отложенных сообщений
            retry_queue = await self._channel.declare_queue(
                f"{self.PARSING_QUEUE}_retry",
                durable=True,
                arguments={
                    # Dead Letter Exchange - возвращаем в основную очередь после TTL
                    "x-dead-letter-exchange": self._main_exchange.name,
                    "x-dead-letter-routing-key": "parsing",
                    # TTL по умолчанию (будет переопределяться в сообщениях)
                    "x-message-ttl": 60000,  # 60 секунд
                }
            )
            await retry_queue.bind(self._retry_exchange, routing_key="retry")
            
            self._is_connected = True
            logger.info(f"✅ Подключено к RabbitMQ: {self.rabbitmq_url}")
            logger.info(f"   📋 Очередь: {self.PARSING_QUEUE}")
            logger.info(f"   📋 DLQ: {self.PARSING_DLQ}")
            logger.info(f"   🔄 Retry Exchange: {self.PARSING_RETRY_EXCHANGE}")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к RabbitMQ: {e}")
            self._is_connected = False
            raise
    
    async def disconnect(self):
        """Отключается от RabbitMQ."""
        # Останавливаем всех потребителей
        for consumer_name, task in list(self._consumers.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._consumers.clear()
        
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
            self._channel = None
        
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            self._connection = None
            self._is_connected = False
            logger.info("❌ Отключено от RabbitMQ")
    
    def is_connected(self) -> bool:
        """Проверяет, подключен ли клиент к RabbitMQ."""
        return self._is_connected and self._connection is not None and not self._connection.is_closed
    
    async def publish_task(self, task_data: Dict[str, Any], priority: int = 0, delay_seconds: int = 0):
        """
        Публикует задачу в очередь RabbitMQ.
        
        Args:
            task_data: Словарь с данными задачи
            priority: Приоритет задачи (0-255, выше = важнее)
            delay_seconds: Задержка перед обработкой (секунды)
        """
        if not self.is_connected():
            await self.connect()
        
        try:
            # Сериализуем данные задачи
            message_body = json.dumps(task_data, ensure_ascii=False).encode('utf-8')
            
            # Добавляем метаданные для отслеживания retry
            headers = {
                "x-retry-count": 0,  # Счетчик попыток
                "x-task-id": task_data.get("task_id", "unknown"),
                "x-published-at": datetime.now().isoformat(),
            }
            
            # Создаем сообщение с persistent delivery mode
            # Если есть задержка, устанавливаем expiration в сообщении
            message = Message(
                message_body,
                delivery_mode=DeliveryMode.PERSISTENT,  # Сохранять при перезапуске
                priority=priority,
                headers=headers,
                expiration=delay_seconds * 1000 if delay_seconds > 0 else None,  # TTL в миллисекундах (только для задержки)
            )
            
            # Если есть задержка, публикуем в retry exchange
            if delay_seconds > 0:
                # Используем retry exchange для отложенных сообщений
                await self._retry_exchange.publish(
                    message,
                    routing_key="retry",
                )
                logger.debug(f"📤 Задача {task_data.get('task_id')} опубликована с задержкой {delay_seconds}с")
            else:
                # Публикуем в основную очередь
                await self._main_exchange.publish(
                    message,
                    routing_key="parsing",
                )
                logger.info(f"📤 Задача {task_data.get('task_id')} опубликована в очередь RabbitMQ")
        except Exception as e:
            logger.error(f"❌ Ошибка при публикации задачи в RabbitMQ: {e}")
            raise
    
    async def consume_tasks(
        self,
        callback: Callable[[Dict[str, Any], Any], None],
        consumer_name: str = "worker-1"
    ):
        """
        Начинает потребление задач из очереди.
        
        Args:
            callback: Функция для обработки задач (async или sync)
                     Принимает (task_data, message)
            consumer_name: Имя потребителя (для логирования)
        """
        if not self.is_connected():
            await self.connect()
        
        if consumer_name in self._consumers:
            logger.warning(f"⚠️ Потребитель '{consumer_name}' уже запущен")
            return
        
        async def _consume_loop():
            """Цикл потребления сообщений."""
            try:
                async with self._parsing_queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        try:
                            # Парсим данные задачи
                            task_data = json.loads(message.body.decode('utf-8'))
                            task_id = task_data.get('task_id', 'unknown')
                            
                            logger.debug(f"📥 Получена задача {task_id} из RabbitMQ")
                            
                            # Вызываем callback для обработки
                            # ВАЖНО: callback должен сам подтвердить сообщение через message.ack()
                            # или пробросить исключение для retry механизма
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(task_data, message)
                                else:
                                    callback(task_data, message)
                                
                                # Сообщение должно быть подтверждено в callback
                                # Если callback не подтвердил сообщение, оно будет обработано механизмом retry
                                logger.debug(f"✅ Задача {task_id} обработана (подтверждение в callback)")
                            except Exception as callback_error:
                                # Ошибка при обработке - обрабатываем retry
                                logger.error(f"❌ Ошибка при обработке задачи {task_id}: {callback_error}")
                                await self._handle_task_error(message, task_data, callback_error)
                                
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Ошибка декодирования JSON из RabbitMQ: {e}")
                            # Некорректное сообщение - отправляем в DLQ
                            await message.nack(requeue=False)
                        except Exception as e:
                            logger.error(f"❌ Ошибка при получении сообщения из RabbitMQ: {e}")
                            # Неизвестная ошибка - отправляем в DLQ
                            await message.nack(requeue=False)
            except asyncio.CancelledError:
                logger.info(f"🛑 Потребитель '{consumer_name}' остановлен")
            except Exception as e:
                logger.error(f"❌ Критическая ошибка в цикле потребления '{consumer_name}': {e}")
        
        # Запускаем потребителя в фоне
        task = asyncio.create_task(_consume_loop())
        self._consumers[consumer_name] = task
        logger.info(f"📥 Потребитель '{consumer_name}' запущен для очереди '{self.PARSING_QUEUE}'")
    
    async def _handle_task_error(
        self,
        message: Message,
        task_data: Dict[str, Any],
        error: Exception
    ):
        """
        Обрабатывает ошибку при выполнении задачи (retry механизм).
        
        Args:
            message: Сообщение RabbitMQ
            task_data: Данные задачи
            error: Ошибка, которая произошла
        """
        # Получаем текущий счетчик retry
        headers = message.headers or {}
        retry_count = headers.get("x-retry-count", 0)
        task_id = task_data.get("task_id", "unknown")
        
        if retry_count >= self.MAX_RETRY_ATTEMPTS:
            # Превышен лимит попыток - отправляем в DLQ
            logger.error(
                f"❌ Задача {task_id}: Превышен лимит попыток ({self.MAX_RETRY_ATTEMPTS}), "
                f"отправляем в DLQ"
            )
            await message.nack(requeue=False)  # Отправляется в DLQ через x-dead-letter-exchange
        else:
            # Увеличиваем счетчик и повторяем с экспоненциальной задержкой
            retry_count += 1
            delay_seconds = min(60 * (2 ** retry_count), 600)  # Экспоненциальная задержка: 60с, 120с, 240с, 480с, 600с (макс)
            
            logger.warning(
                f"⚠️ Задача {task_id}: Ошибка при обработке (попытка {retry_count}/{self.MAX_RETRY_ATTEMPTS}), "
                f"повтор через {delay_seconds}с"
            )
            
            # Обновляем headers и публикуем в retry exchange с задержкой
            new_headers = {**headers, "x-retry-count": retry_count}
            new_message = Message(
                message.body,
                delivery_mode=DeliveryMode.PERSISTENT,
                headers=new_headers,
                expiration=delay_seconds * 1000,  # TTL в миллисекундах
            )
            
            # Публикуем в retry exchange с TTL
            await self._retry_exchange.publish(
                new_message,
                routing_key="retry",
            )
            
            # Подтверждаем оригинальное сообщение (оно уже обработано через retry)
            await message.ack()
    
    async def stop_consumer(self, consumer_name: str):
        """Останавливает потребителя."""
        if consumer_name in self._consumers:
            self._consumers[consumer_name].cancel()
            try:
                await self._consumers[consumer_name]
            except asyncio.CancelledError:
                pass
            del self._consumers[consumer_name]
            logger.info(f"🛑 Потребитель '{consumer_name}' остановлен")
    
    async def get_queue_info(self) -> Dict[str, Any]:
        """
        Получает информацию об очередях (количество сообщений и т.д.).
        
        Returns:
            Словарь с информацией об очередях
        """
        if not self.is_connected():
            return {"error": "Не подключено к RabbitMQ"}
        
        try:
            # Получаем информацию об очереди через RabbitMQ Management API или напрямую
            # Для простоты возвращаем базовую информацию
            return {
                "queue": self.PARSING_QUEUE,
                "dlq": self.PARSING_DLQ,
                "connected": self.is_connected(),
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при получении информации об очередях: {e}")
            return {"error": str(e)}
    
    async def requeue_task(self, task_data: Dict[str, Any], delay_seconds: int = 0):
        """
        Повторно публикует задачу в очередь (для повторного запуска после выполнения).
        
        Args:
            task_data: Данные задачи
            delay_seconds: Задержка перед повторным запуском (секунды)
        """
        await self.publish_task(task_data, delay_seconds=delay_seconds)
        logger.info(f"🔄 Задача {task_data.get('task_id')} повторно добавлена в очередь (задержка: {delay_seconds}с)")
