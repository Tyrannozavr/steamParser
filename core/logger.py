"""
Централизованное логирование с поддержкой разделения по задачам.
Использует loguru для логирования в файлы с ротацией по датам.
"""
import sys
from pathlib import Path
from typing import Optional
from loguru import logger
from contextvars import ContextVar

from core import Config

# Context variable для хранения текущего task_id в контексте выполнения
task_id_context: ContextVar[Optional[int]] = ContextVar('task_id', default=None)


def setup_logging(
    service_name: str,
    enable_task_logging: bool = True,
    enable_console: bool = True
) -> None:
    """
    Настраивает логирование для сервиса.
    
    Args:
        service_name: Имя сервиса (например, 'parsing_worker', 'telegram_bot')
        enable_task_logging: Включить ли разделение логов по задачам
        enable_console: Включить ли вывод в консоль (stderr)
    """
    log_dir = Path(Config.LOG_DIR)
    
    # Создаем директорию для логов (с родительскими директориями)
    try:
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
        # Пытаемся установить права доступа
        try:
            import os
            os.chmod(log_dir, 0o777)
        except (OSError, PermissionError):
            pass  # Игнорируем ошибки прав доступа
    except (OSError, PermissionError) as e:
        # Если не удалось создать директорию, логируем только в stderr
        logger.warning(f"Не удалось создать директорию логов {log_dir}: {e}. Логирование только в stderr.")
        logger.remove()
        if enable_console:
            logger.add(
                sys.stderr,
                level=Config.LOG_LEVEL,
                format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
            )
        return
    
    # Удаляем все существующие handlers
    logger.remove()
    
    # Основной файл лога для сервиса (ротация по датам)
    main_log_file = log_dir / f"{service_name}_{{time:YYYY-MM-DD}}.log"
    
    try:
        logger.add(
            str(main_log_file),
            rotation="00:00",  # Ротация в полночь
            retention="30 days",  # Храним логи 30 дней
            level=Config.LOG_LEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            encoding="utf-8",
            enqueue=True,  # Асинхронная запись для производительности
            backtrace=True,  # Показывать полный traceback
            diagnose=True  # Показывать переменные в traceback
        )
    except (OSError, PermissionError) as e:
        logger.warning(f"Не удалось создать файл лога {main_log_file}: {e}.")
    
    # Отдельный файл для ошибок (ERROR и CRITICAL)
    errors_log_file = log_dir / f"{service_name}_errors_{{time:YYYY-MM-DD}}.log"
    try:
        logger.add(
            str(errors_log_file),
            rotation="00:00",  # Ротация в полночь
            retention="90 days",  # Храним ошибки 90 дней
            level="ERROR",  # Только ERROR и CRITICAL
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
            encoding="utf-8",
            enqueue=True,
            backtrace=True,
            diagnose=True,
            filter=lambda record: record["level"].name in ["ERROR", "CRITICAL"]
        )
    except (OSError, PermissionError) as e:
        logger.warning(f"Не удалось создать файл лога ошибок {errors_log_file}: {e}.")
    
    # Создаем директорию для логов задач, если включено разделение по задачам
    if enable_task_logging:
        tasks_log_dir = log_dir / "tasks"
        try:
            tasks_log_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
            try:
                import os
                os.chmod(tasks_log_dir, 0o777)
            except (OSError, PermissionError):
                pass
        except (OSError, PermissionError) as e:
            logger.warning(f"Не удалось создать директорию для логов задач {tasks_log_dir}: {e}.")
            enable_task_logging = False
    
    # Вывод в консоль (stderr)
    if enable_console:
        logger.add(
            sys.stderr,
            level=Config.LOG_LEVEL,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            colorize=True
        )


def get_task_logger(task_id: Optional[int] = None) -> "TaskLogger":
    """
    Получает логгер для конкретной задачи.
    
    Args:
        task_id: ID задачи. Если None, используется task_id из контекста.
        
    Returns:
        TaskLogger: Логгер для задачи
    """
    if task_id is None:
        task_id = task_id_context.get()
    
    return TaskLogger(task_id)


