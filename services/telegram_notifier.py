"""
Вспомогательный модуль для отправки уведомлений в Telegram.
Используется для уведомлений о проблемах с прокси.
"""
import asyncio
from typing import Optional
from loguru import logger

from core.config import Config


async def send_telegram_notification(message: str, chat_id: Optional[str] = None) -> bool:
    """
    Отправляет уведомление в Telegram.
    
    Args:
        message: Текст сообщения
        chat_id: ID чата (по умолчанию из Config.TELEGRAM_CHAT_ID)
        
    Returns:
        True если уведомление отправлено, False в противном случае
    """
    try:
        chat_id = chat_id or Config.TELEGRAM_CHAT_ID
        token = Config.TELEGRAM_BOT_TOKEN
        
        if not token or not chat_id:
            logger.debug("⚠️ TelegramNotifier: Токен или chat_id не настроены, пропускаем уведомление")
            return False
        
        # Импортируем aiogram только при необходимости
        try:
            from aiogram import Bot
        except ImportError:
            logger.warning("⚠️ TelegramNotifier: aiogram не установлен, пропускаем уведомление")
            return False
        
        bot = Bot(token=token)
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
            logger.info(f"✅ TelegramNotifier: Уведомление отправлено в Telegram")
            return True
        finally:
            await bot.session.close()
            
    except Exception as e:
        logger.error(f"❌ TelegramNotifier: Ошибка при отправке уведомления в Telegram: {e}")
        return False


async def send_proxy_unavailable_notification(blocked_count: int, total_count: int, oldest_proxy_delay: float) -> bool:
    """
    Отправляет уведомление о том, что все прокси недоступны (все 429).
    
    Args:
        blocked_count: Количество заблокированных прокси
        total_count: Общее количество прокси
        oldest_proxy_delay: Задержка для самого старого прокси (секунды)
        
    Returns:
        True если уведомление отправлено
    """
    message = (
        f"🚨 <b>КРИТИЧНО: Все прокси заблокированы (429)</b>\n\n"
        f"❌ Все прокси временно недоступны из-за 429 ошибок:\n"
        f"• Заблокировано: <b>{blocked_count}/{total_count}</b>\n"
        f"• Причина: Too Many Requests от Steam API\n"
        f"• Ожидание разблокировки: ~{oldest_proxy_delay/60:.1f} мин\n\n"
        f"⚠️ Система не может выполнять парсинг до разблокировки прокси.\n"
        f"🔄 Автоматическая проверка и разблокировка активна."
    )
    
    return await send_telegram_notification(message)

