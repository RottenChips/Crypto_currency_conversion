"""
Обробники повідомлень та FSM-станів Telegram-бота.

FSM (Finite State Machine) використовується для
покрокового процесу конвертації валют:
  1. Вибір валюти-джерела
  2. Введення суми
  3. Вибір цільової валюти
  4. Відображення результату
"""

import asyncio
import logging
import time
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import (
    AVAILABLE_CURRENCIES,
    WELCOME_TEXT,
    HELP_TEXT,
    CRYPTO_IDS,
    FIAT_CURRENCIES,
    COINGECKO_TIMEOUT,
)
from api_client import coingecko
from keyboards import (
    main_menu_kb,
    from_currency_kb,
    to_currency_kb,
    cancel_kb,
)

logger = logging.getLogger(__name__)
router = Router()


# ── FSM-стани ───────────────────────────────────────────────────────────────




class ConvertState(StatesGroup):
    """Стани процесу конвертації."""
    waiting_from_currency = State()
    waiting_amount = State()
    waiting_to_currency = State()


# ── Допоміжні функції ───────────────────────────────────────────────────────

def _format_rate(value: float, currency: str) -> str:
    """Форматує число залежно від типу валюти."""
    if currency.upper() in CRYPTO_IDS.values():
        # Для крипто — 2 знаки після коми
        return f"{value:,.2f}"
    else:
        # Для фіатних — 4 знаки для UAH, 2 для інших
        if currency.upper() == "UAH":
            return f"{value:,.2f}"
        return f"{value:,.4f}"


def _currency_emoji(symbol: str) -> str:
    """Повертає емодзі для валюти."""
    emojis = {
        "USD": "💵", "EUR": "🇪🇺", "UAH": "🇺🇦",
        "BTC": "₿", "ETH": "⟠", "SOL": "◎",
    }
    return emojis.get(symbol.upper(), "💱")


# ── Команда /start ──────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обробник команди /start."""
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


# ── Курси валют ─────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Курси валют")
async def show_rates(message: Message, state: FSMContext) -> None:
    """Показує актуальні курси криптовалют до фіатних валют."""
    await state.clear()

    wait_msg = await message.answer("⏳ Отримую актуальні курси...")

    try:
        rates = await coingecko.get_all_rates()
    except Exception:
        await wait_msg.edit_text(
            "❌ Не вдалося отримати курси. Спробуйте пізніше."
        )
        return

    lines = ["📊 Актуальні курси криптовалют\n"]

    for symbol in CRYPTO_IDS.values():
        data = rates.get(symbol, {})
        if not data:
            continue

        emoji = _currency_emoji(symbol)
        lines.append(f"{emoji} {symbol}")

        for fiat in FIAT_CURRENCIES:
            price = data.get(fiat)
            if price is not None:
                formatted = _format_rate(price, fiat)
                fiat_emoji = _currency_emoji(fiat)
                lines.append(f"   {fiat_emoji} {fiat.upper()}: {formatted}")
        lines.append("")  # порожній рядок між валютами

    # Додаємо крос-курси фіатних валют
    fiat_rates = rates.get("fiat_rates", {})
    if fiat_rates:
        lines.append("💱 Крос-курси фіатних валют\n")
        pairs_to_show = [
            ("USD_UAH", "USD → UAH"),
            ("EUR_UAH", "EUR → UAH"),
            ("USD_EUR", "USD → EUR"),
        ]
        for key, label in pairs_to_show:
            rate = fiat_rates.get(key)
            if rate:
                lines.append(f"   {label}: {rate:.4f}")

    await wait_msg.edit_text("\n".join(lines))
    await message.answer("⬇️ Головне меню", reply_markup=main_menu_kb())


# ── Початок конвертації ─────────────────────────────────────────────────────

@router.message(F.text == "🔄 Конвертація")
async def start_conversion(message: Message, state: FSMContext) -> None:
    """Починає процес конвертації — вибір валюти-джерела."""
    await state.set_state(ConvertState.waiting_from_currency)
    await message.answer(
        "🔄 Конвертація валют\n\n"
        "Оберіть валюту, З якої бажаєте конвертувати:",
        reply_markup=from_currency_kb(),
    )


# ── Вибір валюти-джерела ───────────────────────────────────────────────────

@router.message(
    ConvertState.waiting_from_currency,
    F.text.in_(list(AVAILABLE_CURRENCIES.keys())),
)
async def process_from_currency(message: Message, state: FSMContext) -> None:
    """Зберігає валюту-джерело та запитує суму."""
    from_currency = message.text.strip().upper()
    await state.update_data(from_currency=from_currency)

    emoji = _currency_emoji(from_currency)
    await state.set_state(ConvertState.waiting_amount)
    await message.answer(
        f"{emoji} Обрано: {from_currency}\n\n"
        f"Введіть суму для конвертації (наприклад: 100):",
        reply_markup=cancel_kb(),
    )


# ── Введення суми ───────────────────────────────────────────────────────────

