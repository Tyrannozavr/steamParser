"""
Хранение результатов парсинга в Redis для оптимизации производительности.
Вместо блокировки на общий список, каждый воркер сохраняет результаты в Redis.
В конце все результаты собираются и обрабатываются batch'ом.
"""
import json
from typing import List, Optional, Dict, Any
from loguru import logger

from ..models import ParsedItemData
from services.redis_service import RedisService


def serialize_parsed_item(parsed_data: ParsedItemData) -> Dict[str, Any]:
    """
    Сериализует ParsedItemData в словарь для хранения в Redis.
    
    Args:
        parsed_data: Данные парсинга
        
    Returns:
        Словарь с сериализованными данными
    """
    return {
        'float_value': parsed_data.float_value,
        'pattern': parsed_data.pattern,
        'stickers': [s.model_dump() if hasattr(s, 'model_dump') else s.__dict__ for s in parsed_data.stickers],
        'total_stickers_price': parsed_data.total_stickers_price,
        'item_name': parsed_data.item_name,
        'item_price': parsed_data.item_price,
        'inspect_links': parsed_data.inspect_links,
        'item_type': parsed_data.item_type,
        'is_stattrak': parsed_data.is_stattrak,
        'listing_id': parsed_data.listing_id
    }


def deserialize_parsed_item(data: Dict[str, Any]) -> ParsedItemData:
    """
    Десериализует словарь обратно в ParsedItemData.
    
    Args:
        data: Словарь с данными
        
    Returns:
        ParsedItemData объект
    """
    from ..models import StickerInfo
    
    stickers = []
    for s_data in data.get('stickers', []):
        if isinstance(s_data, dict):
            stickers.append(StickerInfo(**s_data))
        else:
            stickers.append(s_data)
    
    return ParsedItemData(
        float_value=data.get('float_value'),
        pattern=data.get('pattern'),
        stickers=stickers,
        total_stickers_price=data.get('total_stickers_price', 0.0),
        item_name=data.get('item_name'),
        item_price=data.get('item_price'),
        inspect_links=data.get('inspect_links', []),
        item_type=data.get('item_type'),
        is_stattrak=data.get('is_stattrak', False),
        listing_id=data.get('listing_id')
    )


async def save_page_results_to_redis(
    redis_service: RedisService,
    task_id: int,
    page_num: int,
    page_results: List[ParsedItemData],
    log_func
) -> bool:
    """
    Сохраняет результаты страницы в Redis.
    
    Args:
        redis_service: Сервис Redis
        task_id: ID задачи
        page_num: Номер страницы
        page_results: Список результатов страницы
        log_func: Функция для логирования
        
    Returns:
        True если успешно, False иначе
    """
    if not redis_service or not redis_service.is_connected():
        log_func("error", f"    ❌ Redis недоступен для сохранения результатов страницы {page_num}")
        return False
    
    try:
        # Сериализуем результаты
        serialized_results = [serialize_parsed_item(item) for item in page_results]
        
        # Сохраняем в Redis List
        redis_key = f"parsing:results:task_{task_id}:page_{page_num}"
        # Используем JSON для каждого элемента (более надежно)
        # Сохраняем все элементы одним вызовом для эффективности
        if serialized_results:
            items_json = [json.dumps(item_data, ensure_ascii=False) for item_data in serialized_results]
            await redis_service.lpush(redis_key, *items_json)
        
        # Устанавливаем TTL (1 час на случай, если что-то пойдет не так)
        await redis_service.expire(redis_key, 3600)
        
        log_func("debug", f"    💾 Воркер: Сохранено {len(page_results)} результатов страницы {page_num} в Redis")
        return True
    except Exception as e:
        log_func("error", f"    ❌ Ошибка при сохранении результатов страницы {page_num} в Redis: {e}")
        return False


async def get_all_results_from_redis(
    redis_service: RedisService,
    task_id: int,
    total_pages: int,
    log_func
) -> List[ParsedItemData]:
    """
    Собирает все результаты из Redis для всех страниц.
    
    Args:
        redis_service: Сервис Redis
        task_id: ID задачи
        total_pages: Общее количество страниц
        log_func: Функция для логирования
        
    Returns:
        Список всех результатов в правильном порядке
    """
    all_results = []
    
    if not redis_service or not redis_service.is_connected():
        log_func("error", "❌ Redis недоступен для получения результатов")
        return all_results
    
    try:
        for page_num in range(1, total_pages + 1):
            redis_key = f"parsing:results:task_{task_id}:page_{page_num}"
            
            # Получаем все элементы из списка
            items_json = await redis_service.lrange(redis_key, 0, -1)
            
            if items_json:
                page_results = []
                for item_json in items_json:
                    try:
                        item_data = json.loads(item_json)
                        parsed_item = deserialize_parsed_item(item_data)
                        page_results.append(parsed_item)
                    except Exception as e:
                        log_func("warning", f"    ⚠️ Ошибка при десериализации результата страницы {page_num}: {e}")
                        continue
                
                all_results.extend(page_results)
                log_func("debug", f"    📥 Загружено {len(page_results)} результатов со страницы {page_num} из Redis")
        
        log_func("info", f"📊 Всего загружено {len(all_results)} результатов из Redis")
        return all_results
    except Exception as e:
        log_func("error", f"❌ Ошибка при получении результатов из Redis: {e}")
        return all_results


async def cleanup_redis_results(
    redis_service: RedisService,
    task_id: int,
    total_pages: int,
    log_func
) -> None:
    """
    Очищает результаты из Redis после обработки.
    
    Args:
        redis_service: Сервис Redis
        task_id: ID задачи
        total_pages: Общее количество страниц
        log_func: Функция для логирования
    """
    if not redis_service or not redis_service.is_connected():
        return
    
    try:
        deleted_count = 0
        for page_num in range(1, total_pages + 1):
            redis_key = f"parsing:results:task_{task_id}:page_{page_num}"
            deleted = await redis_service.delete(redis_key)
            if deleted:
                deleted_count += 1
        
        log_func("debug", f"🗑️ Очищено {deleted_count} ключей результатов из Redis")
    except Exception as e:
        log_func("warning", f"⚠️ Ошибка при очистке результатов из Redis: {e}")

