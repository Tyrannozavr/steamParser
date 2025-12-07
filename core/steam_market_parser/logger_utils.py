"""
Утилиты для логирования в оба логгера (основной и task_logger).
"""
from typing import Optional
from loguru import logger


def log_both(level: str, message: str, task_logger=None):
    """
    Логирует сообщение в обычный logger и task_logger.
    
    Args:
        level: Уровень логирования ('info', 'warning', 'error', 'debug')
        message: Сообщение для логирования
        task_logger: Опциональный task_logger для логирования в файл задачи
    """
    try:
        # Логируем в основной logger
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        elif level == "debug":
            logger.debug(message)
        else:
            logger.info(message)
        
        # Также логируем в task_logger, если он доступен
        if task_logger:
            try:
                if level == "info":
                    task_logger.info(message)
                elif level == "warning":
                    task_logger.warning(message)
                elif level == "error":
                    task_logger.error(message)
                elif level == "debug":
                    task_logger.debug(message)
            except Exception:
                pass  # Игнорируем ошибки с task_logger
    except Exception:
        pass  # Игнорируем ошибки логирования

