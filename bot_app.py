"""
Главное приложение - Telegram бот для управления мониторингом Steam Market.
Все управление через команды и кнопки бота.
"""
import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional
from loguru import logger

from core import Config, DatabaseManager
from services import MonitoringService, ProxyManager
from services.redis_service import RedisService
from telegram import TelegramBotManager

# Настройка логирования
def setup_logging():
    """Настраивает логирование."""
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"steam_monitor_{{time:YYYY-MM-DD}}.log"
    
    logger.remove()
    logger.add(
        str(log_file),
        rotation="00:00",
        retention="30 days",
        level=Config.LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        encoding="utf-8"
    )
    logger.add(
        sys.stderr,
        level=Config.LOG_LEVEL,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )

setup_logging()


class BotApplication:
    """Главное приложение на основе Telegram бота."""
    
    def __init__(self):
        """Инициализация приложения."""
        # Валидация конфигурации
        try:
            Config.validate()
        except ValueError as e:
            logger.error(f"Ошибка конфигурации: {e}")
            logger.error("Создайте .env файл на основе .env.example")
            raise
        
        self.db_manager: Optional[DatabaseManager] = None
        self.db_session = None
        self.proxy_manager: Optional[ProxyManager] = None
        self.monitoring_service: Optional[MonitoringService] = None
        self.telegram_bot: Optional[TelegramBotManager] = None
        self.redis_service: Optional[RedisService] = None
        self._shutdown_event = asyncio.Event()
        
        # Обработка сигналов
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов."""
        logger.info(f"Получен сигнал {signum}, завершение работы...")
        self._shutdown_event.set()
    
    async def initialize(self):
        """Инициализирует все компоненты."""
        logger.info("Инициализация приложения...")
        
        # Инициализируем БД
        self.db_manager = DatabaseManager(Config.DATABASE_URL)
        await self.db_manager.init_db()
        self.db_session = await self.db_manager.get_session()
        
        # Инициализируем Redis (если включен) - сначала, т.к. нужен для ProxyManager
        if Config.REDIS_ENABLED:
            try:
                self.redis_service = RedisService(redis_url=Config.REDIS_URL)
                await self.redis_service.connect()
                logger.info(f"✅ Redis подключен: {Config.REDIS_URL}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось подключиться к Redis: {e}. Продолжаем без Redis.")
                self.redis_service = None
        else:
            logger.info("ℹ️ Redis отключен в конфигурации")
            self.redis_service = None
        
        # Инициализируем менеджер прокси через фабрику
        from services.proxy_manager_factory import ProxyManagerFactory
        self.proxy_manager = await ProxyManagerFactory.get_instance(
            db_session=self.db_session,
            redis_service=self.redis_service,
            default_delay=0.2,  # Оптимальная частота из RATE_LIMITS_ANALYSIS.md
            site="steam"
        )
        
        # Инициализируем Telegram бота (сначала, чтобы можно было использовать его callback)
        self.telegram_bot = TelegramBotManager(
            token=Config.TELEGRAM_BOT_TOKEN,
            chat_id=Config.TELEGRAM_CHAT_ID,
            db_manager=self.db_manager,
            proxy_manager=self.proxy_manager,
            monitoring_service=None,  # Будет установлен после создания
            redis_service=self.redis_service
        )
        
        # Инициализируем сервис мониторинга
        self.monitoring_service = MonitoringService(
            self.db_session,
            self.proxy_manager,
            notification_callback=self.telegram_bot.send_notification if not Config.REDIS_ENABLED else None,
            redis_service=self.redis_service
        )
        
        # Устанавливаем ссылку на monitoring_service в боте
        self.telegram_bot.monitoring_service = self.monitoring_service
        
        logger.info("Приложение инициализировано")
    
    async def shutdown(self):
        """Корректно завершает работу."""
        logger.info("Завершение работы приложения...")
        
        if self.monitoring_service:
            await self.monitoring_service.stop()
        
        if self.telegram_bot:
            await self.telegram_bot.stop()
        
        if self.redis_service:
            try:
                await self.redis_service.stop()
            except Exception as e:
                logger.warning(f"Ошибка при остановке Redis: {e}")
        
        if self.db_session:
            await self.db_session.close()
        
        if self.db_manager:
            await self.db_manager.close()
        
        logger.info("Приложение завершено")
    
    async def run(self):
        """Запускает приложение."""
        try:
            await self.initialize()
            
            # Запускаем сервис мониторинга
            await self.monitoring_service.start()
            logger.info("Сервис мониторинга запущен")
            
            # Запускаем бота (блокирующий вызов)
            logger.info("Запуск Telegram бота...")
            logger.info(f"Бот готов к работе. Chat ID: {Config.TELEGRAM_CHAT_ID}")
            
            # Запускаем polling в фоне и ждем сигнала завершения
            bot_task = asyncio.create_task(self.telegram_bot.start_polling())
            
            # Ждем сигнала завершения
            await self._shutdown_event.wait()
            
            # Останавливаем бота
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise
        finally:
            await self.shutdown()


async def main():
    """Точка входа."""
    app = BotApplication()
    
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.exception(f"Необработанная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

