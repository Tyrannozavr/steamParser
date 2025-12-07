"""
Клавиатуры для Telegram бота.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from loguru import logger


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Создает основную клавиатуру с частыми командами."""
    logger.info("🔍 DEBUG: Создание основной клавиатуры...")
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статус"),
                KeyboardButton(text="📋 Задачи")
            ],
            [
                KeyboardButton(text="🔌 Прокси"),
                KeyboardButton(text="🔍 Найдено")
            ],
            [
                KeyboardButton(text="➕ Добавить прокси"),
                KeyboardButton(text="➕ Добавить задачу")
            ],
            [
                KeyboardButton(text="🔍 Проверить прокси"),
                KeyboardButton(text="❓ Помощь")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False  # Клавиатура остается видимой
    )
    
    logger.info(f"🔍 DEBUG: Основная клавиатура создана с {len(keyboard.keyboard)} рядами")
    logger.info(f"🔍 DEBUG: Ряд 4 содержит: {[btn.text for btn in keyboard.keyboard[3]]}")
    
    return keyboard


def get_skip_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с кнопкой 'Skip'."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Skip", callback_data="skip")]
    ])

