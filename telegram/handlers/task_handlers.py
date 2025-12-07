"""
Обработчики задач Telegram бота.
"""
import asyncio
import re
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from telegram.states import BotStates
from telegram.keyboards import get_skip_keyboard
from core import SearchFilters, FloatRange, PatternList, StickersFilter
from services import MonitoringService


class TaskHandlers:
    """Обработчики задач бота."""
    
    def __init__(self, bot_manager):
        """
        Инициализация обработчиков задач.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
    def _get_skip_keyboard(self):
        """Получает клавиатуру с кнопкой Skip."""
        return get_skip_keyboard()
    
    async def process_task_name(self, message: Message, state: FSMContext):

        """Обрабатывает создание задачи (упрощенная версия)."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        # Проверяем, что message.text не None (может быть при отправке фото/документов)

        if not message.text:

            await message.answer("❌ Пожалуйста, отправьте текстовое сообщение с названием задачи")

            return


        task_name = message.text.strip()


        # Сохраняем название в состояние

        await state.update_data(task_name=task_name)


        # Просим ввести название предмета

        await message.answer(

            f"✅ Шаг 1/7: Название задачи: <b>{task_name}</b>\n\n"

            "Шаг 2/7: Отправьте название предмета для мониторинга:\n"

            "⚠️ <b>Важно:</b> Используйте <b>английское название</b>!\n"

            "Steam Market API не поддерживает русский язык.\n\n"

            "Примеры:\n"

            "• <code>AK-47 | Nightwish</code>\n"

            "• <code>AK-47 | Redline</code>\n"

            "• <code>M4A4 | Howl</code>\n\n"

            "Или /cancel для отмены",

            parse_mode="HTML"

        )

        await state.set_state(BotStates.waiting_for_item_name)



    async def process_item_name(self, message: Message, state: FSMContext):

        """Обрабатывает ввод названия предмета."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        item_name = message.text.strip()


        # Проверяем, не русский ли язык (простая проверка по кириллице)

        has_cyrillic = any('\u0400' <= char <= '\u04FF' for char in item_name)

        if has_cyrillic:

            await message.answer(

                "⚠️ <b>Внимание!</b>\n\n"

                "Обнаружен русский текст в названии предмета.\n"

                "Steam Market API <b>не поддерживает поиск по русским названиям</b>.\n"

                "Поиск работает только по <b>английским названиям</b> (market_hash_name).\n\n"

                "Пожалуйста, введите название на английском языке:\n"

                "• <code>AK-47 | Nightwish</code> вместо <code>AK-47 | Пожелание на ночь</code>\n"

                "• <code>AK-47 | Redline</code> вместо <code>AK-47 | Красная линия</code>\n\n"

                "Повторите ввод названия предмета:",

                parse_mode="HTML"

            )

            # Остаемся в том же состоянии, чтобы пользователь мог ввести правильное название

            return


        # Проверяем, есть ли степень износа в названии

        import re

        wear_patterns = [

            r'\(Factory New\)',

            r'\(Minimal Wear\)',

            r'\(Field-Tested\)',

            r'\(Well-Worn\)',

            r'\(Battle-Scarred\)'

        ]


        has_wear = any(re.search(pattern, item_name, re.IGNORECASE) for pattern in wear_patterns)

        logger.info(f"🔍 process_item_name: Проверка степени износа для '{item_name}': has_wear={has_wear}")


        if has_wear:

            logger.info(f"🔍 process_item_name: Степень износа указана в названии, проверяю корректность...")

            # Степень износа указана - проверяем корректность

            await message.answer("🔍 Проверяю корректность названия предмета...")


            # Используем Parser API клиент

            if not self.bot.parser_client:

                await message.answer("❌ Parser API клиент не инициализирован. Redis должен быть включен.")

                return


            try:

                is_valid, total_count = await self.bot.parser_client.validate_hash_name(appid=730, hash_name=item_name)


                if is_valid:

                    await state.update_data(item_name=item_name)

                    await message.answer(

                        f"✅ <b>Предмет найден!</b>\n\n"

                        f"📦 <b>{item_name}</b>\n"

                        f"📊 Доступно лотов: <b>{total_count}</b>\n\n"

                        "Введите максимальную цену (USD):\n"

                        "Например: <code>50.0</code>\n\n"

                        "Или отправьте <code>skip</code> чтобы пропустить",

                        parse_mode="HTML",

                        reply_markup=self._get_skip_keyboard()

                    )

                    await state.set_state(BotStates.waiting_for_max_price)

                else:

                    await message.answer(

                        f"❌ <b>Предмет не найден</b>\n\n"

                        f"Название <code>{item_name}</code> не найдено на Steam Market.\n\n"

                        "Возможные причины:\n"

                        "• Неправильное написание\n"

                        "• Предмет отсутствует на маркете\n"

                        "• Неправильная степень износа\n\n"

                        "Попробуйте ввести название без степени износа, чтобы увидеть доступные варианты:",

                        parse_mode="HTML"

                    )

            except Exception as e:

                logger.error(f"❌ process_item_name: Ошибка при проверке hash_name: {e}", exc_info=True)

                await message.answer(

                    f"⚠️ Ошибка при проверке предмета. Попробуйте еще раз или введите название без степени износа."

                )

        else:

            # Степень износа не указана - ищем варианты

            logger.info(f"🔍 process_item_name: Степень износа НЕ указана для '{item_name}', ищем варианты...")

            logger.info(f"🔍 process_item_name: Переходим в блок else для поиска вариантов")


            try:

                await message.answer("🔍 Ищу доступные варианты предмета...")

                logger.info(f"🔍 process_item_name: Сообщение 'Ищу доступные варианты' отправлено пользователю")

            except Exception as e:

                logger.error(f"❌ process_item_name: Ошибка при отправке сообщения: {e}")


            # Используем Parser API клиент

            if not self.bot.parser_client:

                await message.answer("❌ Parser API клиент не инициализирован. Redis должен быть включен.")

                return


            try:

                logger.info(f"🔍 process_item_name: Вызываю get_item_variants через Parser API для '{item_name}'")

                variants = await self.bot.parser_client.get_item_variants(item_name)

                logger.info(f"🔍 process_item_name: Получено {len(variants)} вариантов")


                if not variants:

                    logger.warning(f"⚠️ process_item_name: Варианты не найдены для '{item_name}'")

                    await message.answer(

                        f"❌ <b>Варианты не найдены</b>\n\n"

                        f"По запросу <code>{item_name}</code> ничего не найдено.\n\n"

                        "Проверьте правильность написания и попробуйте еще раз:",

                        parse_mode="HTML"

                    )

                    return


                # Определяем, является ли предмет брелком (Charm или Keychain)

                from parsers.item_type_detector import detect_item_type

                is_keychain = detect_item_type(item_name, False, False) == "keychain"
                
                # Фильтруем варианты с износом для скинов
                variants_with_wear = [v for v in variants if v.get('wear_condition')]
                
                # Если варианты найдены, но нет износа - это скорее всего брелок
                if not is_keychain and len(variants) > 0 and len(variants_with_wear) == 0:
                    logger.info(f"🔍 process_item_name: Найдены варианты без износа для '{item_name}', определяем как брелок")
                    is_keychain = True
                
                item_type = "keychain" if is_keychain else "skin"
                
                # Сохраняем тип предмета в state
                await state.update_data(item_type=item_type, is_keychain=is_keychain)

                # Для брелков не фильтруем по износу (у них нет износа)

                if is_keychain:

                    variants_with_wear = variants

                    logger.info(f"🔍 process_item_name: Предмет '{item_name}' определен как брелок, используем все {len(variants)} вариантов")

                else:

                    logger.info(f"🔍 process_item_name: Вариантов с износом: {len(variants_with_wear)} из {len(variants)}")


                # Логируем все варианты для отладки

                for i, v in enumerate(variants, 1):

                    logger.info(f"  Вариант {i}: {v.get('market_hash_name')} - is_stattrak={v.get('is_stattrak', 'NOT SET')}, wear={v.get('wear_condition', 'N/A')}")


                if not variants_with_wear:

                    logger.warning(f"⚠️ process_item_name: Нет вариантов для предмета '{item_name}'")

                    await message.answer(

                        f"❌ <b>Варианты не найдены</b>\n\n"

                        f"По запросу <code>{item_name}</code> ничего не найдено.\n\n"

                        "Проверьте правильность написания и попробуйте еще раз:",

                        parse_mode="HTML"

                    )

                    return


                # Группируем по комбинации (StatTrak/обычный + степень износа)

                # Для брелков группируем только по StatTrak/обычный

                variant_groups = {}

                for variant in variants_with_wear:

                    wear = variant.get('wear_condition')

                    is_stattrak = variant.get('is_stattrak', False)

                    # Создаем ключ: (is_stattrak, wear) для скинов, (is_stattrak,) для брелков

                    if is_keychain:

                        key = (is_stattrak,)

                    else:

                        key = (is_stattrak, wear)

                    if key not in variant_groups:

                        variant_groups[key] = []

                    variant_groups[key].append(variant)

                    logger.debug(f"  Группировка: is_stattrak={is_stattrak}, wear={wear}, hash_name={variant.get('market_hash_name')}")


                logger.info(f"🔍 process_item_name: Создано групп: {len(variant_groups)}")

                for key, items in variant_groups.items():

                    logger.info(f"  Группа {key}: {len(items)} вариантов")


                # ОПТИМИЗАЦИЯ: Если все варианты имеют одинаковую комбинацию (или только один вариант),

                # автоматически выбираем его без показа кнопок

                unique_keys = list(variant_groups.keys())

                logger.info(f"🔍 process_item_name: Уникальных комбинаций (StatTrak+износ): {len(unique_keys)}")

                if len(unique_keys) == 1:

                    logger.info(f"✅ process_item_name: Одна комбинация, автоматически выбираем")

                    # Все варианты с одинаковой комбинацией - автоматически выбираем первый

                    key = unique_keys[0]

                    first_item = variant_groups[key][0]

                    hash_name = first_item.get('market_hash_name', '')


                    logger.info(f"🔍 process_item_name: Проверяю единственный вариант - hash_name='{hash_name}'")


                    # Проверяем количество лотов через Parser API

                    is_valid, total_count = await self.bot.parser_client.validate_hash_name(appid=730, hash_name=hash_name)


                    logger.info(f"📊 process_item_name: Результат проверки для '{hash_name}': is_valid={is_valid}, total_count={total_count}")


                    if is_valid:
                        # Сохраняем тип предмета в state (если еще не сохранен)
                        data = await state.get_data()
                        if 'item_type' not in data:
                            is_keychain = detect_item_type(hash_name, False, False) == "keychain"
                            item_type = "keychain" if is_keychain else "skin"
                            await state.update_data(item_type=item_type, is_keychain=is_keychain)
                        
                        await state.update_data(item_name=hash_name)

                        await message.answer(

                            f"✅ <b>Предмет найден!</b>\n\n"

                            f"📦 <b>{hash_name}</b>\n"

                            f"📊 Доступно лотов: <b>{total_count}</b>\n\n"

                            "Введите максимальную цену (USD):\n"

                            "Например: <code>50.0</code>\n\n"

                            "Или отправьте <code>skip</code> чтобы пропустить",

                            parse_mode="HTML",

                            reply_markup=self._get_skip_keyboard()

                        )

                        await state.set_state(BotStates.waiting_for_max_price)

                        return

                    else:

                        await message.answer(

                            f"❌ <b>Вариант не имеет доступных лотов</b>\n\n"

                            f"Найден вариант <code>{hash_name}</code>, но на маркете нет доступных лотов.",

                            parse_mode="HTML"

                        )

                        return


                # Если несколько разных комбинаций - показываем кнопки для выбора
                keyboard_buttons = []
                skipped_variants = []

                logger.info(f"🔍 process_item_name: Начинаю параллельную проверку {len(variant_groups)} вариантов комбинаций")

                # Сортируем варианты: сначала обычные, потом StatTrak, внутри по степени износа
                # Для брелков ключ имеет формат (is_stattrak,), для скинов - (is_stattrak, wear)
                sorted_keys = sorted(variant_groups.keys(), key=lambda x: (x[0], x[1] if len(x) > 1 else ''))

                # Подготавливаем данные для параллельной проверки
                async def check_variant(key):
                    """Проверяет один вариант и возвращает результат."""
                    # Обрабатываем ключ: для скинов (is_stattrak, wear), для брелков (is_stattrak,)
                    if len(key) == 2:
                        is_stattrak, wear = key
                    else:
                        is_stattrak = key[0]
                        wear = None  # Для брелков нет износа

                    items = variant_groups[key]
                    first_item = items[0]
                    hash_name = first_item.get('market_hash_name', '')

                    stattrack_prefix = "StatTrak™ " if is_stattrak else ""
                    wear_text = wear if wear else ""

                    logger.info(f"🔍 process_item_name: Проверяю вариант {stattrack_prefix}{wear_text} - hash_name='{hash_name}'")

                    # Проверяем количество лотов через Parser API
                    is_valid, total_count = await self.bot.parser_client.validate_hash_name(appid=730, hash_name=hash_name)

                    return {
                        'key': key,
                        'is_stattrak': is_stattrak,
                        'wear': wear,
                        'wear_text': wear_text,
                        'stattrack_prefix': stattrack_prefix,
                        'hash_name': hash_name,
                        'is_valid': is_valid,
                        'total_count': total_count
                    }

                # Выполняем все проверки параллельно
                check_tasks = [check_variant(key) for key in sorted_keys]
                results = await asyncio.gather(*check_tasks)

                # Обрабатываем результаты
                for result in results:
                    if result['is_valid']:
                        # Формируем текст кнопки: для скинов показываем износ, для брелков - только StatTrak
                        if result['wear'] is None:  # Брелок (нет износа)
                            button_text = f"{result['stattrack_prefix']}Брелок ({result['total_count']} лотов)" if result['stattrack_prefix'] else f"Брелок ({result['total_count']} лотов)"
                        else:
                            button_text = f"{result['stattrack_prefix']}{result['wear']} ({result['total_count']} лотов)"

                        keyboard_buttons.append([
                            InlineKeyboardButton(
                                text=button_text,
                                callback_data=f"select_wear:{result['hash_name']}"
                            )
                        ])

                        logger.info(f"✅ process_item_name: Добавлена кнопка для {result['stattrack_prefix']}{result['wear_text']} ({result['hash_name']}): {result['total_count']} лотов")
                    else:
                        skipped_variants.append(f"{result['stattrack_prefix']}{result['wear_text']} ({result['hash_name']})")
                        logger.info(f"❌ process_item_name: Вариант {result['stattrack_prefix']}{result['wear_text']} ({result['hash_name']}) не прошел проверку: is_valid=False, total_count={result['total_count']}")


                if not keyboard_buttons:

                    await message.answer(

                        f"❌ <b>Нет доступных вариантов с лотами</b>\n\n"

                        f"Найдено {len(variants_with_wear)} вариантов, но ни один не имеет доступных лотов на маркете.",

                        parse_mode="HTML"

                    )

                    return


                # Сохраняем базовое название для отображения

                await state.update_data(base_item_name=item_name)


                logger.info(f"✅ process_item_name: Показываю {len(keyboard_buttons)} кнопок для выбора степени износа (пропущено: {len(skipped_variants)})")

                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

                await message.answer(

                    f"📦 <b>Найдено вариантов: {len(variants_with_wear)}</b>\n"

                    f"✅ <b>Доступно для выбора: {len(keyboard_buttons)}</b>\n\n"

                    f"Выберите степень износа для предмета <code>{item_name}</code>:",

                    parse_mode="HTML",

                    reply_markup=keyboard

                )

                await state.set_state(BotStates.waiting_for_wear_selection)

                logger.info(f"✅ process_item_name: Состояние изменено на waiting_for_wear_selection")

                return  # ВАЖНО: останавливаем выполнение после показа кнопок


            except Exception as e:

                logger.error(f"❌ process_item_name: Ошибка при поиске вариантов для '{item_name}': {e}", exc_info=True)

                import traceback

                error_details = traceback.format_exc()

                logger.error(f"❌ process_item_name: Детали ошибки:\n{error_details}")

                await message.answer(

                    f"⚠️ <b>Ошибка при поиске вариантов</b>\n\n"

                    f"Произошла ошибка: {str(e)}\n\n"

                    f"Попробуйте еще раз или введите полное название с износом, например:\n"

                    f"<code>AK-47 | Redline (Field-Tested)</code>",

                    parse_mode="HTML"

                )

                return  # ВАЖНО: останавливаем выполнение, чтобы не переходить к следующему шагу



    async def process_wear_selection(self, message: Message, state: FSMContext):

        """Обрабатывает выбор степени износа через callback."""

        # Этот метод будет вызываться через callback, но на всякий случай обработаем и текстовый ввод

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        # Если это текстовый ввод, пытаемся найти соответствующий вариант

        selected_text = message.text.strip()

        data = await state.get_data()

        base_name = data.get('base_item_name', '')


        if not base_name:

            await message.answer("❌ Ошибка: не найдено базовое название предмета. Начните заново.")

            await state.clear()

            return


        # Используем Parser API клиент

        if not self.bot.parser_client:

            await message.answer("❌ Parser API клиент не инициализирован. Redis должен быть включен.")

            return


        try:

            variants = await self.bot.parser_client.get_item_variants(base_name)


            # Пытаемся найти вариант по тексту

            selected_variant = None

            for variant in variants:

                if selected_text.lower() in variant.get('market_hash_name', '').lower():

                    selected_variant = variant

                    break


            if selected_variant:

                hash_name = selected_variant.get('market_hash_name', '')

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

                    await message.answer(

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

                    await message.answer("❌ Выбранный вариант не имеет доступных лотов. Попробуйте другой.")

            else:

                await message.answer("❌ Вариант не найден. Используйте кнопки для выбора.")

        except Exception as e:

            logger.error(f"❌ process_wear_selection: Ошибка при обработке выбора: {e}", exc_info=True)

            await message.answer("⚠️ Ошибка при обработке выбора. Попробуйте еще раз.")



    async def process_max_price(self, message: Message, state: FSMContext):

        """Обрабатывает ввод максимальной цены."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        data = await state.get_data()

        max_price = None


        if message.text.lower() != "skip":

            try:

                max_price = float(message.text.strip())

            except ValueError:

                await message.answer("❌ Неверный формат. Введите число или 'skip'")

                return


        await state.update_data(max_price=max_price)

        # Проверяем тип предмета - для брелков пропускаем float и наклейки
        data = await state.get_data()
        is_keychain = data.get('is_keychain', False)
        item_type = data.get('item_type', 'skin')
        
        if is_keychain or item_type == "keychain":
            # Для брелков пропускаем float и наклейки, переходим к паттернам
            logger.info(f"🔍 process_max_price: Предмет является брелком, пропускаем float и наклейки")
            await self._ask_patterns(message, state)
        else:
            # Для скинов спрашиваем float диапазон
            await message.answer(

                "🎯 <b>Фильтр по Float</b>\n\n"

                "Введите минимальное значение float (0.0 - 1.0):\n"

                "Например: <code>0.15</code>\n\n"

                "Или отправьте <code>skip</code> чтобы пропустить",

                parse_mode="HTML",

                reply_markup=self._get_skip_keyboard()

            )

            await state.set_state(BotStates.waiting_for_float_min)



    async def process_float_min(self, message: Message, state: FSMContext):

        """Обрабатывает ввод минимального float."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        data = await state.get_data()

        float_min = None


        if message.text.lower() != "skip":

            try:

                float_min = float(message.text.strip())

                if not 0.0 <= float_min <= 1.0:

                    await message.answer("❌ Float должен быть от 0.0 до 1.0")

                    return

            except ValueError:

                await message.answer("❌ Неверный формат. Введите число или 'skip'")

                return


        await state.update_data(float_min=float_min)


        if float_min is not None:

            # Спрашиваем максимальный float

            await message.answer(

                f"📊 Float min: <b>{float_min}</b>\n\n"

                "Введите максимальное значение float:\n"

                "Например: <code>0.20</code>\n\n"

                "Или отправьте <code>skip</code> чтобы пропустить",

                parse_mode="HTML",

                reply_markup=self._get_skip_keyboard()

            )

            await state.set_state(BotStates.waiting_for_float_max)

        else:

            # Пропускаем float, переходим к паттернам

            await state.update_data(float_max=None)

            await self._ask_patterns(message, state)



    async def process_float_max(self, message: Message, state: FSMContext):

        """Обрабатывает ввод максимального float."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        data = await state.get_data()

        float_max = None


        if message.text.lower() != "skip":

            try:

                float_max = float(message.text.strip())

                if not 0.0 <= float_max <= 1.0:

                    await message.answer("❌ Float должен быть от 0.0 до 1.0")

                    return

                float_min = data.get('float_min')

                if float_min and float_max < float_min:

                    await message.answer(f"❌ Максимальный float должен быть >= {float_min}")

                    return

            except ValueError:

                await message.answer("❌ Неверный формат. Введите число или 'skip'")

                return


        await state.update_data(float_max=float_max)

        await self._ask_patterns(message, state)



    async def _ask_patterns(self, message: Message, state: FSMContext):

        """Спрашивает паттерны."""

        await message.answer(

            "🔢 <b>Фильтр по паттернам</b>\n\n"

            "Введите список паттернов через запятую:\n"

            "Например: <code>372, 48, 289</code>\n\n"

            "Или отправьте <code>skip</code> чтобы пропустить",

            parse_mode="HTML",

            reply_markup=self._get_skip_keyboard()

        )

        await state.set_state(BotStates.waiting_for_patterns)



    async def process_patterns(self, message: Message, state: FSMContext):

        """Обрабатывает ввод паттернов."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        data = await state.get_data()

        patterns = None

        item_type = "skin"  # По умолчанию


        if message.text.lower() != "skip":

            try:

                patterns_list = [int(p.strip()) for p in message.text.split(',')]

                # Определяем тип по диапазону паттернов

                if any(p > 999 for p in patterns_list):

                    item_type = "keychain"

                patterns = patterns_list

            except ValueError:

                await message.answer("❌ Неверный формат. Введите числа через запятую или 'skip'")

                return


        # Обновляем item_type если он был определен ранее (для брелков)
        data = await state.get_data()
        existing_item_type = data.get('item_type', 'skin')
        if existing_item_type == "keychain":
            item_type = "keychain"
        
        await state.update_data(patterns=patterns, item_type=item_type)

        # Проверяем тип предмета - для брелков пропускаем наклейки
        is_keychain = item_type == "keychain" or existing_item_type == "keychain"
        
        if is_keychain:
            # Для брелков пропускаем наклейки, сразу создаем задачу
            logger.info(f"🔍 process_patterns: Предмет является брелком, пропускаем наклейки, создаем задачу")
            await self._create_task_from_state(message, state)
        else:
            # Для скинов спрашиваем про формулу наклеек (S = D + (P * x))
            await message.answer(

                "📊 <b>Фильтр по наклейкам (формула S = D + (P * x))</b>\n\n"

                "Где:\n"

                "• S - текущая цена предмета\n"

                "• D - базовая цена (цена первого лота)\n"

                "• P - общая цена наклеек\n"

                "• x - коэффициент переплаты\n\n"

                "Введите максимальный коэффициент переплаты (x) от 0.0 до 1.0:\n"

                "Например: <code>0.08</code> (8% переплата)\n"

                "Или <code>0.15</code> (15% переплата)\n\n"

                "Или отправьте <code>skip</code> чтобы пропустить",

                parse_mode="HTML",

                reply_markup=self._get_skip_keyboard()

            )

            await state.set_state(BotStates.waiting_for_stickers_overpay)



    async def process_item_type(self, message: Message, state: FSMContext):

        """Обрабатывает выбор типа предмета (не используется, но оставлен для совместимости)."""

        await self._create_task_from_state(message, state)



    async def process_stickers_overpay(self, message: Message, state: FSMContext):

        """Обрабатывает ввод максимального коэффициента переплаты за наклейки."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        data = await state.get_data()

        max_overpay_coefficient = None


        if message.text.lower() != "skip":

            try:

                value = float(message.text.strip())

                if not 0.0 <= value <= 1.0:

                    await message.answer("❌ Коэффициент должен быть от 0.0 до 1.0")

                    return

                max_overpay_coefficient = value

            except ValueError:

                await message.answer("❌ Неверный формат. Введите число от 0.0 до 1.0 или 'skip'")

                return


        await state.update_data(max_overpay_coefficient=max_overpay_coefficient)


        # Спрашиваем минимальную цену наклеек для формулы

        await message.answer(

            "💰 <b>Минимальная цена наклеек для формулы</b>\n\n"

            "Введите минимальную общую цену наклеек (P в формуле):\n"

            "Например: <code>5.0</code> (минимум $5 наклеек)\n"

            "Или <code>10.0</code> (минимум $10 наклеек)\n\n"

            "Или отправьте <code>skip</code> чтобы пропустить",

            parse_mode="HTML",

            reply_markup=self._get_skip_keyboard()

        )

        await state.set_state(BotStates.waiting_for_stickers_min_price)



    async def process_stickers_min_price(self, message: Message, state: FSMContext):

        """Обрабатывает ввод минимальной цены наклеек для формулы."""

        if message.text == "/cancel":

            await state.clear()

            await message.answer("❌ Отменено")

            return


        data = await state.get_data()

        min_stickers_price = None


        if message.text.lower() != "skip":

            try:

                min_stickers_price = float(message.text.strip())

                if min_stickers_price < 0:

                    await message.answer("❌ Цена не может быть отрицательной")

                    return

            except ValueError:

                await message.answer("❌ Неверный формат. Введите число или 'skip'")

                return


        await state.update_data(min_stickers_price=min_stickers_price)


        # Создаем задачу

        await self._create_task_from_state(message, state)



    async def _create_task_from_state(self, message: Message, state: FSMContext):

        """Создает задачу из данных состояния."""

        data = await state.get_data()


        item_name = data.get('item_name')

        # Генерируем название задачи автоматически из названия предмета

        task_name = data.get('task_name', item_name if item_name else 'Новая задача')

        max_price = data.get('max_price')

        float_min = data.get('float_min')

        float_max = data.get('float_max')

        patterns = data.get('patterns')

        item_type = data.get('item_type', 'skin')


        if not item_name:

            await message.answer("❌ Ошибка: не указано название предмета")

            await state.clear()

            return


        # Создаем фильтры

        from core import SearchFilters, FloatRange, PatternList


        filters = SearchFilters(item_name=item_name)


        if max_price:

            filters.max_price = max_price

        # Получаем значения для фильтров наклеек (нужны для формирования текста, даже если не применяются)
        max_overpay_coefficient = data.get('max_overpay_coefficient')
        min_stickers_price = data.get('min_stickers_price')

        # Для брелков не применяем фильтры float и наклеек
        if item_type != "keychain":
            if float_min is not None and float_max is not None:
                filters.float_range = FloatRange(min=float_min, max=float_max)

            # Фильтр по наклейкам с формулой S = D + (P * x)
            if max_overpay_coefficient is not None or min_stickers_price is not None:
                filters.stickers_filter = StickersFilter(
                    max_overpay_coefficient=max_overpay_coefficient,
                    min_stickers_price=min_stickers_price
                )
        else:
            logger.info(f"🔍 _create_task_from_state: Предмет является брелком, пропускаем фильтры float и наклеек")

        if patterns:
            filters.pattern_list = PatternList(patterns=patterns, item_type=item_type)


        try:

            task = await self.bot.monitoring_service.add_monitoring_task(

                name=task_name,

                item_name=item_name,

                filters=filters,

                check_interval=60  # 1 минута - быстрая проверка новых объявлений

            )


            # Формируем описание фильтров

            filters_text = f"📦 Предмет: {item_name}\n"

            if max_price:

                filters_text += f"💰 Макс. цена: ${max_price}\n"

            if float_min is not None and float_max is not None:

                filters_text += f"🎯 Float: {float_min} - {float_max}\n"

            if patterns:

                filters_text += f"🔢 Паттерны: {', '.join(map(str, patterns))} ({item_type})\n"

            if max_overpay_coefficient is not None:

                filters_text += f"📊 Макс. переплата за наклейки: {max_overpay_coefficient:.4f} ({max_overpay_coefficient*100:.2f}%)\n"

            if min_stickers_price is not None:

                filters_text += f"💰 Мин. цена наклеек: ${min_stickers_price:.2f}\n"


            await message.answer(

                f"✅ <b>Задача создана!</b>\n\n"

                f"ID: #{task.id}\n"

                f"Название: {task.name}\n\n"

                f"{filters_text}\n"

                f"Используйте /tasks для управления",

                parse_mode="HTML"

            )

        except Exception as e:

            await message.answer(f"❌ Ошибка при создании задачи: {str(e)}")

            logger.exception("Ошибка создания задачи")


        await state.clear()



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



    async def cmd_delete_task(self, message: Message):

        """Удаляет задачу."""

        try:

            task_id = int(message.text.split()[1])

            session = await self.bot.db_manager.get_session()

            monitoring_service = MonitoringService(session, self.bot.proxy_manager)

            success = await monitoring_service.delete_monitoring_task(task_id)

            await session.close()


            if success:

                await message.answer(f"✅ Задача #{task_id} удалена")

            else:

                await message.answer(f"❌ Задача #{task_id} не найдена")

        except (IndexError, ValueError):

            await message.answer("❌ Использование: /delete_task [id]")

        except Exception as e:

            await message.answer(f"❌ Ошибка: {str(e)}")



    async def cmd_toggle_task(self, message: Message):

        """Включает/выключает задачу."""

        try:

            task_id = int(message.text.split()[1])

            session = await self.bot.db_manager.get_session()

            monitoring_service = MonitoringService(session, self.bot.proxy_manager)


            tasks = await monitoring_service.get_all_tasks()

            task = next((t for t in tasks if t.id == task_id), None)


            if task:

                new_status = not task.is_active

                await monitoring_service.update_monitoring_task(task_id, is_active=new_status)

                status_text = "включена" if new_status else "выключена"

                await message.answer(f"✅ Задача #{task_id} {status_text}")

            else:

                await message.answer(f"❌ Задача #{task_id} не найдена")


            await session.close()

        except (IndexError, ValueError):

            await message.answer("❌ Использование: /toggle_task [id]")

        except Exception as e:

            await message.answer(f"❌ Ошибка: {str(e)}")



    async def cmd_add_task(self, message: Message, state: FSMContext):

        """Добавляет задачу мониторинга."""

        await self._start_add_task(message, state)



