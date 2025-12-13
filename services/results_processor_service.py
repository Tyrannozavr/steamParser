"""
Сервис для обработки результатов парсинга.
Отвечает за сохранение результатов в БД и публикацию уведомлений.
Универсальный - работает с любыми фильтрами.
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import FoundItem, MonitoringTask
from services.redis_service import RedisService
from loguru import logger


class ResultsProcessorService:
    """Сервис для обработки результатов парсинга."""
    
    def __init__(
        self,
        db_session: AsyncSession,
        redis_service: Optional[RedisService] = None
    ):
        """
        Инициализация сервиса.
        
        Args:
            db_session: Сессия БД для работы с данными
            redis_service: Сервис Redis для публикации уведомлений
        """
        self.db_session = db_session
        self.redis_service = redis_service
    
    async def process_results(
        self,
        task: MonitoringTask,
        items: List[Dict[str, Any]],
        task_logger=None
    ) -> int:
        """
        Обрабатывает результаты парсинга: сохраняет в БД и публикует уведомления.
        
        Args:
            task: Задача мониторинга
            items: Список найденных предметов (результаты парсинга)
            task_logger: Логгер для задачи (опционально)
            
        Returns:
            Количество сохраненных предметов
        """
        if not items:
            logger.info(f"ℹ️ ResultsProcessor: Нет предметов для обработки для задачи {task.id}")
            if task_logger:
                task_logger.info(f"ℹ️ Нет предметов для обработки")
            return 0
        
        logger.info(f"📦 ResultsProcessor: Начинаем обработку {len(items)} предметов для задачи {task.id}")
        if task_logger:
            task_logger.info(f"📦 Начинаем обработку {len(items)} предметов")
        
        found_count = 0
        
        for item_idx, item in enumerate(items):
            logger.info(f"   🔄 Обрабатываем предмет {item_idx + 1}/{len(items)}")
            if task_logger:
                task_logger.info(f"   🔄 Обрабатываем предмет {item_idx + 1}/{len(items)}")
            
            # Получаем данные из parsed_data
            parsed_data = item.get('parsed_data', {})
            logger.debug(f"   DEBUG: parsed_data type={type(parsed_data)}, keys={list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'N/A'}")
            
            # Извлекаем цену
            price = parsed_data.get('item_price')
            if price is None:
                price_text = item.get("sell_price_text", "").replace("$", "").replace(",", "").strip()
                try:
                    price = float(price_text)
                    logger.warning(f"   ⚠️ Цена не найдена в parsed_data, используем цену из API: ${price:.2f}")
                except (ValueError, AttributeError):
                    price = 0.0
            
            # Извлекаем название
            item_name = item.get('name', task.item_name)
            
            # Извлекаем listing_id
            listing_id = parsed_data.get('listing_id') if isinstance(parsed_data, dict) else None
            if not listing_id:
                listing_id = item.get('listingid')
            
            logger.info(f"💾 Проверяем сохранение предмета: {item_name} (${price:.2f}), listing_id={listing_id}")
            
            # Проверяем дубликаты по listing_id
            # ВАЖНО: Всегда приводим listing_id к строке для корректного сравнения
            if listing_id:
                listing_id_str = str(listing_id)
                all_task_items = await self.db_session.execute(
                    select(FoundItem).where(FoundItem.task_id == task.id)
                )
                found_duplicate = False
                for existing_item in all_task_items.scalars().all():
                    try:
                        existing_data = json.loads(existing_item.item_data_json)
                        existing_listing_id = existing_data.get('listing_id')
                        # ВАЖНО: Приводим к строке для корректного сравнения
                        if existing_listing_id and str(existing_listing_id) == listing_id_str:
                            logger.info(f"   ⏭️ Предмет с listing_id={listing_id_str} уже существует в БД (ID={existing_item.id}), пропускаем")
                            found_duplicate = True
                            break
                    except (json.JSONDecodeError, AttributeError):
                        pass
                
                if found_duplicate:
                    continue
            
            # Дополнительная проверка по комбинации task_id + item_name + price + listing_id
            # Для брелков и других предметов с listing_id это более точная проверка
            if listing_id:
                existing_query = select(FoundItem).where(
                    FoundItem.task_id == task.id,
                    FoundItem.item_name == item_name,
                    FoundItem.price == price
                )
                existing_items = await self.db_session.execute(existing_query)
                found_duplicate = False
                for existing_item in existing_items.scalars().all():
                    try:
                        existing_data = json.loads(existing_item.item_data_json)
                        existing_listing_id = existing_data.get('listing_id')
                        # Если у существующего предмета нет listing_id или он отличается - это разные лоты
                        if existing_listing_id and str(existing_listing_id) == str(listing_id):
                            logger.info(f"   ⏭️ Предмет с listing_id={listing_id} уже существует в БД (ID={existing_item.id}), пропускаем")
                            found_duplicate = True
                            break
                    except (json.JSONDecodeError, AttributeError):
                        pass
                if found_duplicate:
                    continue
            else:
                # Если нет listing_id, проверяем только по task_id + item_name + price
                existing_query = select(FoundItem).where(
                    FoundItem.task_id == task.id,
                    FoundItem.item_name == item_name,
                    FoundItem.price == price
                )
                existing = await self.db_session.execute(existing_query.limit(1))
                if existing.scalar_one_or_none():
                    logger.info(f"   ⏭️ Предмет уже существует в БД, пропускаем: {item_name} (${price:.2f})")
                    continue
            
            # Убеждаемся, что listing_id сохранен в parsed_data
            if listing_id and isinstance(parsed_data, dict):
                parsed_data['listing_id'] = listing_id
            
            # Преобразуем parsed_data в JSON-сериализуемый формат
            serialized_data = self._serialize_for_json(parsed_data)
            
            # Создаем FoundItem
            found_item = FoundItem(
                task_id=task.id,
                item_name=item_name,
                price=price,
                item_data_json=json.dumps(serialized_data, ensure_ascii=False),
                market_url=item.get('asset_description', {}).get('market_hash_name'),
                notification_sent=False
            )
            
            try:
                self.db_session.add(found_item)
                found_count += 1
                logger.info(f"   ✅ Предмет добавлен для сохранения: {item_name} (${price:.2f})")
                if task_logger:
                    task_logger.info(f"   ✅ Предмет добавлен для сохранения: {item_name} (${price:.2f})")
            except Exception as add_error:
                logger.error(f"   ❌ Ошибка при добавлении предмета {item_name} в сессию: {add_error}")
                if task_logger:
                    task_logger.error(f"   ❌ Ошибка при добавлении предмета {item_name} в сессию: {add_error}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                if task_logger:
                    task_logger.error(f"   Traceback: {traceback.format_exc()}")
        
        logger.info(f"🔍 DEBUG: Обработано {len(items)} предметов, добавлено в сессию: {found_count}")
        if task_logger:
            task_logger.info(f"🔍 DEBUG: Обработано {len(items)} предметов, добавлено в сессию: {found_count}")
        
        # Обновляем счетчик найденных предметов в задаче
        try:
            await self.db_session.refresh(task)
        except Exception as refresh_error:
            logger.warning(f"⚠️ Не удалось обновить задачу {task.id} перед обновлением счетчика: {refresh_error}")
            try:
                await self.db_session.rollback()
            except Exception:
                pass
            task = await self.db_session.get(MonitoringTask, task.id)
            if not task:
                logger.error(f"❌ Задача {task.id} не найдена в БД")
                return found_count
        
        task.items_found += found_count
        
        # ВАЖНО: Обновляем next_check, если он еще не установлен или в прошлом
        # Это гарантирует, что задача будет запускаться повторно через заданный интервал
        from datetime import datetime, timedelta
        if not task.next_check or task.next_check < datetime.now():
            task.next_check = datetime.now() + timedelta(seconds=task.check_interval)
            logger.info(f"⏰ ResultsProcessor: Установлена следующая проверка для задачи {task.id}: {task.next_check.strftime('%Y-%m-%d %H:%M:%S')}")
            if task_logger:
                task_logger.info(f"⏰ Следующая проверка в {task.next_check.strftime('%Y-%m-%d %H:%M:%S')}")
        
        logger.info(f"✅ ResultsProcessor: Сохранено {found_count} предметов для задачи {task.id}")
        if task_logger:
            task_logger.success(f"✅ Сохранено {found_count} предметов")
        
        # Сохраняем изменения в БД
        try:
            await self.db_session.commit()
            logger.info(f"📊 ResultsProcessor: Статистика задачи {task.id} обновлена: проверок={task.total_checks}, найдено={task.items_found}, next_check={task.next_check.strftime('%Y-%m-%d %H:%M:%S') if task.next_check else 'не установлен'}")
            if task_logger:
                task_logger.info(f"📊 Статистика обновлена: проверок={task.total_checks}, найдено={task.items_found}")
        except Exception as commit_error:
            logger.error(f"❌ ResultsProcessor: Ошибка при сохранении статистики задачи {task.id}: {commit_error}")
            if task_logger:
                task_logger.error(f"❌ Ошибка при сохранении статистики: {commit_error}")
            try:
                await self.db_session.rollback()
                logger.debug("✅ Транзакция откачена после ошибки commit")
            except Exception as rollback_error:
                logger.error(f"❌ Ошибка при откате транзакции: {rollback_error}")
            return found_count
        
        # Публикуем уведомления в Redis
        if found_count > 0 and self.redis_service:
            await self._publish_notifications(task, found_count)
        
        return found_count
    
    async def _publish_notifications(self, task: MonitoringTask, found_count: int):
        """
        Публикует уведомления о найденных предметах в Redis.
        
        Args:
            task: Задача мониторинга
            found_count: Количество новых предметов
        """
        # Получаем новые предметы
        found_items_result = await self.db_session.execute(
            select(FoundItem)
            .where(
                (FoundItem.task_id == task.id) &
                (FoundItem.notification_sent == False)
            )
            .order_by(FoundItem.found_at.desc())
            .limit(found_count)
        )
        found_items = found_items_result.scalars().all()
        
        logger.info(f"📤 ResultsProcessor: Публикуем {len(found_items)} уведомлений в Redis канал 'found_items'")
        for found_item in found_items:
            # ВАЖНО: Проверяем еще раз, что уведомление не было отправлено (защита от race condition)
            await self.db_session.refresh(found_item)
            if found_item.notification_sent:
                logger.warning(f"⚠️ ResultsProcessor: Уведомление для предмета {found_item.id} уже было отправлено, пропускаем (защита от дублей)")
                continue
            
            notification_data = {
                "type": "found_item",
                "item_id": found_item.id,
                "task_id": task.id,
                "item_name": found_item.item_name,
                "price": found_item.price,
                "market_url": found_item.market_url,
                "item_data_json": found_item.item_data_json,
                "task_name": task.name
            }
            logger.info(f"📤 ResultsProcessor: Публикуем уведомление для предмета {found_item.id} ({found_item.item_name}, ${found_item.price:.2f})")
            
            # ВАЖНО: Обновляем флаг notification_sent СРАЗУ после публикации (до отправки в Telegram)
            # Это предотвращает дублирование уведомлений при повторной обработке сообщения из Redis
            try:
                found_item.notification_sent = True
                found_item.notification_sent_at = datetime.now()
                await self.db_session.commit()
                logger.debug(f"✅ ResultsProcessor: Флаг notification_sent установлен для предмета {found_item.id}")
            except Exception as commit_error:
                logger.warning(f"⚠️ ResultsProcessor: Не удалось обновить notification_sent для предмета {found_item.id}: {commit_error}")
                try:
                    await self.db_session.rollback()
                except Exception:
                    pass
            
            # Публикуем уведомление в Redis
            await self.redis_service.publish("found_items", notification_data)
            logger.info(f"✅ ResultsProcessor: Уведомление для предмета {found_item.id} опубликовано")
    
    def _serialize_for_json(self, obj: Any) -> Any:
        """
        Рекурсивно преобразует Pydantic модели и другие объекты в JSON-сериализуемый формат.
        
        Args:
            obj: Объект для сериализации
            
        Returns:
            Сериализуемый объект
        """
        if hasattr(obj, 'model_dump'):
            # Pydantic v2
            return obj.model_dump()
        elif hasattr(obj, 'dict'):
            # Pydantic v1
            return obj.dict()
        elif isinstance(obj, dict):
            return {k: self._serialize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_json(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            # Для других типов пытаемся преобразовать в строку
            return str(obj)

