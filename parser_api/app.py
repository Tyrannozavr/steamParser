"""
FastAPI сервис для работы с парсером Steam Market.
Обрабатывает запросы через Redis очереди.
"""
import asyncio
import json
import uuid
from typing import Optional, Dict, Any, List, Tuple
from fastapi import FastAPI, HTTPException
from loguru import logger
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.steam_parser import SteamMarketParser
from services.redis_service import RedisService
from services.proxy_manager import ProxyManager
from core import DatabaseManager
from core.config import Config

# Импорт версии
try:
    from version import get_version, get_version_info
    VERSION = get_version()
    VERSION_INFO = get_version_info()
except ImportError:
    VERSION = "unknown"
    VERSION_INFO = {"version": "unknown", "last_updated": "unknown", "changelog": ""}

app = FastAPI(title="Steam Market Parser API", version=VERSION)

# Глобальные переменные
redis_service: Optional[RedisService] = None
parser: Optional[SteamMarketParser] = None
proxy_manager: Optional[ProxyManager] = None
db_manager: Optional[DatabaseManager] = None
currency_service = None


@app.on_event("startup")
async def startup():
    """Инициализация при запуске сервиса."""
    global redis_service, parser, proxy_manager, db_manager, currency_service
    
    logger.info("=" * 80)
    logger.info(f"🚀 Parser API: Запуск сервиса...")
    logger.info(f"📦 Версия: {VERSION}")
    logger.info(f"📅 Обновлено: {VERSION_INFO.get('last_updated', 'unknown')}")
    logger.info("=" * 80)
    
    # Инициализация БД (для ProxyManager)
    try:
        db_manager = DatabaseManager(Config.DATABASE_URL)
        await db_manager.init_db()
        db_session = await db_manager.get_session()
        logger.info("✅ Parser API: БД инициализирована")
    except Exception as e:
        logger.warning(f"⚠️ Parser API: Не удалось инициализировать БД: {e}. Продолжаем без ProxyManager.")
        db_session = None
    
    # Инициализация Redis
    if Config.REDIS_ENABLED:
        redis_service = RedisService(redis_url=Config.REDIS_URL)
        await redis_service.connect()
        logger.info("✅ Parser API: Redis подключен")
    
    # Инициализация ProxyManager через фабрику (если есть БД)
    if db_session:
        try:
            from services.proxy_manager_factory import ProxyManagerFactory
            proxy_manager = await ProxyManagerFactory.get_instance(
                db_session=db_session,
                redis_service=redis_service,
                default_delay=0.2,  # Оптимальная частота из RATE_LIMITS_ANALYSIS.md
                site="steam"
            )
            # Запускаем фоновую проверку заблокированных прокси
            proxy_manager.start_background_proxy_check()
            logger.info("✅ Parser API: ProxyManager инициализирован через фабрику")
        except Exception as e:
            logger.warning(f"⚠️ Parser API: Не удалось инициализировать ProxyManager: {e}. Продолжаем без прокси.")
            proxy_manager = None
    else:
        logger.warning("⚠️ Parser API: ProxyManager не инициализирован (нет БД)")
        proxy_manager = None
    
    # Инициализация парсера с ProxyManager (если есть)
    parser = SteamMarketParser(redis_service=redis_service, proxy_manager=proxy_manager)
    await parser._ensure_client()
    # ВАЖНО: Убеждаемся, что proxy_manager установлен в parser
    if proxy_manager:
        parser.proxy_manager = proxy_manager
        logger.info("✅ Parser API: Парсер инициализирован с ProxyManager")
    else:
        logger.warning("⚠️ Parser API: Парсер инициализирован без ProxyManager")
    
    # Инициализация CurrencyService
    global currency_service
    try:
        from services.currency_service import CurrencyService
        currency_service = CurrencyService(
            redis_service=redis_service,
            proxy_manager=proxy_manager
        )
        logger.info("✅ Parser API: CurrencyService инициализирован")
    except Exception as e:
        logger.warning(f"⚠️ Parser API: Не удалось инициализировать CurrencyService: {e}")
        currency_service = None
    
    # Запускаем несколько воркеров для параллельной обработки запросов
    num_workers = 10  # Количество параллельных воркеров
    for i in range(num_workers):
        asyncio.create_task(process_requests_queue(worker_id=i))
    logger.info(f"✅ Parser API: Запущено {num_workers} воркеров для параллельной обработки запросов")


@app.on_event("shutdown")
async def shutdown():
    """Очистка при остановке сервиса."""
    global redis_service, parser, proxy_manager, db_manager
    
    logger.info("🛑 Parser API: Остановка сервиса...")
    
    if parser:
        await parser.close()
        logger.info("✅ Parser API: Парсер закрыт")
    
    if redis_service:
        await redis_service.disconnect()
        logger.info("✅ Parser API: Redis отключен")
    
    if db_manager:
        await db_manager.close()
        logger.info("✅ Parser API: БД закрыта")


