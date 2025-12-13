"""
Обработчики команд Telegram бота.
"""
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from telegram.keyboards import get_main_keyboard


class CommandHandlers:
    """Обработчики команд бота."""
    
    def __init__(self, bot_manager):
        """
        Инициализация обработчиков команд.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
    async def cmd_start(self, message: Message):
        """Обработчик команды /start."""
        logger.info(f"🔍 DEBUG: Обработка команды /start от пользователя {message.from_user.id}")
        
        # Inline клавиатура для быстрых действий
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статус", callback_data="status"),
                InlineKeyboardButton(text="📋 Задачи", callback_data="tasks")
            ],
            [
                InlineKeyboardButton(text="🔌 Прокси", callback_data="proxies"),
                InlineKeyboardButton(text="🔍 Найдено", callback_data="found")
            ],
            [
                InlineKeyboardButton(text="➕ Добавить прокси", callback_data="add_proxy"),
                InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task")
            ],
            [
                InlineKeyboardButton(text="🔍 Проверить прокси", callback_data="check_proxies"),
                InlineKeyboardButton(text="❓ Помощь", callback_data="help")
            ]
        ])
        
        logger.info(f"🔍 DEBUG: Создана inline клавиатура с {len(inline_keyboard.inline_keyboard)} рядами")
        logger.info(f"🔍 DEBUG: Кнопка 'Проверить прокси' в ряду 4: {inline_keyboard.inline_keyboard[3][0].text}")
        
        # Постоянная клавиатура (ReplyKeyboardMarkup)
        main_keyboard = get_main_keyboard()
        logger.info(f"🔍 DEBUG: Создана основная клавиатура с {len(main_keyboard.keyboard)} рядами")
        
        try:
            await message.answer(
                "🤖 <b>Бот для управления мониторингом Steam Market</b>\n\n"
                "Используйте кнопки ниже для быстрого доступа к командам.\n"
                "Или выберите действие через inline-кнопки:",
                reply_markup=main_keyboard,
                parse_mode="HTML"
            )
            logger.info("🔍 DEBUG: Первое сообщение с основной клавиатурой отправлено успешно")
            
            # Отправляем также inline-кнопки
            await message.answer(
                "Выберите действие:",
                reply_markup=inline_keyboard,
                parse_mode="HTML"
            )
            logger.info("🔍 DEBUG: Второе сообщение с inline клавиатурой отправлено успешно")
            
        except Exception as e:
            logger.error(f"❌ DEBUG: Ошибка при отправке сообщений в cmd_start: {e}")
            raise
    
    async def cmd_help(self, message: Message):
        """Обработчик команды /help."""
        help_text = """
📋 <b>Доступные команды:</b>

<b>Информация:</b>
/status - Статистика системы
/tasks - Список задач мониторинга
/proxies - Список прокси
/found - Последние найденные предметы

<b>Управление прокси:</b>
/add_proxy - Добавить прокси
/delete_proxy [id] - Удалить прокси
/cleanup_duplicates - Очистить дубликаты прокси
/check_proxies - Проверить все прокси на работоспособность

<b>Управление задачами:</b>
/add_task - Добавить задачу мониторинга
/delete_task [id] - Удалить задачу
/toggle_task [id] - Включить/выключить задачу

Используйте /help для справки
        """
        await message.answer(help_text, parse_mode="HTML")
    
    async def cmd_status(self, message: Message):
        """Показывает статус системы."""
        stats = await self.bot.monitoring_service.get_statistics()
        
        # ВАЖНО: Используем новую сессию БД для получения статистики прокси,
        # чтобы гарантированно увидеть последние изменения (blocked_until)
        session = await self.bot.db_manager.get_session()
        try:
            # Передаем новую сессию в get_proxy_stats для чтения актуальных данных
            proxy_stats = await self.bot.proxy_manager.get_proxy_stats(db_session=session)
            from sqlalchemy import select, func
            from core import Proxy
            
            # Получаем статистику по успешным/неуспешным запросам
            total_success = sum(p.get('success_count', 0) for p in proxy_stats.get('proxies', []))
            total_fail = sum(p.get('fail_count', 0) for p in proxy_stats.get('proxies', []))
            
            # Заблокированные прокси (rate limited) - активные, но заблокированные Steam
            active_blocked = proxy_stats.get('active_blocked', 0)
            total_blocked = proxy_stats.get('blocked', 0)
            
            # Работающие прокси = активные минус заблокированные
            working_proxies = proxy_stats['active'] - active_blocked
            
            text = f"""
