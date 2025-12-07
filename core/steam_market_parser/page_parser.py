"""
Модуль для парсинга страниц.
Отвечает за формирование пула URL'ов и обработку страниц.
"""
from typing import Optional, Dict, Any, List

from ..models import SearchFilters
from .url_pool_builder import build_url_pool
from .url_pool_processor import process_url_pool
from .parallel_page_parser import parse_all_pages_parallel


class PageParser:
    """
    Класс для парсинга страниц.
    Принимает ссылку на парсер для использования его методов.
    """
    
    def __init__(self, parser, listing_parser=None):
        """
        Инициализация парсера страниц.
        
        Args:
            parser: Экземпляр SteamMarketParser для использования его методов
            listing_parser: Экземпляр ListingParser для парсинга лотов
        """
        self.parser = parser
        self.listing_parser = listing_parser

    async def build_url_pool(
        self,
        filters: SearchFilters,
        exact_hash_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Формирует пул URL'ов для задачи.
        Делегирует выполнение модулю url_pool_builder.
        """
        return await build_url_pool(self.parser, filters, exact_hash_name)

    async def process_url_pool(
        self,
        url_pool: List[Dict[str, Any]],
        filters: SearchFilters,
        task = None,
        db_session = None,
        redis_service = None
    ) -> Dict[str, Any]:
        """
        Обрабатывает все URL'ы из пула последовательно.
        Делегирует выполнение модулю url_pool_processor.
        
        Args:
            url_pool: Пул URL'ов для обработки
            filters: Параметры поиска
            task: Задача мониторинга (для сохранения результатов)
            db_session: Сессия БД (для сохранения результатов)
            redis_service: Сервис Redis (для отправки уведомлений)
        """
        from .listing_parser import ListingParser
        if not self.listing_parser:
            self.listing_parser = ListingParser(self.parser)
        return await process_url_pool(
            self.parser,
            self.listing_parser,
            url_pool,
            filters,
            task=task,
            db_session=db_session,
            redis_service=redis_service
        )

    async def parse_all_pages_parallel(
        self,
        filters: SearchFilters,
        params: Dict[str, Any],
        items: List[Dict[str, Any]],
        total_count: int,
        current_start: int,
        max_per_request: int,
        active_proxies_count: int,
        max_retries: int,
        retry_delay: float,
        task_logger=None,
        total_pages: int = 0
    ):
        """
        Параллельный парсинг всех страниц с распределением запросов между прокси.
        Делегирует выполнение модулю parallel_page_parser.
        """
        await parse_all_pages_parallel(
            self.parser,
            filters,
            params,
            items,
            total_count,
            current_start,
            max_per_request,
            active_proxies_count,
            max_retries,
            retry_delay,
            task_logger,
            total_pages
        )

    async def _parse_item_page(self, appid: int, hash_name: str, listing_id: Optional[str] = None, target_patterns: Optional[set] = None):
        """
        Парсит страницу предмета и извлекает детальные данные.
        Делегирует выполнение модулю item_page_parser.
        """
        from .item_page_parser import parse_item_page
        return await parse_item_page(self.parser, appid, hash_name, listing_id, target_patterns)

