"""
Состояния FSM для Telegram бота.
"""
from aiogram.fsm.state import State, StatesGroup


class BotStates(StatesGroup):
    """Состояния FSM для бота."""
    waiting_for_proxy = State()
    waiting_for_task_name = State()
    waiting_for_item_name = State()
    waiting_for_wear_selection = State()  # Выбор степени износа
    waiting_for_max_price = State()
    waiting_for_float_min = State()
    waiting_for_float_max = State()
    waiting_for_patterns = State()
    waiting_for_item_type = State()
    waiting_for_stickers_overpay = State()  # Максимальный коэффициент переплаты за наклейки
    waiting_for_stickers_min_price = State()  # Минимальная цена наклеек для формулы