@router.message(ConvertState.waiting_amount, F.text)
async def process_amount(message: Message, state: FSMContext) -> None:
    """Зберігає суму та переходить до вибору цільової валюти."""
    text = message.text.strip().replace(",", ".").replace(" ", "")

    try:
        amount = Decimal(text)
        if amount <= 0:
            raise ValueError("Сума має бути більшою за нуль")
    except (InvalidOperation, ValueError):
        await message.answer(
            "⚠️ Введіть коректне додатне число.\n"
            "Наприклад: 100 або 0.5"
        )
        return

    await state.update_data(amount=float(amount))

    data = await state.get_data()
    from_currency = data["from_currency"]

    await state.set_state(ConvertState.waiting_to_currency)
    await message.answer(
        f"💰 Сума: {amount} {from_currency}\n\n"
        "Оберіть валюту, В яку бажаєте конвертувати:",
        reply_markup=to_currency_kb(exclude=from_currency),
    )


# ── Вибір цільової валюти та результат ──────────────────────────────────────

@router.message(
    ConvertState.waiting_to_currency,
    F.text.in_(list(AVAILABLE_CURRENCIES.keys())),
)
async def process_to_currency(message: Message, state: FSMContext) -> None:
    """Обчислює та відображає результат конвертації."""
    to_currency = message.text.strip().upper()

    data = await state.get_data()
    from_currency = data["from_currency"]
    amount = data["amount"]

    await state.clear()

    wait_msg = await message.answer("⏳ Обчислюю...")
    started_at = time.monotonic()
    logger.info(
        "КРОК 1/4: старт конвертації: %f %s -> %s",
        amount, from_currency, to_currency,
    )

    try:
        logger.info("КРОК 2/4: виклик coingecko.convert()")
        result = await asyncio.wait_for(
            coingecko.convert(amount, from_currency, to_currency),
            timeout=COINGECKO_TIMEOUT + 3,
        )
        logger.info(
            "КРОК 3/4: convert завершено за %.2fs, result=%s",
            time.monotonic() - started_at,
            result,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Таймаут конвертації після %.2fs: %f %s -> %s",
            time.monotonic() - started_at,
            amount, from_currency, to_currency,
        )
        await wait_msg.edit_text(
            "⏰ Час очікування вичерпано. CoinGecko API не відповідає.\n"
            "Спробуйте пізніше."
        )
        await message.answer("⬇️ Головне меню", reply_markup=main_menu_kb())
        return
    except Exception:
        logger.exception("Помилка конвертації: %f %s -> %s", amount, from_currency, to_currency)
        await wait_msg.edit_text(
            "❌ Не вдалося отримати курси для конвертації. Спробуйте пізніше."
        )
        await message.answer("⬇️ Головне меню", reply_markup=main_menu_kb())
        return

    if result is None:
        await wait_msg.edit_text(
            "❌ Не вдалося знайти курс для цієї пари валют."
        )
        await message.answer("⬇️ Головне меню", reply_markup=main_menu_kb())
        return

    from_emoji = _currency_emoji(from_currency)
    to_emoji = _currency_emoji(to_currency)

    # Визначаємо форматування результату
    result_str = _format_rate(result, to_currency)
    final_text = (
        f"✅ Результат конвертації\n\n"
        f"{from_emoji} {amount:,.2f} {from_currency}\n"
        f"⬇️\n"
        f"{to_emoji} {result_str} {to_currency}\n\n"
        f"Курс: 1 {from_currency} = {_format_rate(result / amount, to_currency)} {to_currency}"
    )

    logger.info("КРОК 4/4: відправка edit_text з результатом")
    try:
        await asyncio.wait_for(
            wait_msg.edit_text(final_text),
            timeout=12,
        )
        await message.answer("⬇️ Головне меню", reply_markup=main_menu_kb())
        logger.info("Готово: результат відправлено за %.2fs", time.monotonic() - started_at)
    except asyncio.TimeoutError:
        logger.error(
            "Таймаут на edit_text після %.2fs, надсилаю результат новим повідомленням",
            time.monotonic() - started_at,
        )
        await message.answer(final_text, reply_markup=main_menu_kb())
    except Exception:
        logger.exception("Помилка edit_text, надсилаю результат новим повідомленням")
        await message.answer(final_text, reply_markup=main_menu_kb())


# ── Допомога ────────────────────────────────────────────────────────────────

@router.message(F.text == "ℹ️ Допомога")
async def show_help(message: Message, state: FSMContext) -> None:
    """Показує інструкцію з використання."""
    await state.clear()
    await message.answer(HELP_TEXT, reply_markup=main_menu_kb())


# ── Кнопки «Назад» / «Скасувати» ───────────────────────────────────────────

@router.message(F.text.in_(["⬅️ Назад", "⬅️ Скасувати"]))
async def cancel_action(message: Message, state: FSMContext) -> None:
    """Скасовує поточну дію та повертає до головного меню."""
    await state.clear()
    await message.answer("🔄 Повернуто до головного меню.", reply_markup=main_menu_kb())


# ── Обробка невідомих повідомлень ───────────────────────────────────────────

@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    """Обробляє всі нерозпізнані повідомлення."""
    current_state = await state.get_state()

    if current_state == ConvertState.waiting_from_currency:
        await message.answer(
            "⚠️ Будь ласка, оберіть валюту з клавіатури нижче."
        )
    elif current_state == ConvertState.waiting_amount:
        await message.answer(
            "⚠️ Введіть числове значення суми або натисніть «Скасувати»."
        )
    elif current_state == ConvertState.waiting_to_currency:
        await message.answer(
            "⚠️ Будь ласка, оберіть цільову валюту з клавіатури нижче."
        )
    else:
        await message.answer(
            "🤔 Не розумію команду. Скористайтеся кнопками нижче 👇",
            reply_markup=main_menu_kb(),
        )
