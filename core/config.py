"""
Конфигурация приложения из переменных окружения.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env файл
# Ищем .env в корне проекта (на уровень выше core/)
env_path = Path(__file__).parent.parent / ".env"
# Загружаем .env если он существует, иначе используем значения по умолчанию
if env_path.exists():
    load_dotenv(env_path)
else:
    # Пробуем загрузить из текущей директории (для Docker)
    load_dotenv()


class Config:
    """Класс конфигурации приложения."""
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://steam_user:steam_password@localhost:5432/steam_monitor"
    )
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # Proxy
    PROXY_DELAY_DEFAULT: float = float(os.getenv("PROXY_DELAY_DEFAULT", "10.0"))
    
    # Item Page Parsing Delay
    ITEM_PAGE_DELAY: float = float(os.getenv("ITEM_PAGE_DELAY", "1.5"))
    
    # Parallel Parsing (обработка предметов параллельно или последовательно)
    PARALLEL_PARSING: bool = os.getenv("PARALLEL_PARSING", "false").lower() == "true"
    
    # HTTP Client (httpx или curl_cffi для обхода блокировок)
    USE_CURL_CFFI: bool = os.getenv("USE_CURL_CFFI", "false").lower() == "true"
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_ENABLED: bool = os.getenv("REDIS_ENABLED", "false").lower() == "true"
    
    # Parser API
    PARSER_API_URL: str = os.getenv("PARSER_API_URL", "http://parser-api:8000")
    
    # Параллельная обработка задач
    MAX_CONCURRENT_TASKS: int = int(os.getenv("MAX_CONCURRENT_TASKS", "10"))  # Максимум одновременных задач в одном воркере
    
    # Parsing Worker
    ENABLE_MONITORING_SERVICE: bool = os.getenv("ENABLE_MONITORING_SERVICE", "true").lower() == "true"
    
    # RabbitMQ
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    RABBITMQ_ENABLED: bool = os.getenv("RABBITMQ_ENABLED", "true").lower() == "true"
    
    @classmethod
    def validate(cls) -> bool:
        """
        Проверяет, что все необходимые настройки заданы.
        
        Returns:
            True если все настройки валидны
            
        Raises:
            ValueError: Если обязательные настройки не заданы
        """
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN не задан в .env файле")
        if not cls.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID не задан в .env файле")
        
        if errors:
            error_msg = "\n".join(f"  - {e}" for e in errors)
            raise ValueError(
                f"Ошибка конфигурации:\n{error_msg}\n\n"
                f"Создайте .env файл на основе .env.example:\n"
                f"  cp .env.example .env\n"
                f"И заполните необходимые значения."
            )
        return True

