"""
Telegram бот для управления настройками мониторинга Steam Market.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

import sys
from pathlib import Path

# Добавляем корневую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import DatabaseManager, MonitoringTask, Proxy, FoundItem, SearchFilters, FloatRange, PatternList, StickersFilter
from core.logger import get_task_logger, set_task_id
from services import ProxyManager, MonitoringService
from services.redis_service import RedisService
from services.parser_api_client import ParserAPIClient

from telegram.states import BotStates
from telegram.keyboards import get_main_keyboard, get_skip_keyboard
from telegram.handlers.commands import CommandHandlers
from telegram.handlers.proxy_handlers import ProxyHandlers
from telegram.handlers.task_handlers import TaskHandlers
from telegram.handlers.callback_handlers import CallbackHandlers
from telegram.handlers.message_senders import MessageSenders
from telegram.handlers.notifications import NotificationHandlers
from telegram.handlers.redis_handlers import RedisHandlers


class TelegramBotManager:
    """Менеджер Telegram бота для управления настройками."""
    
    def __init__(
        self,
        token: str,
        chat_id: str,
        db_manager: DatabaseManager,
        proxy_manager: ProxyManager,
        monitoring_service: MonitoringService,
        redis_service: Optional[RedisService] = None
    ):
        """
        Инициализация бота.
        
        Args:
            token: Токен Telegram бота
            chat_id: ID чата для уведомлений
            db_manager: Менеджер БД
            proxy_manager: Менеджер прокси
            monitoring_service: Сервис мониторинга
            redis_service: Сервис Redis для получения уведомлений (опционально)
        """
        self.bot = Bot(token=token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.chat_id = chat_id
        self.db_manager = db_manager
        self.proxy_manager = proxy_manager
        self.monitoring_service = monitoring_service
        self.redis_service = redis_service
        
        # Инициализируем клиент Parser API
        if redis_service:
            self.parser_client = ParserAPIClient(redis_service=redis_service)
            logger.info("✅ TelegramBot: ParserAPIClient инициализирован")
        else:
            self.parser_client = None
            logger.warning("⚠️ TelegramBot: ParserAPIClient не инициализирован (redis_service=None)")
        
        # CurrencyService теперь используется через ParserAPIClient (HTTP запросы к parser-api)
        logger.info("✅ TelegramBot: Курсы валют будут запрашиваться через ParserAPIClient")
        
        # Инициализируем обработчики
        self.command_handlers = CommandHandlers(self)
        self.proxy_handlers = ProxyHandlers(self)
        self.task_handlers = TaskHandlers(self)
        self.callback_handlers = CallbackHandlers(self)
        self.message_senders = MessageSenders(self)
        self.notification_handlers = NotificationHandlers(self)
        self.redis_handlers = RedisHandlers(self)
        
        # Регистрируем обработчики
        self._register_handlers()
    
    def _register_handlers(self):
        """Регистрирует все обработчики команд."""
        
        # Команды
        self.dp.message.register(self.command_handlers.cmd_start, Command("start"))
        self.dp.message.register(self.command_handlers.cmd_help, Command("help"))
        self.dp.message.register(self.command_handlers.cmd_status, Command("status"))
        self.dp.message.register(self.command_handlers.cmd_tasks, Command("tasks"))
        self.dp.message.register(self.command_handlers.cmd_proxies, Command("proxies"))
        self.dp.message.register(self.command_handlers.cmd_found, Command("found"))
        self.dp.message.register(self.command_handlers.cmd_check_proxies, Command("check_proxies"))
        
        # Обработка нажатий на кнопки клавиатуры
        self.dp.message.register(self.command_handlers.handle_keyboard_button, F.text.in_([
            "📊 Статус", "📋 Задачи", "🔌 Прокси", "🔍 Найдено",
            "➕ Добавить задачу", "➕ Добавить прокси", "❓ Помощь", "🔍 Проверить прокси"
        ]))
        
        # Управление прокси
        self.dp.message.register(self.proxy_handlers.cmd_add_proxy, Command("add_proxy"))
        self.dp.message.register(self.proxy_handlers.cmd_delete_proxy, Command("delete_proxy"))
        self.dp.message.register(self.proxy_handlers.cmd_cleanup_duplicates, Command("cleanup_duplicates"))
        
        # Управление задачами
        self.dp.message.register(self.task_handlers.cmd_add_task, Command("add_task"))
        self.dp.message.register(self.task_handlers.cmd_delete_task, Command("delete_task"))
        self.dp.message.register(self.task_handlers.cmd_toggle_task, Command("toggle_task"))
        
        # Callback обработчики
        self.dp.callback_query.register(self.callback_handlers.handle_callback)
        
        # FSM обработчики
        self.dp.message.register(self.proxy_handlers.process_proxy_input, BotStates.waiting_for_proxy)
        self.dp.message.register(self.task_handlers.process_task_name, BotStates.waiting_for_task_name)
        self.dp.message.register(self.task_handlers.process_item_name, BotStates.waiting_for_item_name)
        self.dp.message.register(self.task_handlers.process_wear_selection, BotStates.waiting_for_wear_selection)
        self.dp.message.register(self.task_handlers.process_max_price, BotStates.waiting_for_max_price)
        self.dp.message.register(self.task_handlers.process_float_min, BotStates.waiting_for_float_min)
        self.dp.message.register(self.task_handlers.process_float_max, BotStates.waiting_for_float_max)
        self.dp.message.register(self.task_handlers.process_patterns, BotStates.waiting_for_patterns)
        self.dp.message.register(self.task_handlers.process_item_type, BotStates.waiting_for_item_type)
        self.dp.message.register(self.task_handlers.process_stickers_overpay, BotStates.waiting_for_stickers_overpay)
        self.dp.message.register(self.task_handlers.process_stickers_min_price, BotStates.waiting_for_stickers_min_price)
    
    def _get_main_keyboard(self) -> ReplyKeyboardMarkup:
        """Создает основную клавиатуру с частыми командами."""
        return get_main_keyboard()
    
    def _get_skip_keyboard(self) -> InlineKeyboardMarkup:
        """Создает inline-клавиатуру с кнопкой 'Skip'."""
        return get_skip_keyboard()
    
    # Команды делегируются в модули
    async def cmd_start(self, message: Message):
        await self.command_handlers.cmd_start(message)
    
    async def handle_keyboard_button(self, message: Message, state: FSMContext):
        await self.command_handlers.handle_keyboard_button(message, state)
    
    async def cmd_help(self, message: Message):
        await self.command_handlers.cmd_help(message)
    
    async def cmd_status(self, message: Message):
        await self.command_handlers.cmd_status(message)
    
    async def cmd_tasks(self, message: Message):
        """Показывает список задач."""
        await self.message_senders._send_tasks(message)
    
    async def cmd_proxies(self, message: Message):
        """Показывает список прокси с детальной статистикой."""
        await self.message_senders._send_proxies(message)
    
    async def cmd_check_proxies(self, message: Message):
        await self.command_handlers.cmd_check_proxies(message)
    
    async def cmd_found(self, message: Message):
        await self.command_handlers.cmd_found(message)
    
    async def cmd_add_proxy(self, message: Message, state: FSMContext):
        await self.proxy_handlers.cmd_add_proxy(message, state)
    
    async def cmd_cleanup_duplicates(self, message: Message):
        await self.proxy_handlers.cmd_cleanup_duplicates(message)
    
    async def cmd_delete_proxy(self, message: Message):
        await self.proxy_handlers.cmd_delete_proxy(message)
    
    # Методы задач делегируются в модули
    async def cmd_add_task(self, message: Message, state: FSMContext):
        await self.task_handlers.cmd_add_task(message, state)
    
    async def process_task_name(self, message: Message, state: FSMContext):
        await self.task_handlers.process_task_name(message, state)
    
    async def process_item_name(self, message: Message, state: FSMContext):
        await self.task_handlers.process_item_name(message, state)
    
    async def process_wear_selection(self, message: Message, state: FSMContext):
        await self.task_handlers.process_wear_selection(message, state)
    
    async def process_max_price(self, message: Message, state: FSMContext):
        await self.task_handlers.process_max_price(message, state)
    
    async def process_float_min(self, message: Message, state: FSMContext):
        await self.task_handlers.process_float_min(message, state)
    
    async def process_float_max(self, message: Message, state: FSMContext):
        await self.task_handlers.process_float_max(message, state)
    
    async def _ask_patterns(self, message: Message, state: FSMContext):
        await self.task_handlers._ask_patterns(message, state)
    
    async def process_patterns(self, message: Message, state: FSMContext):
        await self.task_handlers.process_patterns(message, state)
    
    async def process_item_type(self, message: Message, state: FSMContext):
        await self.task_handlers.process_item_type(message, state)
    
    async def process_stickers_overpay(self, message: Message, state: FSMContext):
        await self.task_handlers.process_stickers_overpay(message, state)
    
    async def process_stickers_min_price(self, message: Message, state: FSMContext):
        await self.task_handlers.process_stickers_min_price(message, state)
    
    async def _create_task_from_state(self, message: Message, state: FSMContext):
        await self.task_handlers._create_task_from_state(message, state)
    
    async def _start_add_task(self, message: Message, state: FSMContext):
        await self.task_handlers._start_add_task(message, state)
    
    async def cmd_delete_task(self, message: Message):
        await self.task_handlers.cmd_delete_task(message)
    
    async def cmd_toggle_task(self, message: Message):
        await self.task_handlers.cmd_toggle_task(message)
    
    # Старые методы удалены - делегируются в модули
    async def handle_callback(self, callback: CallbackQuery, state: FSMContext):
        await self.callback_handlers.handle_callback(callback, state)

    async def _send_status(self, message: Message):
        """Отправляет статус через callback."""
        await self.cmd_status(message)
    
    async def _send_tasks(self, message: Message):
        """Отправляет список задач с кнопками и полной информацией о фильтрах."""
        tasks = await self.monitoring_service.get_all_tasks()
        
        if not tasks:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task")]
            ])
            await message.answer("📋 Задач мониторинга нет", reply_markup=keyboard)
            return
        
        text = "📋 <b>Задачи мониторинга:</b>\n\n"
        keyboard_buttons = []
        
        for task in tasks:
            status = "✅" if task.is_active else "❌"
            text += f"{status} <b>#{task.id}</b> - {task.name}\n"
            text += f"   📦 Предмет: <b>{task.item_name}</b>\n"
            text += f"   📊 Проверок: {task.total_checks}, Найдено: {task.items_found}\n"
            
            # Загружаем и показываем все параметры фильтров
            try:
                # ВАЖНО: filters_json может быть строкой JSON или словарем (JSONB)
                filters_json = task.filters_json
                if isinstance(filters_json, str):
                    import json
                    filters_json = json.loads(filters_json)
                filters = SearchFilters.model_validate(filters_json)
                filters.item_name = task.item_name  # Убеждаемся, что название установлено
                
                # Максимальная цена
                if filters.max_price is not None:
                    text += f"   💰 Макс. цена: <b>${filters.max_price:.2f}</b>\n"
                
                # Float диапазон
                if filters.float_range:
                    text += f"   🔢 Float: <b>{filters.float_range.min:.6f} - {filters.float_range.max:.6f}</b>\n"
                
                # Паттерны (новый формат - список)
                if filters.pattern_list:
                    patterns_str = ", ".join(map(str, filters.pattern_list.patterns[:10]))  # Показываем первые 10
                    if len(filters.pattern_list.patterns) > 10:
                        patterns_str += f" ... (+{len(filters.pattern_list.patterns) - 10} еще)"
                    text += f"   🎨 Паттерны: <b>{patterns_str}</b> ({filters.pattern_list.item_type})\n"
                
                # Паттерны (старый формат - диапазон, для обратной совместимости)
                elif filters.pattern_range:
                    text += f"   🎨 Паттерн: <b>{filters.pattern_range.min} - {filters.pattern_range.max}</b> ({filters.pattern_range.item_type})\n"
                
                # Фильтр по наклейкам
                if filters.stickers_filter:
                    sticker_info = []
                    
                    # Минимальная/максимальная цена наклеек (старый формат)
                    if filters.stickers_filter.total_stickers_price_min is not None:
                        sticker_info.append(f"Мин. цена: ${filters.stickers_filter.total_stickers_price_min:.2f}")
                    if filters.stickers_filter.total_stickers_price_max is not None:
                        sticker_info.append(f"Макс. цена: ${filters.stickers_filter.total_stickers_price_max:.2f}")
                    
                    # Формула S = D + (P * x)
                    if filters.stickers_filter.max_overpay_coefficient is not None:
                        sticker_info.append(f"Макс. переплата: {filters.stickers_filter.max_overpay_coefficient:.4f} ({filters.stickers_filter.max_overpay_coefficient*100:.2f}%)")
                    if filters.stickers_filter.min_stickers_price is not None:
                        sticker_info.append(f"Мин. цена наклеек: ${filters.stickers_filter.min_stickers_price:.2f}")
                    
                    # Конкретные наклейки (если указаны)
                    if filters.stickers_filter.stickers:
                        sticker_names = []
                        for sticker in filters.stickers_filter.stickers[:5]:  # Показываем первые 5
                            if sticker.position is not None:
                                sticker_names.append(f"Поз. {sticker.position}")
                        if len(filters.stickers_filter.stickers) > 5:
                            sticker_names.append(f"+{len(filters.stickers_filter.stickers) - 5} еще")
                        if sticker_names:
                            sticker_info.append(f"Наклейки: {', '.join(sticker_names)}")
                    
                    if sticker_info:
                        text += f"   🏷️ Наклейки: <b>{' | '.join(sticker_info)}</b>\n"
                
                # Автообновление базовой цены
                if filters.auto_update_base_price:
                    interval = filters.base_price_update_interval or 300
                    text += f"   🔄 Автообновление цены: каждые {interval} сек\n"
                
            except Exception as e:
                logger.error(f"Ошибка при парсинге фильтров задачи {task.id}: {e}")
                text += f"   ⚠️ Ошибка загрузки фильтров\n"
            
            text += "\n"
            
            # Кнопки для каждой задачи
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"{'⏸️' if task.is_active else '▶️'} #{task.id}",
                    callback_data=f"toggle_task_{task.id}"
                ),
                InlineKeyboardButton(
                    text=f"🗑️ #{task.id}",
                    callback_data=f"delete_task_{task.id}"
                )
            ])
        
        keyboard_buttons.append([InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    
    async def _send_proxies(self, message: Message):
        """Отправляет список прокси с детальной статистикой."""
        proxy_stats = await self.proxy_manager.get_proxy_stats()
        
        if not proxy_stats['proxies']:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить прокси", callback_data="add_proxy")]
            ])
            await message.answer("🔌 Прокси не добавлены", reply_markup=keyboard)
            return
        
        # Подсчитываем статистику
        total = proxy_stats['total']
        active = proxy_stats['active']
        inactive = proxy_stats['inactive']
        total_success = sum(p.get('success_count', 0) for p in proxy_stats['proxies'])
        total_fail = sum(p.get('fail_count', 0) for p in proxy_stats['proxies'])
        
        # Заблокированные = неактивные ИЛИ прокси с большой задержкой (delay_seconds >= 8.0)
        # Большая задержка обычно означает, что прокси часто получает 429 ошибки
        blocked_count = 0
        for proxy in proxy_stats['proxies']:
            if not proxy['active']:
                blocked_count += 1
            else:
                # Используем delay_seconds (если есть) или delay (для обратной совместимости)
                delay = proxy.get('delay_seconds') or proxy.get('delay', 0)
                if delay >= 8.0:
                    # Прокси с задержкой >= 8 секунд считается временно заблокированным
                    blocked_count += 1
        blocked = blocked_count
        
        # Вычисляем успешность
        success_rate = (total_success / (total_success + total_fail) * 100) if (total_success + total_fail) > 0 else 0
        
        # Отправляем общую статистику
        stats_text = f"🔌 <b>Прокси-серверы:</b>\n\n"
        stats_text += f"📊 <b>Общая статистика:</b>\n"
        stats_text += f"• Всего: {total}\n"
        stats_text += f"• Активных: {active}\n"
        stats_text += f"• Заблокированных: {blocked}\n"
        stats_text += f"• Успешных запросов: {total_success}\n"
        stats_text += f"• Ошибок: {total_fail}\n"
        stats_text += f"• Успешность: {success_rate:.1f}%\n"
        
        await message.answer(stats_text, parse_mode="HTML")
        
        # Разбиваем список прокси на части (максимум 20 прокси на сообщение, чтобы не превысить лимит)
        MAX_PROXIES_PER_MESSAGE = 20
        MAX_MESSAGE_LENGTH = 3500  # Оставляем запас от лимита 4096
        
        proxies = proxy_stats['proxies']
        keyboard_buttons = []
        current_text = ""
        current_keyboard_buttons = []
        
        for i, proxy in enumerate(proxies):
            status = "✅" if proxy['active'] else "❌"
            success = proxy.get('success_count', 0)
            fail = proxy.get('fail_count', 0)
            proxy_success_rate = (success / (success + fail) * 100) if (success + fail) > 0 else 0
            
            # Определяем статус прокси
            if not proxy['active']:
                proxy_status = "🔴 Заблокирован"
            elif fail > success * 2 and fail > 10:
                proxy_status = "⚠️ Много ошибок"
            elif success > 0 and fail == 0:
                proxy_status = "🟢 Отлично"
            elif proxy_success_rate >= 80:
                proxy_status = "🟡 Хорошо"
            else:
                proxy_status = "🟠 Проблемы"
            
            # Формируем текст для прокси
            proxy_text = f"{status} <b>#{proxy['id']}</b> - {proxy['url']}\n"
            proxy_text += f"   {proxy_status}\n"
            proxy_text += f"   Успешно: {success}, Ошибок: {fail} ({proxy_success_rate:.1f}%)\n\n"
            
            # Если это начало новой части или текст станет слишком длинным
            if i % MAX_PROXIES_PER_MESSAGE == 0:
                # Отправляем предыдущую часть (если есть)
                if i > 0 and current_text:
                    part_keyboard = InlineKeyboardMarkup(inline_keyboard=current_keyboard_buttons)
                    await message.answer(current_text, parse_mode="HTML", reply_markup=part_keyboard)
                
                # Начинаем новую часть
                part_num = i // MAX_PROXIES_PER_MESSAGE + 1
                current_text = f"📋 <b>Прокси (часть {part_num}):</b>\n\n"
                current_text += proxy_text
                current_keyboard_buttons = []
            else:
                # Проверяем, не превысит ли добавление этого прокси лимит
                if len(current_text) + len(proxy_text) > MAX_MESSAGE_LENGTH:
                    # Отправляем текущую часть
                    if current_text:
                        part_keyboard = InlineKeyboardMarkup(inline_keyboard=current_keyboard_buttons)
                        await message.answer(current_text, parse_mode="HTML", reply_markup=part_keyboard)
                    
                    # Начинаем новую часть
                    current_text = f"📋 <b>Прокси (продолжение):</b>\n\n"
                    current_text += proxy_text
                    current_keyboard_buttons = []
                else:
                    current_text += proxy_text
            
            current_keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"🗑️ Удалить #{proxy['id']}",
                    callback_data=f"delete_proxy_{proxy['id']}"
                )
            ])
        
        # Отправляем последнюю часть
        if current_text:
            current_keyboard_buttons.append([InlineKeyboardButton(text="➕ Добавить прокси", callback_data="add_proxy")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=current_keyboard_buttons)
            await message.answer(current_text, parse_mode="HTML", reply_markup=keyboard)
    
    async def _send_found(self, message: Message):
        """Отправляет найденные предметы."""
        await self.cmd_found(message)
    
    async def _delete_task(self, message: Message, task_id: int):
        """Удаляет задачу."""
        try:
            success = await self.monitoring_service.delete_monitoring_task(task_id)
            if success:
                await message.answer(f"✅ Задача #{task_id} удалена")
            else:
                await message.answer(f"❌ Задача #{task_id} не найдена")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
    
    async def _toggle_task(self, message: Message, task_id: int):
        """Включает/выключает задачу."""
        try:
            tasks = await self.monitoring_service.get_all_tasks()
            task = next((t for t in tasks if t.id == task_id), None)
            
            if task:
                new_status = not task.is_active
                await self.monitoring_service.update_monitoring_task(task_id, is_active=new_status)
                status_text = "включена" if new_status else "выключена"
                await message.answer(f"✅ Задача #{task_id} {status_text}")
            else:
                await message.answer(f"❌ Задача #{task_id} не найдена")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
    
    async def _delete_proxy(self, message: Message, proxy_id: int):
        """Удаляет прокси."""
        try:
            # Используем существующий proxy_manager с redis_service для обновления кэша
            if not self.proxy_manager:
                session = await self.db_manager.get_session()
                proxy_manager = ProxyManager(session, redis_service=self.redis_service)
                await session.close()
            else:
                proxy_manager = self.proxy_manager
            success = await proxy_manager.delete_proxy(proxy_id)
            
            if success:
                await message.answer(f"✅ Прокси #{proxy_id} удален")
                # Обновляем список прокси после удаления
                await self._send_proxies(message)
            else:
                await message.answer(f"❌ Прокси #{proxy_id} не найден")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
            logger.error(f"Ошибка удаления прокси через callback: {e}")
    
    async def _start_add_task(self, message: Message, state: FSMContext):
        """Начинает процесс добавления задачи."""
        # Сначала запрашиваем название задачи
        await message.answer(
            "📋 <b>Создание новой задачи мониторинга</b>\n\n"
            "Шаг 1/7: Отправьте название задачи:\n\n"
            "Это название будет использоваться для идентификации задачи в списке.\n"
            "Например: <code>AK-47 Redline поиск</code> или <code>Мониторинг Howl</code>\n\n"
            "Или /cancel для отмены",
            parse_mode="HTML"
        )
        await state.set_state(BotStates.waiting_for_task_name)
    
    async def send_notification(self, item: FoundItem, task: MonitoringTask):
        """
        Отправляет уведомление о найденном предмете с подробной информацией.
        
        Формат уведомления согласно требованиям пользователя:
        - Float с указанием источника
        - Паттерн с указанием источника
        - Количество наклеек
        - Общая цена наклеек
        - Детали каждой наклейки (позиция, название, цена)
        - Название со страницы
        - Цена со страницы
        - Явное указание, если наклеек нет
        
        Args:
            item: Найденный предмет
            task: Задача мониторинга
        """
        try:
            logger.info(f"📨 TelegramBot.send_notification: Начинаем отправку уведомления для предмета {item.id} ({item.item_name})")
            item_data = item.get_item_data()
            logger.debug(f"   Данные предмета: {item_data}")
            
            text = f"🎯 <b>Найден предмет!</b>\n\n"
            text += f"📋 Задача: <b>{task.name}</b>\n\n"
            text += f"<b>РАСПАРСЕННЫЕ ДАННЫЕ:</b>\n"
            text += f"{'=' * 70}\n\n"
            
            # Определяем тип предмета
            item_type = item_data.get('item_type')
            if not item_type:
                from parsers.item_type_detector import detect_item_type
                item_type = detect_item_type(
                    item_data.get('item_name', ''),
                    item_data.get('float_value') is not None,
                    len(item_data.get('stickers', [])) > 0
                )
            
            is_keychain = item_type == "keychain"
            
            # Float-значение (только для скинов)
            if not is_keychain:
                if item_data.get('float_value') is not None:
                    float_val = item_data['float_value']
                    text += f"✅ Float: <b>{float_val:.6f}</b>\n\n"
                else:
                    text += f"❌ Float: <i>не указан</i>\n\n"
            
            # Паттерн (если есть)
            if item_data.get('pattern') is not None:
                pattern = item_data['pattern']
                text += f"✅ Паттерн: <b>{pattern}</b>\n\n"
            else:
                text += f"❌ Паттерн: <i>не указан</i>\n\n"
            
            # Информация о наклейках (только для скинов)
            if not is_keychain:
                stickers = item_data.get('stickers', [])
                total_stickers_price = item_data.get('total_stickers_price', 0.0)
                
                logger.info(f"   🔍 DEBUG: stickers={len(stickers) if stickers else 0}, total_stickers_price={total_stickers_price}")
                if stickers:
                    logger.info(f"   🔍 DEBUG: Первая наклейка: {stickers[0] if len(stickers) > 0 else 'нет'}")
                
                if stickers and len(stickers) > 0:
                    text += f"✅ Наклеек найдено: <b>{len(stickers)}</b>\n\n"
                    text += f"💰 Общая цена наклеек: <b>${total_stickers_price:.2f}</b>\n\n"
                    
                    # Ограничиваем количество наклеек в сообщении (максимум 10, чтобы не превысить лимит Telegram)
                    max_stickers_in_message = 10
                    stickers_to_show = stickers[:max_stickers_in_message]
                    
                    if len(stickers) > max_stickers_in_message:
                        text += f"📋 <b>Детали наклеек (показано {max_stickers_in_message} из {len(stickers)}):</b>\n\n"
                    else:
                        text += f"📋 <b>Детали наклеек:</b>\n\n"
                    
                    for idx, sticker in enumerate(stickers_to_show, 1):
                        # Получаем данные о наклейке
                        if isinstance(sticker, dict):
                            position = sticker.get('position')
                            sticker_name = sticker.get('name') or sticker.get('sticker_name') or None
                            sticker_wear = sticker.get('wear') or None
                            price = sticker.get('price', 0.0)
                        else:
                            position = getattr(sticker, 'position', None)
                            sticker_name = getattr(sticker, 'name', None)
                            sticker_wear = getattr(sticker, 'wear', None)
                            price = getattr(sticker, 'price', 0.0) or 0.0
                        
                        # Формируем читаемое название наклейки
                        display_name = None
                        
                        # Приоритет 1: Используем wear, если оно есть и не является путем к файлу
                        if sticker_wear and not ('.png' in sticker_wear or '.jpg' in sticker_wear or len(sticker_wear.split('.')) > 2):
                            display_name = sticker_wear
                        # Приоритет 2: Используем name, если оно не является путем к файлу
                        elif sticker_name and not ('.png' in sticker_name or '.jpg' in sticker_name or len(sticker_name.split('.')) > 2):
                            display_name = sticker_name
                        # Приоритет 3: Пытаемся извлечь читаемое название из пути к файлу
                        elif sticker_name or sticker_wear:
                            raw_name = sticker_name or sticker_wear
                            # Пытаемся извлечь название команды/турнира из пути
                            # Формат может быть: "team.xxx.png | tournament" или "sig_player.xxx.png | tournament"
                            if ' | ' in raw_name:
                                parts = raw_name.split(' | ')
                                if len(parts) >= 2:
                                    # Берем последнюю часть (турнир) и предпоследнюю (команда/игрок)
                                    tournament = parts[-1].strip()
                                    team_or_player = parts[-2].strip()
                                    # Убираем расширение файла
                                    team_or_player = team_or_player.split('.')[0] if '.' in team_or_player else team_or_player
                                    # Формируем читаемое название
                                    if 'sig_' in team_or_player:
                                        player = team_or_player.replace('sig_', '').replace('_', ' ').title()
                                        display_name = f"{player} | {tournament}"
                                    else:
                                        team = team_or_player.replace('_', ' ').title()
                                        display_name = f"{team} | {tournament}"
                                else:
                                    display_name = parts[0].split('.')[0] if '.' in parts[0] else parts[0]
                            else:
                                # Пытаемся извлечь название из имени файла
                                name_part = raw_name.split('.')[0] if '.' in raw_name else raw_name
                                if 'sig_' in name_part:
                                    display_name = name_part.replace('sig_', '').replace('_', ' ').title()
                                else:
                                    display_name = name_part.replace('_', ' ').title()
                        
                        # Если все еще нет читаемого названия, используем позицию
                        if not display_name or len(display_name) < 3:
                            display_name = f"Наклейка #{idx}"
                        
                        # Формируем строку с информацией о наклейке
                        position_text = f"Slot {position + 1}" if position is not None and 0 <= position <= 4 else f"#{idx}"
                        sticker_info = f"  {idx}. <b>{display_name}</b>"
                        if price and price > 0:
                            sticker_info += f" - ${price:.2f}"
                        else:
                            # Если цена не получена, показываем ошибку парсинга
                            sticker_info += f" - <i>Ошибка парсинга цены</i>"
                        sticker_info += f" ({position_text})"
                        text += sticker_info + "\n"
                    
                    if len(stickers) > max_stickers_in_message:
                        text += f"\n<i>... и еще {len(stickers) - max_stickers_in_message} наклеек</i>\n\n"
                else:
                    text += f"❌ Наклеек нет\n\n"
            # Для брелков блок с наклейками уже пропущен выше
            
            # Название со страницы
            page_name = item_data.get('item_name') or item.item_name
            text += f"\n📝 Название со страницы: <b>{page_name}</b>\n\n"
            
            # StatTrak информация
            is_stattrak = item_data.get('is_stattrak', False)
            if is_stattrak:
                text += f"⭐ <b>StatTrak™</b>\n\n"
            
            # Цена со страницы
            # ПРИОРИТЕТ: цена из parsed_data (цена конкретного лота) > цена из БД
            page_price = item_data.get('item_price') or item.price
            logger.info(f"   💰 Цена в уведомлении: из parsed_data={item_data.get('item_price')}, из БД={item.price}, итого={page_price:.2f}")
            text += f"💰 Цена со страницы: <b>${page_price:.2f}</b>\n"
            
            # Дополнительные валюты (запрашиваем через ParserAPIClient)
            try:
                if self.parser_client:
                    logger.debug(f"   💱 TelegramBot: Запрашиваем курсы валют через ParserAPIClient...")
                    currency_rates = await self.parser_client.get_currency_rates()
                    logger.debug(f"   💱 TelegramBot: Получены курсы валют: {currency_rates}")
                    if currency_rates:
                        currency_names = {
                            "THB": "Тайский бат",
                            "CNY": "Китайский юань",
                            "RUB": "Российский рубль"
                        }
                        
                        currency_lines = []
                        for currency_code, currency_name in currency_names.items():
                            if currency_code in currency_rates and currency_rates[currency_code] is not None:
                                rate = currency_rates[currency_code]
                                price_in_currency = page_price * rate
                                # Форматируем число: убираем лишние нули после запятой, но оставляем минимум 2 знака
                                if price_in_currency >= 1000:
                                    formatted_price = f"{price_in_currency:,.0f}"
                                else:
                                    formatted_price = f"{price_in_currency:,.2f}".rstrip('0').rstrip('.')
                                currency_lines.append(f"   💵 {currency_name}: <b>{formatted_price} {currency_code}</b>")
                        
                        if currency_lines:
                            text += "\n💱 <b>Стоимость в других валютах:</b>\n"
                            text += "\n".join(currency_lines) + "\n"
                            logger.info(f"   ✅ TelegramBot: Добавлены цены в других валютах ({len(currency_lines)} валют)")
                        else:
                            logger.warning(f"   ⚠️ TelegramBot: Курсы валют получены, но нет подходящих валют для отображения")
                    else:
                        logger.warning(f"   ⚠️ TelegramBot: Курсы валют не получены (пустой ответ)")
                else:
                    logger.warning(f"   ⚠️ TelegramBot: ParserAPIClient не инициализирован, пропускаем курсы валют")
            except Exception as e:
                logger.warning(f"⚠️ TelegramBot: Не удалось получить курсы валют для уведомления: {e}")
                import traceback
                logger.debug(f"   Traceback: {traceback.format_exc()}")
            
            text += "\n"
            
            # Ссылка на Steam Market
            if item.market_url:
                import urllib.parse
                encoded_name = urllib.parse.quote(item.market_url)
                text += f"🔗 [Открыть на Steam Market](https://steamcommunity.com/market/listings/730/{encoded_name})"
            
            logger.info(f"📤 TelegramBot.send_notification: Отправляем сообщение в Telegram (chat_id={self.chat_id})")
            logger.debug(f"   Длина сообщения: {len(text)} символов")
            
            # Telegram имеет лимит 4096 символов на сообщение
            # Жесткая обрезка для гарантированной отправки
            MAX_MESSAGE_LENGTH = 3500  # Безопасный лимит с запасом
            
            # Функция для безопасной обрезки HTML-текста
            def truncate_html_safe(text: str, max_len: int) -> str:
                """Безопасно обрезает HTML-текст, не разрывая теги."""
                if len(text) <= max_len:
                    return text
                
                # Пытаемся обрезать по словам/строкам
                truncated = text[:max_len - 100]
                
                # Находим последний перенос строки
                last_newline = truncated.rfind('\n')
                if last_newline > max_len * 0.7:  # Если перенос строки не слишком далеко
                    truncated = truncated[:last_newline]
                
                # Убираем незакрытые HTML-теги в конце
                while '<' in truncated and '>' not in truncated[truncated.rfind('<'):]:
                    truncated = truncated[:truncated.rfind('<')]
                
                # Закрываем возможные открытые теги
                truncated = truncated.rstrip()
                
                return truncated + "\n\n<i>... (сообщение обрезано из-за ограничения Telegram)</i>"
            
            # Многоуровневая обрезка
            if len(text) > MAX_MESSAGE_LENGTH:
                logger.warning(f"⚠️ Сообщение слишком длинное ({len(text)} символов), обрезаем")
                
                # Уровень 1: Убираем детали наклеек, оставляем только общую информацию
                if "📋 <b>Детали наклеек" in text:
                    # Находим начало блока с наклейками
                    stickers_start = text.find("📋 <b>Детали наклеек")
                    if stickers_start > 0:
                        # Оставляем только заголовок с количеством и ценой
                        text_before = text[:text.find("📋 <b>Детали наклеек")]
                        text_after = text[text.find("\n\n", text.find("❌ Наклеек нет") if "❌ Наклеек нет" in text else text.find("📝 Название")):]
                        if not text_after:
                            text_after = text[text.find("📝 Название"):]
                        text = text_before + text_after
                        logger.debug(f"   После удаления деталей наклеек: {len(text)} символов")
                
                # Уровень 2: Если все еще слишком длинное - жесткая обрезка
                if len(text) > MAX_MESSAGE_LENGTH:
                    logger.warning(f"⚠️ Сообщение все еще длинное ({len(text)} символов), применяем жесткую обрезку")
                    text = truncate_html_safe(text, MAX_MESSAGE_LENGTH)
                    logger.debug(f"   После жесткой обрезки: {len(text)} символов")
            
            # Финальная проверка и отправка
            if len(text) > 4096:
                # Последняя попытка - обрезаем до минимума
                logger.error(f"❌ КРИТИЧНО: Сообщение все еще слишком длинное ({len(text)} символов), экстренная обрезка")
                # Оставляем только самое важное
                essential = f"🎯 <b>Найден предмет!</b>\n\n"
                essential += f"📋 Задача: <b>{task.name}</b>\n\n"
                if item_data.get('float_value') is not None:
                    essential += f"✅ Float: <b>{item_data['float_value']:.6f}</b>\n\n"
                if item_data.get('pattern') is not None:
                    essential += f"✅ Паттерн: <b>{item_data['pattern']}</b>\n\n"
                essential += f"💰 Цена: <b>${item_data.get('item_price') or item.price:.2f}</b>\n\n"
                if item.market_url:
                    import urllib.parse
                    encoded_name = urllib.parse.quote(item.market_url)
                    essential += f"🔗 [Открыть на Steam Market](https://steamcommunity.com/market/listings/730/{encoded_name})"
                text = essential[:3500]  # Финальная обрезка
                logger.warning(f"   Отправляем минимальное уведомление ({len(text)} символов)")
            
            await self.bot.send_message(
                int(self.chat_id),
                text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ TelegramBot.send_notification: Уведомление успешно отправлено для предмета {item.item_name} (ID: {item.id})")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления: {e}")
            # Пробрасываем исключение, чтобы вызывающий код знал об ошибке
            raise
    
    async def _setup_bot_commands(self):
        """Настраивает команды бота для меню (кнопка с четырьмя точками)."""
        from aiogram.types import BotCommand
        
        commands = [
            BotCommand(command="start", description="🚀 Начать работу с ботом"),
            BotCommand(command="status", description="📊 Статистика системы"),
            BotCommand(command="tasks", description="📋 Список задач мониторинга"),
            BotCommand(command="proxies", description="🔌 Список прокси"),
            BotCommand(command="found", description="🔍 Последние найденные предметы"),
            BotCommand(command="add_proxy", description="➕ Добавить прокси"),
            BotCommand(command="add_task", description="➕ Добавить задачу"),
            BotCommand(command="check_proxies", description="🔍 Проверить прокси"),
            BotCommand(command="help", description="❓ Справка по командам"),
        ]
        
        try:
            await self.bot.set_my_commands(commands)
            logger.info("✅ Команды бота настроены (меню с кнопкой из четырех точек)")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось настроить команды бота: {e}")
    
    async def start_polling(self):
        """Запускает бота."""
        logger.info("Запуск Telegram бота...")
        await self._setup_bot_commands()
        
        # Подписываемся на Redis канал для уведомлений, если Redis доступен
        if self.redis_service:
            try:
                logger.info("🔌 TelegramBot: Подключаемся к Redis...")
                await self.redis_service.connect()
                logger.info(f"✅ TelegramBot: Подключение к Redis установлено")
                logger.info("📡 TelegramBot: Подписываемся на канал 'found_items'...")
                await self.redis_service.subscribe("found_items", self._handle_redis_notification)
                logger.info("✅ TelegramBot: Подписка на Redis канал 'found_items' установлена")
            except Exception as e:
                logger.error(f"❌ TelegramBot: Не удалось подключиться к Redis: {e}")
                import traceback
                logger.debug(f"Traceback: {traceback.format_exc()}")
                logger.warning(f"⚠️ Уведомления будут отправляться напрямую (если доступен callback)")
        else:
            logger.warning("⚠️ TelegramBot: Redis сервис не инициализирован, уведомления будут отправляться напрямую")
        
        await self.dp.start_polling(self.bot)
    
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
                session = await self.db_manager.get_session()
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
                        logger.info(f"📤 TelegramBot: Отправляем уведомление в Telegram (chat_id={self.chat_id})")
                        task_logger.info(f"📤 Отправляем уведомление в Telegram")
                        try:
                            await self.send_notification(found_item, task)
                            
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
    
    async def stop(self):
        """Останавливает бота."""
        # Отключаемся от Redis
        if self.redis_service:
            try:
                await self.redis_service.stop()
            except Exception as e:
                logger.warning(f"Ошибка при отключении от Redis: {e}")
        
        await self.bot.session.close()

