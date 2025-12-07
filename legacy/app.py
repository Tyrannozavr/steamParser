"""
Главный файл приложения для мониторинга Steam Market.
Обеспечивает устойчивость к перезагрузкам и работу в контейнере.
"""
import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional
from loguru import logger

from config import Config

# Настройка логирования
def setup_logging():
    """Настраивает логирование."""
    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"steam_monitor_{{time:YYYY-MM-DD}}.log"
    
    logger.remove()  # Удаляем дефолтный handler
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

# Настраиваем логирование при импорте
setup_logging()

from database import DatabaseManager
from proxy_manager import ProxyManager
from monitoring_service import MonitoringService
from models import SearchFilters, FloatRange, PatternList, StickersFilter
from telegram import TelegramBotManager


class SteamMonitorApp:
    """Главный класс приложения."""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Инициализация приложения.
        
        Args:
            db_path: Путь к файлу базы данных (если None, берется из Config)
        """
        # Валидация конфигурации
        try:
            Config.validate()
        except ValueError as e:
            logger.error(f"Ошибка конфигурации: {e}")
            logger.error("Создайте .env файл на основе .env.example")
            raise
        
        self.db_path = db_path or Config.DATABASE_PATH
        self.db_manager: Optional[DatabaseManager] = None
        self.db_session = None
        self.proxy_manager: Optional[ProxyManager] = None
        self.monitoring_service: Optional[MonitoringService] = None
        self.telegram_bot: Optional[TelegramBotManager] = None
        self._shutdown_event = asyncio.Event()
        
        # Обработка сигналов для корректного завершения
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов для корректного завершения."""
        logger.info(f"Получен сигнал {signum}, начинаем корректное завершение...")
        self._shutdown_event.set()
    
    async def initialize(self):
        """Инициализирует все компоненты приложения."""
        logger.info("Инициализация приложения...")
        
        # Создаем директорию для логов
        Path("logs").mkdir(exist_ok=True)
        
        # Инициализируем БД
        self.db_manager = DatabaseManager(self.db_path)
        await self.db_manager.init_db()
        self.db_session = await self.db_manager.get_session()
        
        # Инициализируем менеджер прокси
        self.proxy_manager = ProxyManager(self.db_session)
        
        # Инициализируем Telegram бота
        self.telegram_bot = TelegramBotManager(
            token=Config.TELEGRAM_BOT_TOKEN,
            chat_id=Config.TELEGRAM_CHAT_ID,
            db_manager=self.db_manager,
            proxy_manager=self.proxy_manager,
            monitoring_service=None  # Будет установлен после создания
        )
        
        # Инициализируем сервис мониторинга с callback для уведомлений
        self.monitoring_service = MonitoringService(
            self.db_session,
            self.proxy_manager,
            notification_callback=self.telegram_bot.send_notification
        )
        
        # Обновляем ссылку на monitoring_service в боте
        self.telegram_bot.monitoring_service = self.monitoring_service
        
        logger.info("Приложение инициализировано")
    
    async def shutdown(self):
        """Корректно завершает работу приложения."""
        logger.info("Завершение работы приложения...")
        
        if self.monitoring_service:
            await self.monitoring_service.stop()
        
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
            
            # Запускаем Telegram бота в фоне
            bot_task = asyncio.create_task(self.telegram_bot.start_polling())
            
            logger.info("Приложение запущено и работает")
            logger.info(f"Telegram бот запущен, чат ID: {Config.TELEGRAM_CHAT_ID}")
            
            # Ждем сигнала завершения
            await self._shutdown_event.wait()
            
            # Останавливаем бота
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
            await self.telegram_bot.stop()
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def add_proxy(self, url: str, delay: float = 1.0):
        """Добавляет прокси."""
        return await self.proxy_manager.add_proxy(url, delay)
    
    async def add_monitoring_task(
        self,
        name: str,
        item_name: str,
        filters: SearchFilters,
        check_interval: int = 60
    ):
        """Добавляет задачу мониторинга."""
        return await self.monitoring_service.add_monitoring_task(
            name, item_name, filters, check_interval
        )
    
    async def get_statistics(self):
        """Получает статистику."""
        proxy_stats = await self.proxy_manager.get_proxy_stats()
        monitoring_stats = await self.monitoring_service.get_statistics()
        
        return {
            "proxies": proxy_stats,
            "monitoring": monitoring_stats
        }


async def main():
    """Точка входа в приложение."""
    app = SteamMonitorApp()
    
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.exception(f"Необработанная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

