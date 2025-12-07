"""
Обработчики для работы с прокси.
"""
from typing import Tuple, Optional
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from loguru import logger

from telegram.states import BotStates
from services import ProxyManager
from core import Proxy
from sqlalchemy import select


class ProxyHandlers:
    """Обработчики для работы с прокси."""
    
    def __init__(self, bot_manager):
        """
        Инициализация обработчиков прокси.
        
        Args:
            bot_manager: Экземпляр TelegramBotManager
        """
        self.bot = bot_manager
    
    @staticmethod
    def normalize_proxy_url(proxy_url: str) -> Tuple[str, str, bool]:
        """
        Нормализует URL прокси.
        
        Args:
            proxy_url: Исходный URL прокси
            
        Returns:
            Кортеж (normalized_url, original_url, has_extra_param)
        """
        original_url = proxy_url.strip()
        normalized_url = original_url
        
        # Проверяем, есть ли параметры после порта
        has_extra_param = False
        
        if '@' in original_url:
            # Есть авторизация: user:pass@host:port:extra
            auth_part, rest = original_url.split('@', 1)
            if ':' in rest:
                host_port_parts = rest.split(':')
                if len(host_port_parts) > 2:  # host:port:extra
                    has_extra_param = True
                    # Берем только host:port для подключения
                    rest = ':'.join(host_port_parts[:2])
            normalized_url = f"{auth_part}@{rest}"
        else:
            # Нет авторизации: host:port:extra
            if ':' in original_url:
                parts = original_url.split(':')
                if len(parts) > 2:  # host:port:extra
                    has_extra_param = True
                    normalized_url = ':'.join(parts[:2])  # Берем только host:port
        
        # Добавляем префикс http:// если его нет
        if not normalized_url.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
            normalized_url = f"http://{normalized_url}"
        
        return normalized_url, original_url, has_extra_param
    
    async def add_single_proxy(self, proxy_url: str, proxy_manager) -> Tuple[bool, str, Optional[int]]:
        """
        Добавляет один прокси.
        
        Args:
            proxy_url: URL прокси
            proxy_manager: ProxyManager
            
        Returns:
            Кортеж (success, message, proxy_id)
        """
        normalized_url, original_url, has_extra_param = self.normalize_proxy_url(proxy_url)
        
        try:
            # Проверяем, существует ли уже такой прокси (по нормализованному URL)
            check_result = await proxy_manager.db_session.execute(
                select(Proxy)
            )
            all_proxies = check_result.scalars().all()
            existing_proxy = None
            for p in all_proxies:
                p_normalized = ProxyManager._normalize_proxy_url(p.url)
                if p_normalized == normalized_url:
                    existing_proxy = p
                    break
            
            if existing_proxy:
                response_msg = f"⏭️ Прокси уже существует (ID: {existing_proxy.id})\n📝 URL: {normalized_url}"
                logger.info(f"⏭️ Прокси уже существует: {normalized_url} (ID: {existing_proxy.id})")
                return True, response_msg, existing_proxy.id
            
            # Сначала пробуем стандартный формат
            try:
                proxy = await proxy_manager.add_proxy(normalized_url)
                response_msg = f"✅ Прокси добавлен (ID: {proxy.id})\n📝 URL: {normalized_url}"
                if has_extra_param:
                    response_msg += f"\n⚠️ Параметр после порта удален"
                logger.info(f"✅ Прокси добавлен через бота: {normalized_url} (оригинал: {original_url}, ID: {proxy.id})")
                return True, response_msg, proxy.id
            except Exception as e1:
                # Если стандартный формат не работает, пробуем оригинальный
                if has_extra_param:
                    logger.warning(f"⚠️ Стандартный формат не сработал, пробуем оригинальный: {e1}")
                    try:
                        # Пробуем с оригинальным форматом (с параметром)
                        original_with_prefix = f"http://{original_url}" if not original_url.startswith(('http://', 'https://')) else original_url
                        proxy = await proxy_manager.add_proxy(original_with_prefix)
                        response_msg = f"✅ Прокси добавлен с оригинальным форматом (ID: {proxy.id})\n📝 URL: {original_with_prefix}"
                        logger.info(f"✅ Прокси добавлен с оригинальным форматом: {original_with_prefix} (ID: {proxy.id})")
                        return True, response_msg, proxy.id
                    except Exception as e2:
                        return False, f"❌ Ошибка: {str(e1)}", None
                else:
                    return False, f"❌ Ошибка: {str(e1)}", None
        except Exception as e:
            logger.error(f"❌ Ошибка добавления прокси: {e}")
            return False, f"❌ Ошибка: {str(e)}", None
    
    async def cmd_add_proxy(self, message: Message, state: FSMContext):
        """Добавляет прокси."""
        await message.answer(
            "🔌 <b>Добавление прокси</b>\n\n"
            "Отправьте URL прокси в формате:\n"
            "<code>user:pass@host:port</code>\n"
            "или\n"
            "<code>http://user:pass@host:port</code>\n\n"
            "💡 Префикс <code>http://</code> добавляется автоматически, если не указан\n\n"
            "📋 <b>Массовое добавление:</b>\n"
            "Можно добавить несколько прокси сразу, каждый на новой строке:\n"
            "<code>user:pass@host:port:country</code>\n"
            "<code>user:pass@host:port:country</code>\n"
            "<code>...</code>\n\n"
            "Или /cancel для отмены",
            parse_mode="HTML"
        )
        await state.set_state(BotStates.waiting_for_proxy)
    
    async def process_proxy_input(self, message: Message, state: FSMContext):
        """Обрабатывает ввод прокси (поддерживает массовое добавление)."""
        if message.text == "/cancel":
            await state.clear()
            await message.answer("❌ Отменено")
            return
        
        # Разбиваем на строки и фильтруем пустые
        lines = [line.strip() for line in message.text.strip().split('\n') if line.strip()]
        
        if not lines:
            await message.answer("❌ Не найдено прокси для добавления")
            await state.clear()
            return
        
        # Определяем, массовое ли это добавление
        is_bulk = len(lines) > 1
        
        session = None
        try:
            # Используем существующий proxy_manager
            if not self.bot.proxy_manager:
                session = await self.bot.db_manager.get_session()
                proxy_manager = ProxyManager(session, redis_service=self.bot.redis_service)
            else:
                proxy_manager = self.bot.proxy_manager
            
            if is_bulk:
                # Массовое добавление
                # Убираем дубликаты из списка перед обработкой
                normalized_urls = {}
                unique_lines = []
                duplicates_in_input = []
                
                for idx, proxy_url in enumerate(lines, 1):
                    normalized, _, _ = self.normalize_proxy_url(proxy_url)
                    if normalized not in normalized_urls:
                        normalized_urls[normalized] = idx
                        unique_lines.append((idx, proxy_url))
                    else:
                        duplicates_in_input.append((idx, proxy_url, normalized_urls[normalized]))
                
                if duplicates_in_input:
                    dup_msg = f"⚠️ Найдено {len(duplicates_in_input)} дубликатов во входных данных (будут пропущены):\n"
                    for dup_idx, dup_url, first_idx in duplicates_in_input[:10]:  # Показываем первые 10
                        dup_msg += f"  • Строка {dup_idx}: {dup_url[:50]}... (дубликат строки {first_idx})\n"
                    if len(duplicates_in_input) > 10:
                        dup_msg += f"  ... и еще {len(duplicates_in_input) - 10} дубликатов\n"
                    await message.answer(dup_msg)
                
                await message.answer(f"📋 Обработка {len(unique_lines)} уникальных прокси...")
                
                results = []
                success_count = 0
                fail_count = 0
                skipped_count = 0
                
                for original_idx, proxy_url in unique_lines:
                    success, msg, proxy_id = await self.add_single_proxy(proxy_url, proxy_manager)
                    
                    if success:
                        if "уже существует" in msg.lower() or "already exists" in msg.lower():
                            skipped_count += 1
                            results.append(f"{original_idx}. ⏭️ Пропущен (уже существует): ID={proxy_id}")
                        else:
                            success_count += 1
                            results.append(f"{original_idx}. ✅ ID: {proxy_id}")
                    else:
                        fail_count += 1
                        results.append(f"{original_idx}. ❌ {msg.split('❌')[1].strip() if '❌' in msg else 'Ошибка'}")
                
                # Формируем итоговое сообщение
                result_text = f"📊 <b>Результаты добавления прокси:</b>\n\n"
                result_text += f"✅ Успешно добавлено: {success_count}\n"
                result_text += f"⏭️ Пропущено (уже существует): {skipped_count}\n"
                result_text += f"❌ Ошибок: {fail_count}\n"
                if duplicates_in_input:
                    result_text += f"🔄 Дубликатов во входных данных: {len(duplicates_in_input)}\n"
                result_text += "\n"
                
                if success_count > 0:
                    result_text += "<b>Добавленные прокси:</b>\n"
                    for result in results:
                        if "✅" in result:
                            result_text += f"{result}\n"
                
                if fail_count > 0:
                    result_text += f"\n<b>Ошибки:</b>\n"
                    for result in results:
                        if "❌" in result:
                            result_text += f"{result}\n"
                
                await message.answer(result_text, parse_mode="HTML")
            else:
                # Одиночное добавление
                proxy_url = lines[0]
                success, msg, proxy_id = await self.add_single_proxy(proxy_url, proxy_manager)
                await message.answer(msg)
                
        except Exception as e:
            await message.answer(
                f"❌ Критическая ошибка: {str(e)}\n\n"
                f"💡 Попробуйте добавить прокси по одному"
            )
            logger.error(f"❌ Критическая ошибка при добавлении прокси: {e}")
        finally:
            # Закрываем session только если он был создан
            if session is not None:
                try:
                    await session.close()
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка при закрытии session: {e}")
        
        await state.clear()
    
    async def cmd_cleanup_duplicates(self, message: Message):
        """Очищает дубликаты прокси из базы данных."""
        session = None
        try:
            if not self.bot.proxy_manager:
                session = await self.bot.db_manager.get_session()
                proxy_manager = ProxyManager(session, redis_service=self.bot.redis_service)
            else:
                proxy_manager = self.bot.proxy_manager
            
            await message.answer("🔍 Проверяю прокси на дубликаты...")
            
            result = await proxy_manager.remove_duplicate_proxies()
            
            result_text = f"📊 <b>Результаты очистки дубликатов:</b>\n\n"
            result_text += f"✅ Оставлено уникальных: {result['kept']}\n"
            result_text += f"🗑️ Удалено дубликатов: {result['removed']}\n"
            
            if result['removed'] == 0:
                result_text += "\n✅ Дубликатов не найдено!"
            else:
                result_text += f"\n✅ Очистка завершена!"
            
            await message.answer(result_text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка при очистке дубликатов: {str(e)}")
            logger.error(f"❌ Ошибка при очистке дубликатов: {e}")
        finally:
            if session is not None:
                try:
                    await session.close()
                except:
                    pass
    
    async def cmd_delete_proxy(self, message: Message):
        """Удаляет прокси."""
        try:
            proxy_id = int(message.text.split()[1])
            # Используем существующий proxy_manager с redis_service для обновления кэша
            if not self.bot.proxy_manager:
                session = await self.bot.db_manager.get_session()
                proxy_manager = ProxyManager(session, redis_service=self.bot.redis_service)
                await session.close()
            else:
                proxy_manager = self.bot.proxy_manager
            success = await proxy_manager.delete_proxy(proxy_id)
            
            if success:
                await message.answer(f"✅ Прокси #{proxy_id} удален")
            else:
                await message.answer(f"❌ Прокси #{proxy_id} не найден")
        except (IndexError, ValueError):
            await message.answer("❌ Использование: /delete_proxy [id]")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
            logger.error(f"Ошибка удаления прокси: {e}")

