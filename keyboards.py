"""
Клавіатури (ReplyKeyboardMarkup) для Telegram-бота.

Всі клавіатури використовують ReplyKeyboardMarkup,
щоб користувач міг швидко обрати потрібну дію.
"""

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from config import AVAILABLE_CURRENCIES, CRYPTO_IDS, FIAT_CURRENCIES


# ── Головне меню ────────────────────────────────────────────────────────────

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Головна клавіатура бота."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Курси валют")],
            [KeyboardButton(text="🔄 Конвертація"), KeyboardButton(text="ℹ️ Допомога")],
        ],
        resize_keyboard=True,
    )


# ── Вибір валюти-джерела ────────────────────────────────────────────────────

def from_currency_kb() -> ReplyKeyboardMarkup:
    """Клавіатура вибору валюти, З якої конвертуємо."""
    buttons = []
    row: list[KeyboardButton] = []

    for symbol in AVAILABLE_CURRENCIES:
        row.append(KeyboardButton(text=symbol))
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([KeyboardButton(text="⬅️ Назад")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# ── Вибір цільової валюти ───────────────────────────────────────────────────

def to_currency_kb(exclude: str = "") -> ReplyKeyboardMarkup:
    """
    Клавіатура вибору цільової валюти (В яку конвертуємо).

    Параметр exclude виключає валюту-джерело зі списку,
    щоб не конвертувати валюту саму в себе.
    """
    buttons = []
    row: list[KeyboardButton] = []

    for symbol in AVAILABLE_CURRENCIES:
        if symbol.upper() == exclude.upper():
            continue
        row.append(KeyboardButton(text=symbol))
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([KeyboardButton(text="⬅️ Скасувати")])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# ── Скасування ──────────────────────────────────────────────────────────────

def cancel_kb() -> ReplyKeyboardMarkup:
    """Клавіатура зі кнопкою скасування."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Скасувати")]],
        resize_keyboard=True,
    )
