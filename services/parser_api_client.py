"""
Клиент для работы с Parser API через Redis и HTTP.
"""
import asyncio
import json
import uuid
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger
import httpx
from services.redis_service import RedisService
from core.config import Config


class ParserAPIClient:
    """Клиент для работы с Parser API через Redis очереди."""
    
    def __init__(self, redis_service: Optional[RedisService] = None):
        """
        Инициализация клиента.
        
        Args:
            redis_service: Сервис Redis (если None, создается новый)
        """
        self.redis_service = redis_service or RedisService(redis_url=Config.REDIS_URL)
        self.request_timeout = 60  # Таймаут ожидания ответа в секундах (увеличен для get_item_variants)
        self.queue_name = "parser_api:requests"
        self.response_queue_prefix = "parser_api:response:"
        self.parser_api_url = Config.PARSER_API_URL
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _ensure_connected(self):
        """Убеждается, что Redis подключен."""
        if not self.redis_service.is_connected():
            await self.redis_service.connect()
    
    async def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправляет запрос в очередь и ждет ответа.
        
        Args:
            method: Название метода API
            params: Параметры запроса
            
        Returns:
            Результат выполнения запроса
            
        Raises:
            TimeoutError: Если ответ не получен в течение таймаута
            Exception: Если произошла ошибка при выполнении запроса
        """
        await self._ensure_connected()
        
        # Генерируем уникальный ID запроса
        request_id = str(uuid.uuid4())
        response_queue = f"{self.response_queue_prefix}{request_id}"
        
        # Формируем запрос
        request_data = {
            "request_id": request_id,
            "method": method,
            "params": params
        }
        
        logger.debug(f"📤 ParserAPIClient: Отправка запроса {request_id}: method={method}, params={params}")
        
        # Отправляем запрос в очередь
        await self.redis_service.push_to_queue(self.queue_name, request_data)
        
        # Ждем ответа (проверяем очередь каждые 0.1 секунды)
        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > self.request_timeout:
                logger.error(f"❌ ParserAPIClient: Таймаут ожидания ответа для запроса {request_id}")
                raise TimeoutError(f"Таймаут ожидания ответа для запроса {request_id}")
            
            # Пытаемся получить ответ
            response_data = await self.redis_service.pop_from_queue(response_queue, timeout=0.1)
            
            if response_data:
                # Проверяем, что это ответ на наш запрос
                if response_data.get("request_id") == request_id:
                    result = response_data.get("result", {})
                    
                    if result.get("success"):
                        logger.debug(f"✅ ParserAPIClient: Получен успешный ответ для запроса {request_id}")
                        return result
                    else:
                        error = result.get("error", "Unknown error")
                        logger.error(f"❌ ParserAPIClient: Ошибка в ответе для запроса {request_id}: {error}")
                        raise Exception(f"Ошибка API: {error}")
            
            # Небольшая задержка перед следующей проверкой
            await asyncio.sleep(0.05)
    
    async def validate_hash_name(self, appid: int, hash_name: str) -> Tuple[bool, Optional[int]]:
        """
        Проверяет корректность hash_name и возвращает количество доступных лотов.
        
        Args:
            appid: ID приложения
            hash_name: Хэш-имя предмета для проверки
            
        Returns:
            Tuple[bool, Optional[int]]: (валидность, количество лотов или None)
        """
        logger.debug(f"🔍 ParserAPIClient: validate_hash_name(appid={appid}, hash_name='{hash_name}')")
        
        try:
            result = await self._send_request("validate_hash_name", {
                "appid": appid,
                "hash_name": hash_name
            })
            
            is_valid = result.get("is_valid", False)
            total_count = result.get("total_count")
            
            logger.debug(f"✅ ParserAPIClient: validate_hash_name результат: is_valid={is_valid}, total_count={total_count}")
            return is_valid, total_count
            
        except Exception as e:
            logger.error(f"❌ ParserAPIClient: Ошибка при validate_hash_name: {e}", exc_info=True)
            raise
    
    async def get_item_variants(self, item_name: str) -> List[Dict[str, Any]]:
        """
        Получает все варианты предмета (разные износы).
        
        Args:
            item_name: Название предмета для поиска
            
        Returns:
            Список вариантов предмета с их hash_name и степенью износа
        """
        logger.debug(f"🔍 ParserAPIClient: get_item_variants(item_name='{item_name}')")
        
        try:
            result = await self._send_request("get_item_variants", {
                "item_name": item_name
            })
            
            variants = result.get("variants", [])
            logger.debug(f"✅ ParserAPIClient: get_item_variants результат: найдено {len(variants)} вариантов")
            return variants
            
        except Exception as e:
            logger.error(f"❌ ParserAPIClient: Ошибка при get_item_variants: {e}", exc_info=True)
            raise
    
    async def _ensure_http_client(self):
        """Убеждается, что HTTP клиент создан."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
    
    async def get_currency_rates(self) -> Optional[Dict[str, float]]:
        """
        Получает курсы валют (THB, CNY, RUB к USD) через HTTP запрос к parser-api.
        
        Returns:
            Словарь с курсами валют: {"THB": 35.5, "CNY": 7.2, "RUB": 90.0} или None при ошибке
        """
        await self._ensure_http_client()
        
        # Пробуем несколько вариантов URL (DNS может не работать)
        urls_to_try = [
            f"{self.parser_api_url}/currency-rates",
            "http://172.18.0.2:8000/currency-rates",  # Fallback на IP адрес
        ]
        
        for url in urls_to_try:
            try:
                logger.debug(f"🌐 ParserAPIClient: HTTP запрос к {url}")
                
                response = await self._http_client.get(url, timeout=10.0)
                response.raise_for_status()
                
                data = response.json()
                if data.get("success"):
                    rates = data.get("rates", {})
                    logger.debug(f"✅ ParserAPIClient: Получены курсы валют: {rates}")
                    return rates
                else:
                    logger.warning(f"⚠️ ParserAPIClient: API вернул success=False: {data.get('detail', 'Unknown error')}")
                    continue
                    
            except httpx.ConnectError as e:
                logger.debug(f"⚠️ ParserAPIClient: Не удалось подключиться к {url}: {e}, пробуем следующий...")
                continue
            except httpx.HTTPError as e:
                logger.warning(f"⚠️ ParserAPIClient: HTTP ошибка при запросе к {url}: {e}, пробуем следующий...")
                continue
            except Exception as e:
                logger.warning(f"⚠️ ParserAPIClient: Ошибка при запросе к {url}: {e}, пробуем следующий...")
                continue
        
        logger.error(f"❌ ParserAPIClient: Не удалось получить курсы валют ни с одного URL")
        return None
    
    async def close(self):
        """Закрывает HTTP клиент."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