def set_task_id(task_id: Optional[int]) -> None:
    """
    Устанавливает task_id в контексте выполнения.
    
    Args:
        task_id: ID задачи
    """
    task_id_context.set(task_id)


def get_task_id() -> Optional[int]:
    """
    Получает task_id из контекста выполнения.
    
    Returns:
        ID задачи или None
    """
    return task_id_context.get()


class TaskLogger:
    """
    Логгер для конкретной задачи.
    Автоматически создает отдельный файл лога для каждой задачи.
    """
    
    # Кэш для уже созданных логгеров задач
    _task_loggers: dict[int, int] = {}  # task_id -> sink_id
    
    def __init__(self, task_id: Optional[int]):
        """
        Инициализация логгера задачи.
        
        Args:
            task_id: ID задачи. Если None, логирование идет только в основной лог.
        """
        self.task_id = task_id
        
        if task_id is not None and task_id not in TaskLogger._task_loggers:
            self._setup_task_logger()
    
    def _setup_task_logger(self) -> None:
        """Настраивает отдельный файл лога для задачи."""
        if self.task_id is None:
            return
        
        log_dir = Path(Config.LOG_DIR)
        tasks_log_dir = log_dir / "tasks"
        
        # Создаем директорию, если не существует (с родительскими директориями)
        try:
            tasks_log_dir.mkdir(parents=True, exist_ok=True, mode=0o777)
            try:
                import os
                os.chmod(tasks_log_dir, 0o777)
            except (OSError, PermissionError):
                pass
        except (OSError, PermissionError):
            return
        
        # Файл лога для задачи (ротация по датам)
        task_log_file = tasks_log_dir / f"task_{self.task_id}_{{time:YYYY-MM-DD}}.log"
        
        try:
            # Создаем функцию фильтрации для этой конкретной задачи
            def task_filter(record):
                return record["extra"].get("task_id") == self.task_id
            
            # Добавляем handler для файла задачи
            sink_id = logger.add(
                str(task_log_file),
                rotation="00:00",  # Ротация в полночь
                retention="30 days",  # Храним логи 30 дней
                level=Config.LOG_LEVEL,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
                encoding="utf-8",
                filter=task_filter,
                enqueue=True,
                backtrace=True,
                diagnose=True
            )
            
            # Сохраняем sink_id для этой задачи
            TaskLogger._task_loggers[self.task_id] = sink_id
        except (OSError, PermissionError) as e:
            logger.warning(f"Не удалось создать файл лога для задачи {self.task_id}: {e}.")
    
    def info(self, message: str) -> None:
        """Логирует информационное сообщение."""
        if self.task_id is not None:
            logger.bind(task_id=self.task_id).info(message)
        else:
            logger.info(message)
    
    def debug(self, message: str) -> None:
        """Логирует отладочное сообщение."""
        if self.task_id is not None:
            logger.bind(task_id=self.task_id).debug(message)
        else:
            logger.debug(message)
    
    def warning(self, message: str) -> None:
        """Логирует предупреждение."""
        if self.task_id is not None:
            logger.bind(task_id=self.task_id).warning(message)
        else:
            logger.warning(message)
    
    def error(self, message: str) -> None:
        """Логирует ошибку."""
        if self.task_id is not None:
            logger.bind(task_id=self.task_id).error(message)
        else:
            logger.error(message)
    
    def exception(self, message: str) -> None:
        """Логирует исключение с traceback."""
        if self.task_id is not None:
            logger.bind(task_id=self.task_id).exception(message)
        else:
            logger.exception(message)
    
    def success(self, message: str) -> None:
        """Логирует успешное выполнение."""
        if self.task_id is not None:
            logger.bind(task_id=self.task_id).success(message)
        else:
            logger.success(message)


# Экспортируем основной logger для обратной совместимости
__all__ = ['logger', 'setup_logging', 'get_task_logger', 'set_task_id', 'get_task_id', 'TaskLogger']

