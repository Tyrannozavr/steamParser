"""
Обработчики callback запросов Telegram бота.
"""
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from loguru import logger

from telegram.states import BotStates
from telegram.keyboards import get_skip_keyboard


class CallbackHandlers:
    """Обработчики callback запросов."""
    
    def __init__(self, bot_manager):
        """
        Инициализация обработчиков callback.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
    def _get_skip_keyboard(self):
        """Получает клавиатуру с кнопкой Skip."""
        return get_skip_keyboard()
    
    async def handle_callback(self, callback: CallbackQuery, state: FSMContext):

        """Обрабатывает callback запросы."""

        data = callback.data


        if data == "status":

            await self.bot.message_senders._send_status(callback.message)

        elif data == "tasks":

            await self.bot.message_senders._send_tasks(callback.message)

        elif data == "proxies":

            await self.bot.message_senders._send_proxies(callback.message)

        elif data == "found":

            await self.bot.message_senders._send_found(callback.message)

        elif data == "add_proxy":

            await callback.message.answer(

                "🔌 Отправьте URL прокси в формате:\n"

                "http://user:pass@host:port\n\n"

                "Или /cancel для отмены"

            )

            await state.set_state(BotStates.waiting_for_proxy)

        elif data == "add_task":

            await self.bot.task_handlers._start_add_task(callback.message, state)

        elif data == "help":

            await self.bot.command_handlers.cmd_help(callback.message)

        elif data == "check_proxies":

            await self.bot.command_handlers.cmd_check_proxies(callback.message)

        elif data == "skip":

            # Обработка кнопки "Skip" - эмулируем отправку сообщения "skip"

            current_state = await state.get_state()

            # Создаем фейковое сообщение с текстом "skip"

            class FakeMessage:

                def __init__(self, original_message):

                    self.text = "skip"

                    self.chat = original_message.chat

                    self.from_user = original_message.from_user

                    self.message_id = original_message.message_id


                async def answer(self, *args, **kwargs):

                    return await callback.message.answer(*args, **kwargs)


            fake_message = FakeMessage(callback.message)


            # Вызываем соответствующий обработчик в зависимости от текущего состояния

            if current_state == BotStates.waiting_for_max_price:

                await self.bot.task_handlers.process_max_price(fake_message, state)

            elif current_state == BotStates.waiting_for_float_min:

                await self.bot.task_handlers.process_float_min(fake_message, state)

            elif current_state == BotStates.waiting_for_float_max:

                await self.bot.task_handlers.process_float_max(fake_message, state)

            elif current_state == BotStates.waiting_for_patterns:

                await self.bot.task_handlers.process_patterns(fake_message, state)

            elif current_state == BotStates.waiting_for_stickers_overpay:

                await self.bot.task_handlers.process_stickers_overpay(fake_message, state)

            elif current_state == BotStates.waiting_for_stickers_min_price:

                await self.bot.task_handlers.process_stickers_min_price(fake_message, state)

            else:

                await callback.answer("❌ Нельзя пропустить на этом этапе", show_alert=True)

                return

        elif data.startswith("delete_task_"):

            task_id = int(data.split("_")[2])

            await self.bot.message_senders._delete_task(callback.message, task_id)

        elif data.startswith("toggle_task_"):

            task_id = int(data.split("_")[2])

            await self.bot.message_senders._toggle_task(callback.message, task_id)

        elif data.startswith("delete_proxy_"):

            proxy_id = int(data.split("_")[2])

            await self.bot.message_senders._delete_proxy(callback.message, proxy_id)

        elif data.startswith("select_wear:"):

            # Обработка выбора степени износа

            hash_name = data.split(":", 1)[1]

            await callback.answer(f"Выбрано: {hash_name}")


            # Проверяем корректность

            # Используем Parser API клиент

            if not self.bot.parser_client:

                await callback.message.answer("❌ Parser API клиент не инициализирован. Redis должен быть включен.")

                await callback.answer()

                return


            try:

                is_valid, total_count = await self.bot.parser_client.validate_hash_name(appid=730, hash_name=hash_name)


                if is_valid:
                    # Сохраняем тип предмета в state (если еще не сохранен)
                    data = await state.get_data()
                    if 'item_type' not in data:
                        from parsers.item_type_detector import detect_item_type
                        is_keychain = detect_item_type(hash_name, False, False) == "keychain"
                        item_type = "keychain" if is_keychain else "skin"
                        await state.update_data(item_type=item_type, is_keychain=is_keychain)
                    
                    await state.update_data(item_name=hash_name)

                    await callback.message.answer(

                        f"✅ <b>Выбран вариант:</b> <code>{hash_name}</code>\n"

                        f"📊 Доступно лотов: <b>{total_count}</b>\n\n"

                        "Введите максимальную цену (USD):\n"

                        "Например: <code>50.0</code>\n\n"

                        "Или отправьте <code>skip</code> чтобы пропустить",

                        parse_mode="HTML",

                        reply_markup=self._get_skip_keyboard()

                    )

                    await state.set_state(BotStates.waiting_for_max_price)

                else:

                    await callback.message.answer(

                        f"❌ Выбранный вариант не имеет доступных лотов. Попробуйте другой."

                    )

            except Exception as e:

                logger.error(f"❌ handle_callback: Ошибка при обработке выбора степени износа: {e}", exc_info=True)

                await callback.message.answer("⚠️ Ошибка при обработке выбора. Попробуйте еще раз.")


        await callback.answer()


