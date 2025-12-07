"""
Обработчики Redis уведомлений Telegram бота.
"""
from datetime import datetime
from typing import Dict, Any
from loguru import logger

from core import FoundItem, MonitoringTask
from core.logger import get_task_logger, set_task_id


class RedisHandlers:
    """Обработчики Redis уведомлений."""
    
    def __init__(self, bot_manager):
        """
        Инициализация обработчиков Redis.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
    async def _handle_redis_notification(self, message: Dict[str, Any]):

        """

        Обрабатывает уведомление из Redis.


        Args:

            message: Словарь с данными уведомления

        """

        try:

            logger.info(f"📥 TelegramBot: Получено сообщение из Redis: type={message.get('type')}")


            if message.get("type") == "found_item":

                item_id = message.get("item_id")

                task_id = message.get("task_id")


                # Устанавливаем task_id в контексте и получаем логгер для задачи

                set_task_id(task_id)

                task_logger = get_task_logger(task_id)


                logger.info(f"🔔 TelegramBot: Обрабатываем уведомление о найденном предмете: item_id={item_id}, task_id={task_id}")

                task_logger.info(f"🔔 Обрабатываем уведомление о найденном предмете: item_id={item_id}")


                # Получаем данные из БД (используем данные из сообщения, чтобы избежать лишнего запроса)

                # Но все равно загружаем из БД для проверки и обновления статуса

                session = await self.bot.db_manager.get_session()

                try:

                    from sqlalchemy import select

                    logger.info(f"🔍 TelegramBot: Загружаем предмет {item_id} и задачу {task_id} из БД")

                    task_logger.debug(f"🔍 Загружаем предмет {item_id} и задачу {task_id} из БД")

                    found_item = await session.get(FoundItem, item_id)

                    task = await session.get(MonitoringTask, task_id)


                    if found_item and task:

                        logger.info(f"✅ TelegramBot: Данные загружены: предмет={found_item.item_name}, задача={task.name}")

                        task_logger.info(f"✅ Данные загружены: предмет={found_item.item_name}, задача={task.name}")


                        # ВАЖНО: Проверяем, не было ли уже отправлено уведомление (защита от дублей)

                        if found_item.notification_sent:

                            logger.warning(f"⚠️ TelegramBot: Уведомление для предмета {found_item.id} уже было отправлено, пропускаем (защита от дублей)")

                            task_logger.warning(f"⚠️ Уведомление для предмета {found_item.id} уже было отправлено, пропускаем")

                            return


                        # Отправляем уведомление СРАЗУ (до коммита в БД)

                        logger.info(f"📤 TelegramBot: Отправляем уведомление в Telegram (chat_id={self.bot.chat_id})")

                        task_logger.info(f"📤 Отправляем уведомление в Telegram")

                        try:

                            await self.bot.notification_handlers.send_notification(found_item, task)


                            # Только после успешной отправки отмечаем как отправленное

                            found_item.notification_sent = True

                            found_item.notification_sent_at = datetime.now()

                            await session.commit()

                            logger.info(f"✅ TelegramBot: Уведомление отправлено и отмечено в БД для предмета {found_item.id}")

                            task_logger.success(f"✅ Уведомление отправлено и отмечено в БД для предмета {found_item.id}")

                        except Exception as e:

                            logger.error(f"❌ TelegramBot: Не удалось отправить уведомление для предмета {found_item.id}: {e}")

                            task_logger.exception(f"❌ Не удалось отправить уведомление для предмета {found_item.id}: {e}")

                            # НЕ помечаем как отправленное, чтобы можно было повторить попытку

                            await session.rollback()

                            raise

                    else:

                        logger.error(f"❌ TelegramBot: Предмет {item_id} или задача {task_id} не найдены в БД (found_item={found_item is not None}, task={task is not None})")

                        task_logger.error(f"❌ Предмет {item_id} или задача {task_id} не найдены в БД")

                finally:

                    await session.close()

                    set_task_id(None)  # Очищаем task_id из контекста

            else:

                logger.debug(f"⏭️ TelegramBot: Пропускаем сообщение (не found_item): {message.get('type')}")

        except Exception as e:

            logger.error(f"❌ TelegramBot: Ошибка обработки уведомления из Redis: {e}")

            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")