📊 <b>Статус системы:</b>

<b>Мониторинг:</b>
• Всего задач: {stats['total_tasks']}
• Активных: {stats['active_tasks']}
• Запущенных: {stats['running_tasks']}

<b>Прокси:</b>
• Всего: {proxy_stats['total']}
• Активных: {proxy_stats['active']}
• ⚠️ Заблокированных Steam (rate limited): {active_blocked}
• ✅ Работающих: {working_proxies}
• Неактивных: {proxy_stats['inactive']}
• Успешных запросов: {total_success}
• Ошибок: {total_fail}
• Успешность: {(total_success / (total_success + total_fail) * 100) if (total_success + total_fail) > 0 else 0:.1f}%
        """
        except Exception as e:
            logger.error(f"Ошибка при получении статистики прокси: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # В случае ошибки пытаемся получить базовую статистику
            try:
                proxy_stats = await self.bot.proxy_manager.get_proxy_stats()
                active_blocked = proxy_stats.get('active_blocked', 0)
            except:
                active_blocked = 0
                proxy_stats = {'total': 0, 'active': 0, 'inactive': 0}
            
            text = f"""
📊 <b>Статус системы:</b>

<b>Мониторинг:</b>
• Всего задач: {stats['total_tasks']}
• Активных: {stats['active_tasks']}
• Запущенных: {stats['running_tasks']}

