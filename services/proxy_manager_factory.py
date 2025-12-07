"""
Фабрика для создания и управления экземплярами ProxyManager.
Реализует singleton паттерн через фабрику для возможности расширения на другие сайты.
"""
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from services.proxy_manager import ProxyManager
from services.redis_service import RedisService


class ProxyManagerFactory:
    """Фабрика для создания ProxyManager с singleton паттерном."""
    
    _instances: Dict[str, ProxyManager] = {}
    _lock = None  # Будет инициализирован при первом использовании
    
    @classmethod
    def _get_lock(cls):
        """Ленивая инициализация lock."""
        if cls._lock is None:
            import asyncio
            cls._lock = asyncio.Lock()
        return cls._lock
    
    @classmethod
    async def get_instance(
        cls,
        db_session: AsyncSession,
        redis_service: Optional[RedisService] = None,
        default_delay: float = 0.2,  # Оптимальная частота из RATE_LIMITS_ANALYSIS.md
        site: str = "steam"  # Для будущего расширения на другие сайты
    ) -> ProxyManager:
        """
        Получает или создает экземпляр ProxyManager для указанного сайта.
        
        Args:
            db_session: Сессия базы данных
            redis_service: Сервис Redis (опционально)
            default_delay: Задержка по умолчанию между запросами (секунды)
            site: Идентификатор сайта (по умолчанию "steam")
            
        Returns:
            Экземпляр ProxyManager (singleton для каждого сайта)
        """
        lock = cls._get_lock()
        
        async with lock:
            instance_key = f"{site}_{id(db_session)}"
            
            if instance_key not in cls._instances:
                logger.info(f"🏭 ProxyManagerFactory: Создаем новый экземпляр ProxyManager для сайта '{site}'")
                cls._instances[instance_key] = ProxyManager(
                    db_session=db_session,
                    default_delay=default_delay,
                    redis_service=redis_service
                )
                logger.info(f"✅ ProxyManagerFactory: Экземпляр создан (key={instance_key})")
            else:
                logger.debug(f"♻️ ProxyManagerFactory: Используем существующий экземпляр для сайта '{site}' (key={instance_key})")
            
            return cls._instances[instance_key]
    
    @classmethod
    async def clear_instance(cls, site: str = "steam", db_session_id: Optional[int] = None):
        """
        Очищает экземпляр ProxyManager (для тестирования или пересоздания).
        
        Args:
            site: Идентификатор сайта
            db_session_id: ID сессии БД (опционально, для точного удаления)
        """
        lock = cls._get_lock()
        
        async with lock:
            if db_session_id:
                instance_key = f"{site}_{db_session_id}"
            else:
                # Удаляем все экземпляры для этого сайта
                keys_to_remove = [k for k in cls._instances.keys() if k.startswith(f"{site}_")]
                for key in keys_to_remove:
                    del cls._instances[key]
                    logger.info(f"🗑️ ProxyManagerFactory: Удален экземпляр (key={key})")
                return
            
            if instance_key in cls._instances:
                del cls._instances[instance_key]
                logger.info(f"🗑️ ProxyManagerFactory: Удален экземпляр (key={instance_key})")
    
    @classmethod
    def get_instance_sync(cls, site: str = "steam") -> Optional[ProxyManager]:
        """
        Получает экземпляр ProxyManager синхронно (без создания).
        Используется для доступа к уже созданному экземпляру.
        
        Args:
            site: Идентификатор сайта
            
        Returns:
            ProxyManager или None если не создан
        """
        # Ищем первый подходящий экземпляр для этого сайта
        for key, instance in cls._instances.items():
            if key.startswith(f"{site}_"):
                return instance
        return None

