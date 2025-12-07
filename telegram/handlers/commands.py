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
        proxy_stats = await self.bot.proxy_manager.get_proxy_stats()
        
        # Получаем детальную статистику прокси
        session = await self.bot.db_manager.get_session()
        try:
            from sqlalchemy import select, func
            from core import Proxy
            
            # Подсчитываем заблокированные прокси (с большим количеством ошибок)
            blocked_proxies_result = await session.execute(
                select(func.count(Proxy.id))
                .where(
                    Proxy.is_active == False
                )
            )
            blocked_count = blocked_proxies_result.scalar() or 0
            
            # Получаем статистику по успешным/неуспешным запросам
            total_success = sum(p.get('success_count', 0) for p in proxy_stats.get('proxies', []))
            total_fail = sum(p.get('fail_count', 0) for p in proxy_stats.get('proxies', []))
            
            text = f"""
📊 <b>Статус системы:</b>

<b>Мониторинг:</b>
• Всего задач: {stats['total_tasks']}
• Активных: {stats['active_tasks']}
• Запущенных: {stats['running_tasks']}

<b>Прокси:</b>
• Всего: {proxy_stats['total']}
• Активных: {proxy_stats['active']}
• Неактивных: {proxy_stats['inactive']}
• Заблокированных: {blocked_count}
• Успешных запросов: {total_success}
• Ошибок: {total_fail}
• Успешность: {(total_success / (total_success + total_fail) * 100) if (total_success + total_fail) > 0 else 0:.1f}%
        """
        except Exception as e:
            logger.error(f"Ошибка при получении статистики прокси: {e}")
            text = f"""
📊 <b>Статус системы:</b>

<b>Мониторинг:</b>
• Всего задач: {stats['total_tasks']}
• Активных: {stats['active_tasks']}
• Запущенных: {stats['running_tasks']}

<b>Прокси:</b>
• Всего: {proxy_stats['total']}
• Активных: {proxy_stats['active']}
• Неактивных: {proxy_stats['inactive']}
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
        """Проверяет все прокси на работоспособность параллельно."""
        await message.answer("🔍 Начинаю параллельную проверку прокси... Это может занять некоторое время.")
        
        import asyncio
        import httpx
        from sqlalchemy import select
        from core import Proxy
        
        async def check_single_proxy(proxy: Proxy) -> dict:
            """Проверяет один прокси и возвращает результат."""
            try:
                # Проверяем прокси через Steam Market API (как в реальном использовании)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "https://steamcommunity.com/market/",
                    "Origin": "https://steamcommunity.com",
                }
                async with httpx.AsyncClient(proxy=proxy.url, timeout=15, headers=headers) as client:
                    # Простой запрос к Steam Market API
                    response = await client.get(
                        "https://steamcommunity.com/market/search/render/",
                        params={"query": "AK-47", "appid": 730, "start": 0, "count": 1, "norender": 1}
                    )
                    if response.status_code == 200:
                        return {"proxy": proxy, "status": "ok", "error": None}
                    elif response.status_code == 429:
                        return {"proxy": proxy, "status": "rate_limited", "error": "429 Too Many Requests"}
                    else:
                        return {"proxy": proxy, "status": "error", "error": f"HTTP {response.status_code}"}
            except httpx.ProxyError as e:
                return {"proxy": proxy, "status": "error", "error": f"Proxy error: {str(e)[:100]}"}
            except httpx.TimeoutException:
                return {"proxy": proxy, "status": "error", "error": "Timeout"}
            except Exception as e:
                return {"proxy": proxy, "status": "error", "error": f"{type(e).__name__}: {str(e)[:100]}"}
        
        session = await self.bot.db_manager.get_session()
        try:
            # Получаем все прокси
            result = await session.execute(
                select(Proxy).order_by(Proxy.id)
            )
            all_proxies = list(result.scalars().all())
            
            if not all_proxies:
                await message.answer("❌ Прокси не найдены в базе данных")
                return
            
            # Создаем статус-сообщение для обновления прогресса
            status_msg = await message.answer(f"🔍 Проверяю {len(all_proxies)} прокси параллельно...")
            
            # Создаем задачи для параллельной проверки всех прокси
            tasks = [check_single_proxy(proxy) for proxy in all_proxies]
            
            # Выполняем все проверки параллельно
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Обрабатываем результаты (преобразуем исключения в ошибки)
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append({
                        "proxy": all_proxies[i],
                        "status": "error",
                        "error": f"Exception: {str(result)[:100]}"
                    })
                else:
                    processed_results.append(result)
            
            # Обновляем статус-сообщение
            await status_msg.edit_text(f"✅ Проверка завершена! Обрабатываю результаты...")
            
            # Формируем итоговый отчет
            active_ok = sum(1 for r in processed_results if r["proxy"].is_active and r["status"] == "ok")
            active_rate_limited = sum(1 for r in processed_results if r["proxy"].is_active and r["status"] == "rate_limited")
            active_error = sum(1 for r in processed_results if r["proxy"].is_active and r["status"] == "error")
            inactive_ok = sum(1 for r in processed_results if not r["proxy"].is_active and r["status"] == "ok")
            inactive_error = sum(1 for r in processed_results if not r["proxy"].is_active and r["status"] == "error")
            
            text = f"📊 <b>Результаты проверки прокси (Steam API):</b>\n\n"
            text += f"📋 Всего прокси: {len(all_proxies)}\n"
            text += f"✅ Активных и работающих: {active_ok}\n"
            text += f"⚠️ Активных, но rate limited: {active_rate_limited}\n"
            text += f"❌ Активных, но не работающих: {active_error}\n"
            text += f"✅ Неактивных, но работающих: {inactive_ok}\n"
            text += f"❌ Неактивных и не работающих: {inactive_error}\n\n"
            
            if active_rate_limited > 0:
                text += f"<b>⚠️ Активные прокси с rate limit:</b>\n"
                for r in processed_results:
                    if r["proxy"].is_active and r["status"] == "rate_limited":
                        text += f"   ID={r['proxy'].id}: Steam блокирует (429)\n"
                text += "\n"
            
            if active_error > 0:
                text += f"<b>❌ Активные прокси, которые не работают:</b>\n"
                for r in processed_results:
                    if r["proxy"].is_active and r["status"] == "error":
                        text += f"   ID={r['proxy'].id}: {r['error']}\n"
            
            await message.answer(text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка при проверке прокси: {str(e)}")
            logger.error(f"Ошибка проверки прокси: {e}")
        finally:
            await session.close()
    
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