<b>Прокси:</b>
• Всего: {proxy_stats['total']}
• Активных: {proxy_stats['active']}
• ⚠️ Заблокированных Steam (rate limited): {active_blocked}
• Неактивных: {proxy_stats['inactive']}
• <i>Ошибка при получении полной статистики</i>
        """
        finally:
            await session.close()
        
        await message.answer(text, parse_mode="HTML")
    
    async def cmd_tasks(self, message: Message):
        """Показывает список задач."""
        await self.bot._send_tasks(message)
    
    async def cmd_proxies(self, message: Message):
        """Показывает список прокси с детальной статистикой."""
        await self.bot._send_proxies(message)
    
    async def cmd_found(self, message: Message):
        """Показывает последние найденные предметы."""
        session = await self.bot.db_manager.get_session()
        try:
            from sqlalchemy import select, desc
            from core import FoundItem
            result = await session.execute(
                select(FoundItem)
                .order_by(desc(FoundItem.found_at))
                .limit(10)
            )
            items = list(result.scalars().all())
            
            if not items:
                await message.answer("🔍 Найденных предметов пока нет")
                return
            
            text = "🔍 <b>Последние найденные предметы:</b>\n\n"
            for item in items:
                text += f"💰 <b>{item.item_name}</b> - ${item.price:.2f}\n"
                text += f"   Найдено: {item.found_at.strftime('%Y-%m-%d %H:%M')}\n"
                if item.market_url:
                    text += f"   [Steam Market](https://steamcommunity.com/market/listings/730/{item.market_url})\n"
                text += "\n"
            
            await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
        finally:
            await session.close()
    
    async def cmd_check_proxies(self, message: Message):
        """Проверяет все прокси на работоспособность параллельно и обновляет статусы в БД."""
        await message.answer("🔍 Начинаю параллельную проверку прокси... Это может занять некоторое время.")
        
        # ВАЖНО: Используем метод ProxyManager, который обновляет blocked_until в БД
        if not self.bot.proxy_manager:
            session = await self.bot.db_manager.get_session()
            from services import ProxyManager
            proxy_manager = ProxyManager(session, redis_service=self.bot.redis_service)
        else:
            proxy_manager = self.bot.proxy_manager
        
        try:
            # Вызываем проверку с обновлением статусов в БД
            # update_redis_status=True обновляет blocked_until в БД для rate_limited прокси
            check_result = await proxy_manager.check_all_proxies_parallel(
                max_concurrent=20,
                update_redis_status=True  # ВАЖНО: Обновляет blocked_until в БД
            )
            
            if not check_result or check_result.get("total", 0) == 0:
                await message.answer("❌ Прокси не найдены в базе данных")
                return
            
            # Обновляем статус-сообщение
            await message.answer("✅ Проверка завершена! Обрабатываю результаты...")
            
            # Получаем детальную информацию о прокси из БД для формирования отчета
            from sqlalchemy import select
            from core import Proxy
            session = await self.bot.db_manager.get_session()
            try:
                result = await session.execute(select(Proxy).order_by(Proxy.id))
                all_proxies = {p.id: p for p in result.scalars().all()}
            finally:
                await session.close()
            
            # Формируем итоговый отчет на основе результатов проверки
            working_count = check_result.get("working", 0)
            rate_limited_count = check_result.get("rate_limited", 0)
            error_count = check_result.get("error", 0)
            total_count = check_result.get("total", 0)
            results = check_result.get("results", [])
            
            # Подсчитываем активные прокси по статусам
            active_ok = 0
            active_rate_limited = 0
            active_error = 0
            inactive_ok = 0
            inactive_error = 0
            
            for r in results:
                proxy_id = r.get("proxy_id")
                if proxy_id and proxy_id in all_proxies:
                    proxy = all_proxies[proxy_id]
                    status = r.get("status", "error")
                    if proxy.is_active:
                        if status == "ok":
                            active_ok += 1
                        elif status == "rate_limited":
                            active_rate_limited += 1
                        else:
                            active_error += 1
                    else:
                        if status == "ok":
                            inactive_ok += 1
                        else:
                            inactive_error += 1
            
            text = f"📊 <b>Результаты проверки прокси (Steam API):</b>\n\n"
            text += f"📋 Всего прокси: {total_count}\n"
            text += f"✅ Активных и работающих: {active_ok}\n"
            text += f"⚠️ Активных, но rate limited: {active_rate_limited}\n"
            text += f"❌ Активных, но не работающих: {active_error}\n"
            text += f"✅ Неактивных, но работающих: {inactive_ok}\n"
            text += f"❌ Неактивных и не работающих: {inactive_error}\n\n"
            
            if active_rate_limited > 0:
                text += f"<b>⚠️ Активные прокси с rate limit:</b>\n"
                for r in results:
                    if r.get("status") == "rate_limited" and r.get("proxy_id") in all_proxies:
                        proxy = all_proxies[r.get("proxy_id")]
                        if proxy.is_active:
                            text += f"   ID={proxy.id}: Steam блокирует (429)\n"
                text += "\n"
            
            if active_error > 0:
                text += f"<b>❌ Активные прокси, которые не работают:</b>\n"
                for r in results:
                    if r.get("status") == "error" and r.get("proxy_id") in all_proxies:
                        proxy = all_proxies[r.get("proxy_id")]
                        if proxy.is_active:
                            error_msg = r.get("error", "Unknown error")
                            text += f"   ID={proxy.id}: {error_msg[:50]}\n"
            
            await message.answer(text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка при проверке прокси: {str(e)}")
            logger.error(f"Ошибка проверки прокси: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
    
    async def handle_keyboard_button(self, message: Message, state: FSMContext):
        """Обрабатывает нажатия на кнопки постоянной клавиатуры."""
        text = message.text
        
        if text == "📊 Статус":
            await self.cmd_status(message)
        elif text == "📋 Задачи":
            await self.cmd_tasks(message)
        elif text == "🔌 Прокси":
            await self.cmd_proxies(message)
        elif text == "🔍 Найдено":
            await self.cmd_found(message)
        elif text == "➕ Добавить задачу":
            await self.bot.cmd_add_task(message, state)
        elif text == "➕ Добавить прокси":
            await self.bot.cmd_add_proxy(message, state)
        elif text == "❓ Помощь":
            await self.cmd_help(message)
        elif text == "🔍 Проверить прокси":
            await self.bot.cmd_check_proxies(message)

