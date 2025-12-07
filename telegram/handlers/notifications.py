"""
Уведомления Telegram бота.
"""
import urllib.parse
from loguru import logger

from core import FoundItem, MonitoringTask


class NotificationHandlers:
    """Обработчики уведомлений."""
    
    def __init__(self, bot_manager):
        """
        Инициализация обработчиков уведомлений.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
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

                if self.bot.parser_client:

                    logger.debug(f"   💱 TelegramBot: Запрашиваем курсы валют через ParserAPIClient...")

                    currency_rates = await self.bot.parser_client.get_currency_rates()

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


            logger.info(f"📤 TelegramBot.send_notification: Отправляем сообщение в Telegram (chat_id={self.bot.chat_id})")

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


            await self.bot.bot.send_message(

                int(self.bot.chat_id),

                text,

                parse_mode="HTML",

                disable_web_page_preview=True

            )


            logger.info(f"✅ TelegramBot.send_notification: Уведомление успешно отправлено для предмета {item.item_name} (ID: {item.id})")


        except Exception as e:

            logger.error(f"Ошибка при отправке уведомления: {e}")

            # Пробрасываем исключение, чтобы вызывающий код знал об ошибке

            raise


