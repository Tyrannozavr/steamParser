"""
Telegram бот - отдельный сервис для управления через Telegram.
Общается с Parsing Worker через Redis.
"""
import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional
from loguru import logger

from core import Config, DatabaseManager
from core.logger import setup_logging
from services import ProxyManager
from services.redis_service import RedisService
from telegram import TelegramBotManager

# Импорт версии
try:
    from version import get_version, get_version_info
    VERSION = get_version()
    VERSION_INFO = get_version_info()
except ImportError:
    VERSION = "unknown"
    VERSION_INFO = {"version": "unknown", "last_updated": "unknown", "changelog": ""}

# Настройка логирования
setup_logging(service_name="telegram_bot", enable_task_logging=True, enable_console=True)


class TelegramBotApplication:
    """Приложение Telegram бота."""
    
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
        logger.info("=" * 80)
        logger.info("Инициализация Telegram Bot Application...")
        logger.info(f"📦 Версия: {VERSION}")
        logger.info(f"📅 Обновлено: {VERSION_INFO.get('last_updated', 'unknown')}")
        logger.info("=" * 80)
        
        # ВАЖНО: Сначала инициализируем БД (создаем таблицы через SQLAlchemy)
        # Затем применяем миграции для изменения структуры существующих таблиц
        self.db_manager = DatabaseManager(Config.DATABASE_URL)
        await self.db_manager.init_db()
        logger.info("✅ Таблицы БД созданы через SQLAlchemy")
        
        # Применяем миграции БД после создания таблиц (если скрипт доступен)
        # ВАЖНО: Это не критично - если скрипт недоступен, миграции можно применить вручную
        import subprocess
        import os
        migration_script = "/app/docker/apply-migrations.sh"
        if os.path.exists(migration_script) and os.access(migration_script, os.X_OK):
            logger.info("🔄 Применение миграций базы данных...")
            try:
                env = os.environ.copy()
                env['POSTGRES_HOST'] = 'postgres'
                result = subprocess.run(
                    [migration_script],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode == 0:
                    logger.info("✅ Миграции применены успешно")
                    if result.stdout:
                        for line in result.stdout.strip().split('\n'):
                            if line.strip():
                                logger.info(f"   {line}")
                else:
                    logger.warning(f"⚠️ Ошибка при применении миграций: {result.stderr}")
            except FileNotFoundError:
                logger.debug(f"ℹ️ Скрипт миграций не найден: {migration_script} (это нормально, если файл не смонтирован)")
            except Exception as e:
                logger.debug(f"ℹ️ Не удалось применить миграции: {e} (это не критично)")
        else:
            logger.debug(f"ℹ️ Скрипт миграций недоступен: {migration_script} (это нормально, миграции можно применить вручную)")
        
        # Инициализируем БД
        self.db_manager = DatabaseManager(Config.DATABASE_URL)
        await self.db_manager.init_db()
        self.db_session = await self.db_manager.get_session()
        
        # Инициализируем Redis (обязательно для бота)
        if not Config.REDIS_ENABLED:
            logger.error("❌ Redis должен быть включен для Telegram Bot!")
            logger.error("   Установите REDIS_ENABLED=true в .env")
            raise ValueError("Redis должен быть включен для Telegram Bot")
        
        try:
            self.redis_service = RedisService(redis_url=Config.REDIS_URL)
            await self.redis_service.connect()
            logger.info(f"✅ Redis подключен: {Config.REDIS_URL}")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к Redis: {e}")
            raise
        
        # Инициализируем менеджер прокси через фабрику с Redis для кэширования (после инициализации Redis)
        from services.proxy_manager_factory import ProxyManagerFactory
        self.proxy_manager = await ProxyManagerFactory.get_instance(
            db_session=self.db_session,
            redis_service=self.redis_service,
            default_delay=0.2,  # Оптимальная частота из RATE_LIMITS_ANALYSIS.md
            site="steam"
        )
        
        # Инициализируем Telegram бота
        # MonitoringService создается внутри бота для управления задачами через БД
        from services import MonitoringService
        monitoring_service = MonitoringService(
            self.db_session,
            self.proxy_manager,
            notification_callback=None,  # Уведомления через Redis
            redis_service=self.redis_service
        )
        
        self.telegram_bot = TelegramBotManager(
            token=Config.TELEGRAM_BOT_TOKEN,
            chat_id=Config.TELEGRAM_CHAT_ID,
            db_manager=self.db_manager,
            proxy_manager=self.proxy_manager,
            monitoring_service=monitoring_service,
            redis_service=self.redis_service
        )
        
        # Запускаем сервис мониторинга, чтобы задачи сразу начинали работать
        await monitoring_service.start()
        logger.info("✅ Сервис мониторинга запущен")
        
        logger.info("✅ Telegram Bot Application инициализирован")
    
    async def shutdown(self):
        """Корректно завершает работу."""
        logger.info("Завершение работы Telegram Bot Application...")
        
        if self.telegram_bot:
            await self.telegram_bot.stop()
        
        if self.redis_service:
            try:
                await self.redis_service.disconnect()
            except Exception as e:
                logger.warning(f"Ошибка при остановке Redis: {e}")
        
        if self.db_session:
            await self.db_session.close()
        
        if self.db_manager:
            await self.db_manager.close()
        
        logger.info("Telegram Bot Application завершен")
    
    async def run(self):
        """Запускает приложение."""
        try:
            await self.initialize()
            
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
    app = TelegramBotApplication()
    
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания")
    except Exception as e:
        logger.exception(f"Необработанная ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

