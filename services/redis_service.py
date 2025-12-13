"""
Сервис для работы с Redis (коммуникация между сервисами).
"""
import json
import asyncio
from typing import Optional, Dict, Any, Callable
from loguru import logger

try:
    import redis.asyncio as redis
except ImportError:
    redis = None
    logger.warning("Redis не установлен. Установите: pip install redis")


class RedisService:
    """Сервис для работы с Redis (очереди сообщений, pub/sub)."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Инициализация Redis сервиса.
        
        Args:
            redis_url: URL подключения к Redis (по умолчанию localhost:6379)
        """
        if redis is None:
            raise ImportError("Redis не установлен. Установите: pip install redis")
        
        self.redis_url = redis_url
        self._client: Optional[redis.Redis] = None
        self._is_connected = False
        self._pubsub: Optional[redis.client.PubSub] = None
        self._running = False
    
    async def connect(self):
        """Подключается к Redis."""
        if self._client is None:
            self._client = await redis.from_url(
                self.redis_url,
                decode_responses=True,
                encoding="utf-8"
            )
            self._is_connected = True
            logger.info(f"✅ Подключено к Redis: {self.redis_url}")
    
    async def disconnect(self):
        """Отключается от Redis."""
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
            self._pubsub = None
        
        if self._client:
            await self._client.close()
            self._client = None
            self._is_connected = False
            logger.info("❌ Отключено от Redis")
    
    def is_connected(self) -> bool:
        """Проверяет, подключен ли клиент к Redis."""
        return self._is_connected and self._client is not None
    
    async def publish(self, channel: str, message: Dict[str, Any]):
        """
        Публикует сообщение в канал Redis.
        
        Args:
            channel: Название канала
            message: Словарь с данными сообщения
        """
        if self._client is None:
            await self.connect()
        
        try:
            message_json = json.dumps(message, ensure_ascii=False)
            await self._client.publish(channel, message_json)
            logger.debug(f"📤 Опубликовано сообщение в канал '{channel}': {message}")
        except Exception as e:
            logger.error(f"Ошибка при публикации в Redis: {e}")
    
    async def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]):
        """
        Подписывается на канал Redis и вызывает callback при получении сообщения.
        
        Args:
            channel: Название канала
            callback: Функция для обработки сообщений (async или sync)
        """
        if self._client is None:
            await self.connect()
        
        self._pubsub = self._client.pubsub()
        await self._pubsub.subscribe(channel)
        logger.info(f"📥 Подписка на канал '{channel}'")
        
        self._running = True
        
        async def _listen():
            """Слушает сообщения в канале."""
            while self._running:
                try:
                    # Используем timeout=0.1 для более быстрой обработки (100мс вместо 1 секунды)
                    # Это позволяет обрабатывать уведомления почти мгновенно
                    message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                    if message and message['type'] == 'message':
                        try:
                            data = json.loads(message['data'])
                            if asyncio.iscoroutinefunction(callback):
                                await callback(data)
                            else:
                                callback(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"Ошибка декодирования JSON из Redis: {e}")
                        except Exception as e:
                            logger.error(f"Ошибка в callback для Redis сообщения: {e}")
                except asyncio.TimeoutError:
                    # Нормальная ситуация - нет новых сообщений, продолжаем слушать
                    continue
                except Exception as e:
                    logger.error(f"Ошибка при получении сообщения из Redis: {e}")
                    await asyncio.sleep(0.1)  # Уменьшили задержку при ошибке
        
        # Запускаем слушателя в фоне
        asyncio.create_task(_listen())
    
    async def unsubscribe(self, channel: str):
        """Отписывается от канала."""
        if self._pubsub:
            await self._pubsub.unsubscribe(channel)
            logger.info(f"📴 Отписка от канала '{channel}'")
    
    async def stop(self):
        """Останавливает подписки и отключается."""
        self._running = False
        await self.unsubscribe("*")
        await self.disconnect()
    
    async def lpush(self, key: str, *values: str) -> int:
        """
        Добавляет элементы в начало списка (очередь).
        
        Args:
            key: Ключ списка
            *values: Значения для добавления
            
        Returns:
            Длина списка после добавления
        """
        if self._client is None:
            await self.connect()
        
        try:
            result = await self._client.lpush(key, *values)
            return result
        except Exception as e:
            logger.error(f"❌ RedisService.lpush: Ошибка при добавлении в список '{key}': {e}")
            raise
    
    async def rpop(self, key: str, timeout: float = 0) -> Optional[str]:
        """
        Удаляет и возвращает последний элемент списка (FIFO очередь).
        Если timeout > 0, использует BRPOP (блокирующий pop).
        
        Args:
            key: Ключ списка
            timeout: Таймаут в секундах (0 = неблокирующий)
            
        Returns:
            Значение элемента или None если список пуст
        """
        if self._client is None:
            await self.connect()
        
        try:
            if timeout > 0:
                # Блокирующий pop (BRPOP)
                result = await self._client.brpop(key, timeout=timeout)
                if result:
                    return result[1]  # BRPOP возвращает (key, value)
                return None
            else:
                # Неблокирующий pop
                return await self._client.rpop(key)
        except Exception as e:
            logger.error(f"❌ RedisService.rpop: Ошибка при получении из списка '{key}': {e}")
            raise
    
    async def llen(self, key: str) -> int:
        """
        Возвращает длину списка.
        
        Args:
            key: Ключ списка
            
        Returns:
            Длина списка
        """
        if self._client is None:
            await self.connect()
        
        try:
            return await self._client.llen(key)
        except Exception as e:
            logger.error(f"❌ RedisService.llen: Ошибка при получении длины списка '{key}': {e}")
            return 0
    
    async def delete(self, key: str) -> bool:
        """
        Удаляет ключ из Redis.
        
        Args:
            key: Ключ для удаления
            
        Returns:
            True если ключ был удален, False если не существовал
        """
        if self._client is None:
            await self.connect()
        
        try:
            result = await self._client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"❌ RedisService.delete: Ошибка при удалении ключа '{key}': {e}")
            return False
    
    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        """
        Получает элементы из списка Redis.
        
        Args:
            key: Ключ списка
            start: Начальный индекс
            end: Конечный индекс (-1 для всех элементов)
            
        Returns:
            Список значений
        """
        if self._client is None:
            await self.connect()
        
        try:
            return await self._client.lrange(key, start, end)
        except Exception as e:
            logger.error(f"❌ RedisService.lrange: Ошибка при получении элементов списка '{key}': {e}")
            return []
    
    async def expire(self, key: str, seconds: int) -> bool:
        """
        Устанавливает TTL (время жизни) для ключа.
        
        Args:
            key: Ключ
            seconds: Время жизни в секундах
            
        Returns:
            True если успешно, False иначе
        """
        if self._client is None:
            await self.connect()
        
        try:
            return await self._client.expire(key, seconds)
        except Exception as e:
            logger.error(f"❌ RedisService.expire: Ошибка при установке TTL для ключа '{key}': {e}")
            return False
    
    async def push_to_queue(self, queue_name: str, data: Dict[str, Any]):
        """
        Добавляет сообщение в очередь (Redis Streams для лучшей масштабируемости).
        
        Args:
            queue_name: Название потока (stream)
            data: Данные для добавления
        """
        if self._client is None:
            await self.connect()
        
        try:
            # Используем Redis Streams вместо простых списков
            # Это позволяет использовать consumer groups (как в Kafka)
            message_json = json.dumps(data, ensure_ascii=False)
            stream_name = f"stream:{queue_name}"
            
            # Добавляем сообщение в stream
            message_id = await self._client.xadd(
                stream_name,
                {"data": message_json},
                maxlen=10000  # Ограничиваем размер потока (последние 10000 сообщений)
            )
            
            # Получаем длину потока для логирования
            stream_length = await self._client.xlen(stream_name)
            logger.info(f"📥 Добавлено в поток '{stream_name}': task_id={data.get('task_id')}, message_id={message_id}, длина потока={stream_length}")
            logger.debug(f"   Полные данные: {data}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении в поток Redis: {e}")
            # Fallback на старый метод (список) для обратной совместимости
            try:
                message_json = json.dumps(data, ensure_ascii=False)
                await self._client.lpush(queue_name, message_json)
                logger.warning(f"⚠️ Использован fallback (список) для очереди '{queue_name}'")
            except Exception as fallback_error:
                logger.error(f"❌ Ошибка при fallback добавлении в очередь: {fallback_error}")
    
    async def pop_from_queue(self, queue_name: str, timeout: int = 0, consumer_group: str = "workers", consumer_name: str = "worker-1") -> Optional[Dict[str, Any]]:
        """
        Извлекает сообщение из очереди (Redis Streams с consumer groups).
        
        Args:
            queue_name: Название потока (stream)
            timeout: Таймаут в миллисекундах (0 = бесконечно, по умолчанию 1000мс)
            consumer_group: Имя группы потребителей (для распределения нагрузки)
            consumer_name: Имя конкретного потребителя
            
        Returns:
            Словарь с данными или None при таймауте
        """
        if self._client is None:
            await self.connect()
        
        try:
            stream_name = f"stream:{queue_name}"
            # Конвертируем timeout в миллисекунды
            # Если timeout <= 0, используем 1000мс (1 секунда) по умолчанию
            # Redis требует, чтобы block был неотрицательным целым числом
            if timeout > 0:
                timeout_ms = int(timeout * 1000)
            else:
                timeout_ms = 1000  # По умолчанию 1 секунда
            
            # Убеждаемся, что timeout_ms неотрицательное целое число
            if timeout_ms < 0:
                timeout_ms = 1000
            
            # Создаем consumer group, если не существует
            try:
                await self._client.xgroup_create(
                    stream_name,
                    consumer_group,
                    id="0",  # Начинаем с начала потока
                    mkstream=True  # Создаем stream, если не существует
                )
                logger.debug(f"📦 Создана consumer group '{consumer_group}' для потока '{stream_name}'")
            except Exception:
                # Группа уже существует - это нормально
                pass
            
            # Читаем сообщения из потока через consumer group
            # XREADGROUP GROUP group consumer [BLOCK milliseconds] [COUNT count] STREAMS key [key ...] id [id ...]
            # block должен быть неотрицательным целым числом (в миллисекундах)
            messages = await self._client.xreadgroup(
                consumer_group,
                consumer_name,
                {stream_name: ">"},  # ">" означает "новые сообщения, еще не прочитанные этой группой"
                count=1,  # Берем одно сообщение
                block=timeout_ms  # Блокируем на timeout_ms миллисекунд (должно быть >= 0)
            )
            
            if messages:
                stream, stream_messages = messages[0]
                if stream_messages:
                    message_id, message_data = stream_messages[0]
                    message_json = message_data.get("data")
                    
                    if message_json:
                        try:
                            parsed_message = json.loads(message_json)
                            if isinstance(parsed_message, dict):
                                task_id = parsed_message.get('task_id')
                                logger.debug(f"📤 Извлечено из потока '{stream_name}': task_id={task_id}, message_id={message_id}")
                                
                                # Подтверждаем обработку сообщения (ACK)
                                await self._client.xack(stream_name, consumer_group, message_id)
                                
                                return parsed_message
                            else:
                                logger.warning(f"⚠️ RedisService: Сообщение из потока не является словарем: {type(parsed_message)}")
                                return None
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ RedisService: Ошибка декодирования JSON из потока '{stream_name}': {e}, данные: {message_json[:100]}")
                            return None
            
            # Fallback на старый метод (список) для обратной совместимости
            try:
                result = await self._client.brpop(queue_name, timeout=timeout)
                if result:
                    _, message_json = result
                    parsed_message = json.loads(message_json)
                    if isinstance(parsed_message, dict):
                        logger.debug(f"📤 Извлечено из очереди (fallback) '{queue_name}': task_id={parsed_message.get('task_id')}")
                        return parsed_message
            except Exception:
                pass
            
            return None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"Ошибка при извлечении из потока Redis: {e}")
            return None
        
        return None
    
    async def get_cached_parsed_item(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает закэшированные данные парсинга предмета по listing_id.
        
        Args:
            listing_id: ID лота предмета
            
        Returns:
            Словарь с данными парсинга или None
        """
        if self._client is None:
            await self.connect()
        
        try:
            cache_key = f"parsed_item:{listing_id}"
            cached_data = await self._client.get(cache_key)
            if cached_data:
                data = json.loads(cached_data)
                logger.debug(f"💾 Redis: Найдены закэшированные данные для listing_id={listing_id}")
                return data
        except Exception as e:
            logger.debug(f"⚠️ Redis: Ошибка при получении кэша для listing_id={listing_id}: {e}")
        
        return None
    
    async def cache_parsed_item(self, listing_id: str, parsed_data: Dict[str, Any], ttl: int = 86400):
        """
        Сохраняет данные парсинга предмета в кэш.
        
        Args:
            listing_id: ID лота предмета
            parsed_data: Данные парсинга (float, pattern, stickers и т.д.)
            ttl: Время жизни кэша в секундах (по умолчанию 24 часа)
        """
        if self._client is None:
            await self.connect()
        
        try:
            cache_key = f"parsed_item:{listing_id}"
            data_json = json.dumps(parsed_data, ensure_ascii=False)
            await self._client.setex(cache_key, ttl, data_json)
            logger.debug(f"💾 Redis: Сохранены данные парсинга для listing_id={listing_id} (TTL={ttl}с)")
        except Exception as e:
            logger.warning(f"⚠️ Redis: Ошибка при сохранении кэша для listing_id={listing_id}: {e}")
    
    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Получает JSON данные из Redis по ключу.
        
        Args:
            key: Ключ для получения данных
            
        Returns:
            Словарь с данными или None
        """
        if self._client is None:
            await self.connect()
        try:
            json_data = await self._client.get(key)
            if json_data:
                logger.debug(f"📦 Redis: Получен JSON из кэша по ключу '{key}'")
                return json.loads(json_data)
        except Exception as e:
            logger.error(f"❌ Redis: Ошибка при получении JSON по ключу '{key}': {e}")
        return None

    async def set_json(self, key: str, data: Dict[str, Any], ex: Optional[int] = None):
        """
        Сохраняет JSON данные в Redis по ключу.
        
        Args:
            key: Ключ для сохранения данных
            data: Данные для сохранения
            ex: Время жизни в секундах (опционально)
        """
        if self._client is None:
            await self.connect()
        try:
            json_data = json.dumps(data, ensure_ascii=False)
            if ex:
                await self._client.setex(key, ex, json_data)
            else:
                await self._client.set(key, json_data)
            logger.debug(f"💾 Redis: Сохранен JSON по ключу '{key}'")
        except Exception as e:
            logger.error(f"❌ Redis: Ошибка при сохранении JSON по ключу '{key}': {e}")

    async def get(self, key: str) -> Optional[str]:
        """
        Получает значение по ключу из Redis.
        
        Args:
            key: Ключ для получения значения
            
        Returns:
            Значение или None если ключ не найден
        """
        if self._client is None:
            await self.connect()
        
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"❌ RedisService.get: Ошибка при получении '{key}': {e}")
            return None
    
    async def delete_key(self, key: str):
        """
        Удаляет ключ из Redis.
        
        Args:
            key: Ключ для удаления
        """
        if self._client is None:
            await self.connect()
        try:
            await self._client.delete(key)
            logger.debug(f"🗑️ Redis: Удален ключ '{key}'")
        except Exception as e:
            logger.error(f"❌ Redis: Ошибка при удалении ключа '{key}': {e}")