async def process_requests_queue(worker_id: int = 0):
    """Обрабатывает запросы из Redis очереди параллельно."""
    global redis_service, parser, proxy_manager, db_manager
    
    if not redis_service:
        logger.error("❌ Parser API: Redis не инициализирован, очередь не будет обрабатываться")
        return
    
    queue_name = "parser_api:requests"
    response_queue_prefix = "parser_api:response:"
    
    logger.info(f"📥 Parser API: Воркер #{worker_id} начинает слушать очередь '{queue_name}'")
    
    # Используем уникальную consumer group для parser-api
    import socket
    consumer_name = f"parser-api-{socket.gethostname()}-worker-{worker_id}"
    consumer_group = "parser_api_workers"
    
    while True:
        try:
            # Получаем запрос из очереди (блокирующий вызов с таймаутом 1 секунда)
            # Используем уникальную consumer group для parser-api
            request_data = await redis_service.pop_from_queue(
                queue_name, 
                timeout=1,
                consumer_group=consumer_group,
                consumer_name=consumer_name
            )
            
            if request_data is None:
                # Таймаут - продолжаем слушать
                continue
            
            request_id = request_data.get("request_id")
            method = request_data.get("method")
            params = request_data.get("params", {})
            
            logger.info(f"📨 Parser API [Worker #{worker_id}]: Получен запрос {request_id}: method={method}")
            
            # Обрабатываем запрос асинхронно (не блокируя другие запросы)
            asyncio.create_task(handle_request(request_id, method, params, response_queue_prefix, worker_id))
            
        except Exception as e:
            logger.error(f"❌ Parser API [Worker #{worker_id}]: Ошибка в обработчике очереди: {e}", exc_info=True)
            await asyncio.sleep(1)


async def handle_request(request_id: str, method: str, params: Dict[str, Any], response_queue_prefix: str, worker_id: int):
    """Обрабатывает один запрос."""
    global redis_service, parser, proxy_manager
    
    try:
        # Обрабатываем запрос
        if method == "validate_hash_name":
            appid = params.get("appid", 730)
            hash_name = params.get("hash_name")
            if not hash_name:
                raise ValueError("hash_name обязателен")
            
            # ВАЖНО: Убеждаемся, что parser имеет proxy_manager
            # Если proxy_manager был инициализирован после создания parser, обновляем его
            if proxy_manager and parser.proxy_manager != proxy_manager:
                parser.proxy_manager = proxy_manager
                logger.debug(f"🔄 Parser API: Обновлен proxy_manager для parser")
            
            is_valid, total_count = await parser.validate_hash_name(appid=appid, hash_name=hash_name)
            result = {
                "success": True,
                "is_valid": is_valid,
                "total_count": total_count
            }
            
        elif method == "get_item_variants":
            item_name = params.get("item_name")
            if not item_name:
                raise ValueError("item_name обязателен")
            
            variants = await parser.get_item_variants(item_name=item_name)
            result = {
                "success": True,
                "variants": variants
            }
            
        elif method == "get_stickers_prices":
            sticker_names = params.get("sticker_names", [])
            delay = params.get("delay", 0.3)
            
            if not sticker_names:
                raise ValueError("sticker_names обязателен (список названий наклеек)")
            
            if not isinstance(sticker_names, list):
                raise ValueError("sticker_names должен быть списком")
            
            prices = await parser.get_stickers_prices(sticker_names=sticker_names, delay=delay)
            result = {
                "success": True,
                "prices": prices
            }
            
        else:
            raise ValueError(f"Неизвестный метод: {method}")
        
        logger.info(f"✅ Parser API [Worker #{worker_id}]: Запрос {request_id} обработан успешно")
        
    except Exception as e:
        logger.error(f"❌ Parser API [Worker #{worker_id}]: Ошибка при обработке запроса {request_id}: {e}", exc_info=True)
        result = {
            "success": False,
            "error": str(e)
        }
    
    # Отправляем ответ в очередь ответов
    response_queue = f"{response_queue_prefix}{request_id}"
    await redis_service.push_to_queue(response_queue, {
        "request_id": request_id,
        "result": result
    })
    logger.debug(f"📤 Parser API [Worker #{worker_id}]: Ответ отправлен в очередь '{response_queue}'")


@app.get("/health")
async def health_check():
    """Проверка здоровья сервиса."""
    return {
        "status": "ok",
        "version": VERSION,
        "redis_connected": redis_service.is_connected() if redis_service else False,
        "parser_initialized": parser is not None
    }


@app.get("/currency-rates")
async def get_currency_rates():
    """
    Получает курсы валют (THB, CNY, RUB к USD) с trueskins.org/currencies.
    Кэширует результат в Redis на 1 час.
    
    Returns:
        Словарь с курсами валют: {"THB": 35.5, "CNY": 7.2, "RUB": 90.0}
    """
    global currency_service
    
    if not currency_service:
        raise HTTPException(
            status_code=503,
            detail="CurrencyService не инициализирован"
        )
    
    try:
        rates = await currency_service.get_currency_rates()
        if not rates:
            raise HTTPException(
                status_code=503,
                detail="Не удалось получить курсы валют"
            )
        return {
            "success": True,
            "rates": rates
        }
    except Exception as e:
        logger.error(f"❌ Parser API: Ошибка при получении курсов валют: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при получении курсов валют: {str(e)}"
        )


@app.get("/")
async def root():
    """Корневой endpoint."""
    return {
        "service": "Steam Market Parser API",
        "version": VERSION,
        "endpoints": {
            "health": "/health",
            "version": "/version",
            "currency_rates": "/currency-rates",
            "api": "Используйте Redis очереди для запросов",
            "methods": [
                "validate_hash_name",
                "get_item_variants",
                "get_stickers_prices"
            ]
        }
    }


@app.get("/version")
async def get_version():
    """Возвращает информацию о версии приложения."""
    return VERSION_INFO

