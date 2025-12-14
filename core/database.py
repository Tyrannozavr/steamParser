"""
Модуль для работы с базой данных.
Использует SQLAlchemy с asyncpg для асинхронной работы с PostgreSQL.
"""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


class Proxy(Base):
    """Модель для хранения прокси-серверов."""
    __tablename__ = "proxies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, comment="URL прокси в формате http://user:pass@host:port")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="Активен ли прокси")
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Время последнего использования")
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment="Количество успешных запросов")
    fail_count: Mapped[int] = mapped_column(Integer, default=0, comment="Количество неудачных запросов")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Последняя ошибка")
    delay_seconds: Mapped[float] = mapped_column(Float, default=1.0, comment="Задержка между запросами для этого прокси (секунды)")
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Время до которого прокси заблокирован (NULL = не заблокирован)")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Proxy(id={self.id}, url={self.url[:30]}..., active={self.is_active})>"


class MonitoringTask(Base):
    """Модель для задач мониторинга предметов."""
    __tablename__ = "monitoring_tasks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Название задачи мониторинга")
    item_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Название предмета для поиска")
    appid: Mapped[int] = mapped_column(Integer, default=730, comment="ID приложения Steam")
    currency: Mapped[int] = mapped_column(Integer, default=1, comment="Валюта (1 = USD)")
    
    # Фильтры (хранятся как JSONB для эффективных запросов)
    filters_json: Mapped[dict] = mapped_column(JSONB(none_as_null=True), nullable=False, comment="JSONB с настройками фильтров")
    
    # Настройки мониторинга
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="Активна ли задача")
    check_interval: Mapped[int] = mapped_column(Integer, default=60, comment="Интервал проверки в секундах")
    last_check: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Время последней проверки")
    next_check: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Время следующей проверки")
    
    # Статистика
    total_checks: Mapped[int] = mapped_column(Integer, default=0, comment="Всего проверок")
    items_found: Mapped[int] = mapped_column(Integer, default=0, comment="Найдено предметов")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def get_filters_dict(self) -> Dict[str, Any]:
        """Получает фильтры как словарь."""
        return self.filters_json if isinstance(self.filters_json, dict) else json.loads(self.filters_json)
    
    def set_filters_dict(self, filters: Dict[str, Any]):
        """Устанавливает фильтры из словаря."""
        self.filters_json = filters
    
    def __repr__(self):
        return f"<MonitoringTask(id={self.id}, name={self.name}, item={self.item_name}, active={self.is_active})>"


class FoundItem(Base):
    """Модель для хранения найденных предметов."""
    __tablename__ = "found_items"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="ID задачи мониторинга")
    item_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Название предмета")
    price: Mapped[float] = mapped_column(Float, nullable=False, comment="Цена предмета")
    
    # Данные предмета (хранятся как JSON)
    item_data_json: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON с данными предмета (float, pattern, stickers и т.д.)")
    
    # Статус уведомления
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, comment="Отправлено ли уведомление")
    notification_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Время отправки уведомления")
    
    # Ссылки
    market_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, comment="URL страницы на Steam Market")
    inspect_links: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Inspect ссылки (JSON массив)")
    
    found_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="Время обнаружения")
    
    def get_item_data(self) -> Dict[str, Any]:
        """Получает данные предмета как словарь."""
        return json.loads(self.item_data_json)
    
    def set_item_data(self, data: Dict[str, Any]):
        """Устанавливает данные предмета из словаря."""
        self.item_data_json = json.dumps(data, ensure_ascii=False)
    
    def __repr__(self):
        return f"<FoundItem(id={self.id}, task_id={self.task_id}, item={self.item_name}, price=${self.price:.2f})>"


class AppSettings(Base):
    """Модель для настроек приложения."""
    __tablename__ = "app_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, comment="Ключ настройки")
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="Значение настройки (может быть JSON)")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Описание настройки")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<AppSettings(key={self.key}, value={self.value[:50]}...)>"


class DatabaseManager:
    """Менеджер для работы с базой данных."""
    
    def __init__(self, database_url: str = None):
        """
        Инициализация менеджера БД.
        
        Args:
            database_url: URL подключения к PostgreSQL (например, postgresql+asyncpg://user:pass@host:port/db)
                         Если не указан, используется Config.DATABASE_URL
        """
        if database_url is None:
            from core.config import Config
            database_url = Config.DATABASE_URL
        
        # Используем asyncpg для асинхронной работы с PostgreSQL
        self.db_url = database_url
        self.engine = create_async_engine(
            self.db_url,
            echo=False,  # Установить True для отладки SQL запросов
            future=True,
            pool_pre_ping=True,  # Проверка соединения перед использованием
            pool_size=10,  # Размер пула соединений
            max_overflow=20,  # Максимальное количество дополнительных соединений
            connect_args={
                "server_settings": {
                    "application_name": "steam_monitoring"
                },
                "command_timeout": 30,  # Таймаут 30 секунд для команд БД (увеличено для надежности)
            },
            pool_timeout=10,  # Таймаут 10 секунд для получения соединения из пула
            pool_recycle=3600,  # Переиспользование соединений каждый час
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def init_db(self):
        """Создает все таблицы в базе данных."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def close(self):
        """Закрывает соединение с БД."""
        await self.engine.dispose()
    
    async def get_session(self) -> AsyncSession:
        """Получает сессию для работы с БД."""
        return self.async_session()
    
    async def __aenter__(self):
        """Асинхронный контекстный менеджер - вход."""
        await self.init_db()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный контекстный менеджер - выход."""
        await self.close()

