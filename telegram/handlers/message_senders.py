"""
Отправка сообщений Telegram бота.
"""
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from core import SearchFilters
from services import ProxyManager, MonitoringService


class MessageSenders:
    """Отправка сообщений бота."""
    
    def __init__(self, bot_manager):
        """
        Инициализация отправки сообщений.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
    async def _send_status(self, message: Message):

        """Отправляет статус через callback."""

        await self.bot.command_handlers.cmd_status(message)



    async def _send_tasks(self, message: Message):

        """Отправляет список задач с кнопками и полной информацией о фильтрах."""

        tasks = await self.bot.monitoring_service.get_all_tasks()


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

        proxy_stats = await self.bot.proxy_manager.get_proxy_stats()


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

        await self.bot.command_handlers.cmd_found(message)



    async def _delete_task(self, message: Message, task_id: int):

        """Удаляет задачу."""

        try:

            success = await self.bot.monitoring_service.delete_monitoring_task(task_id)

            if success:

                await message.answer(f"✅ Задача #{task_id} удалена")

            else:

                await message.answer(f"❌ Задача #{task_id} не найдена")

        except Exception as e:

            await message.answer(f"❌ Ошибка: {str(e)}")



    async def _toggle_task(self, message: Message, task_id: int):

        """Включает/выключает задачу."""

        try:

            tasks = await self.bot.monitoring_service.get_all_tasks()

            task = next((t for t in tasks if t.id == task_id), None)


            if task:

                new_status = not task.is_active

                await self.bot.monitoring_service.update_monitoring_task(task_id, is_active=new_status)

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

            if not self.bot.proxy_manager:

                session = await self.bot.db_manager.get_session()

                proxy_manager = ProxyManager(session, redis_service=self.redis_service)

                await session.close()

            else:

                proxy_manager = self.bot.proxy_manager

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



