"""
Клієнт для роботи з CoinGecko API.

Отримує курси криптовалют та фіатних валют,
кешує результати для зменшення кількості запитів.
"""

import asyncio
import time
import logging
from typing import Optional

import aiohttp

from config import (
    COINGECKO_BASE_URL,
    COINGECKO_TIMEOUT,
    CRYPTO_IDS,
    FIAT_CURRENCIES,
    CACHE_TTL,
)

logger = logging.getLogger(__name__)


class RatesCache:
    """Простий in-memory кеш з TTL."""

    def __init__(self, ttl: int = CACHE_TTL) -> None:
        self._ttl = ttl
        self._data: Optional[dict] = None
        self._timestamp: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self._data is not None and (time.time() - self._timestamp) < self._ttl

    def get(self) -> Optional[dict]:
        if self.is_valid:
            return self._data
        return None

    def set(self, data: dict) -> None:
        self._data = data
        self._timestamp = time.time()


class CoinGeckoClient:
    """Асинхронний клієнт CoinGecko API."""

    def __init__(self) -> None:
        self._cache = RatesCache()
        self._session: Optional[aiohttp.ClientSession] = None

    async def close(self) -> None:
        """Метод для зворотної сумісності — закриваємо стару сесію, якщо є."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Публічний інтерфейс ─────────────────────────────────────────────

    async def get_all_rates(self) -> dict:
        """
        Повертає словник із курсами всіх валют.

        Структура:
        {
            "BTC": {"usd": 65000.0, "eur": 60000.0, "uah": 2600000.0},
            "ETH": {"usd": 3500.0,  "eur": 3200.0,  "uah": 140000.0},
            "SOL": {"usd": 150.0,   "eur": 138.0,   "uah": 6000.0},
            "fiat_rates": {"USD_UAH": 40.0, "EUR_UAH": 43.0, "USD_EUR": 0.93},
        }
        """
        cached = self._cache.get()
        if cached is not None:
            return cached

        try:
            raw = await self._fetch_crypto_prices()
            rates = self._transform(raw)
            # Додаємо крос-курси фіатних валют
            rates["fiat_rates"] = self._calc_fiat_cross_rates(rates)
            self._cache.set(rates)
            return rates
        except Exception as exc:
            logger.error("Помилка отримання курсів: %s", exc)
            # Якщо є застарілі кешовані дані — повертаємо їх
            if self._cache._data is not None:
                logger.warning("Повертаю застарілі кешовані дані")
                return self._cache._data
            raise

    async def convert(self, amount: float, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Конвертує суму з однієї валюти в іншу.

        Повертає результат або None, якщо курс недоступний.
        """
        logger.info(
            "Конвертація: %f %s -> %s (початок)",
            amount, from_currency, to_currency,
        )

        try:
            rates = await self.get_all_rates()
        except Exception as exc:
            logger.error("Помилка отримання курсів при конвертації: %s", exc)
            raise

        fiat_rates = rates.get("fiat_rates", {})

        from_upper = from_currency.upper()
        to_upper = to_currency.upper()

        if from_upper == to_upper:
            logger.info("Однакова валюта, повертаю суму як є")
            return amount

        result = None

        if from_upper in CRYPTO_IDS.values():
            if to_upper.lower() in FIAT_CURRENCIES:
                result = self._convert_crypto_to_fiat(rates, amount, from_upper, to_upper)
            elif to_upper in CRYPTO_IDS.values():
                result = self._convert_crypto_to_crypto(rates, amount, from_upper, to_upper)
        elif from_upper.lower() in FIAT_CURRENCIES:
            if to_upper in CRYPTO_IDS.values():
                result = self._convert_fiat_to_crypto(rates, amount, from_upper, to_upper)
            elif to_upper.lower() in FIAT_CURRENCIES:
                result = self._convert_fiat_to_fiat(fiat_rates, amount, from_upper, to_upper)

        if result is not None:
            logger.info("Конвертація завершена: %f %s -> %f %s", amount, from_upper, result, to_upper)
        else:
            logger.warning("Курс для пари %s->%s не знайдено", from_upper, to_upper)

        return result

    @staticmethod
    def _convert_crypto_to_fiat(rates: dict, amount: float, from_crypto: str, to_fiat: str) -> Optional[float]:
        rate = rates.get(from_crypto, {}).get(to_fiat.lower())
        return amount * rate if rate else None

    @staticmethod
    def _convert_crypto_to_crypto(rates: dict, amount: float, from_crypto: str, to_crypto: str) -> Optional[float]:
        from_usd = rates.get(from_crypto, {}).get("usd")
        to_usd = rates.get(to_crypto, {}).get("usd")
        if from_usd and to_usd:
            return amount * from_usd / to_usd
        return None

    @staticmethod
    def _convert_fiat_to_crypto(rates: dict, amount: float, from_fiat: str, to_crypto: str) -> Optional[float]:
        rate = rates.get(to_crypto, {}).get(from_fiat.lower())
        return amount / rate if rate else None

    @staticmethod
    def _convert_fiat_to_fiat(fiat_rates: dict, amount: float, from_fiat: str, to_fiat: str) -> Optional[float]:
        key = f"{from_fiat}_{to_fiat}"
        rate = fiat_rates.get(key)
        if rate:
            return amount * rate
        # Спробуємо через зворотній курс
        reverse_key = f"{to_fiat}_{from_fiat}"
        reverse_rate = fiat_rates.get(reverse_key)
        if reverse_rate:
            return amount / reverse_rate
        return None

    # ── Приватні методи ─────────────────────────────────────────────────

    async def _fetch_crypto_prices(self) -> dict:
        """Отримує сирі дані з CoinGecko /simple/price."""
        ids = ",".join(CRYPTO_IDS.keys())
        vs = ",".join(FIAT_CURRENCIES)
        url = f"{COINGECKO_BASE_URL}/simple/price"
        params = {"ids": ids, "vs_currencies": vs}

        logger.info("Запит до CoinGecko: %s params=%s", url, params)

        # Чіткі таймаути на з'єднання/читання + загальний ліміт.
        timeout = aiohttp.ClientTimeout(
            total=COINGECKO_TIMEOUT,
            connect=5,
            sock_connect=5,
            sock_read=5,
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # Контекстно закриваємо response у будь-якому сценарії.
                resp = await asyncio.wait_for(
                    session.get(url, params=params),
                    timeout=COINGECKO_TIMEOUT + 2,
                )
                async with resp:
                    resp.raise_for_status()
                    # Окремий таймаут на читання JSON
                    data = await asyncio.wait_for(
                        resp.json(),
                        timeout=5,
                    )
                    return data
            except asyncio.TimeoutError:
                logger.error("Таймаут запиту до CoinGecko (url=%s)", url)
                raise RuntimeError("CoinGecko API не відповідає (таймаут)")
            except aiohttp.ClientResponseError as exc:
                logger.error("CoinGecko HTTP %d: %s", exc.status, exc.message)
                raise RuntimeError(f"CoinGecko API повернув статус {exc.status}")
            except aiohttp.ClientError as exc:
                logger.error("Помилка з'єднання з CoinGecko: %s", exc)
                raise RuntimeError(f"Помилка з'єднання з CoinGecko: {exc}")

    @staticmethod
    def _transform(raw: dict) -> dict:
        """Перетворює відповідь CoinGecko у зручний формат."""
        rates: dict = {}
        for coin_id, symbol in CRYPTO_IDS.items():
            prices = raw.get(coin_id, {})
            rates[symbol] = {
                fiat: prices.get(fiat) for fiat in FIAT_CURRENCIES if prices.get(fiat) is not None
            }
        return rates

    @staticmethod
    def _calc_fiat_cross_rates(rates: dict) -> dict:
        """
        Обчислює крос-курси фіатних валют через BTC.

        Якщо BTC коштує 65000 USD і 2600000 UAH,
        то USD/UAH = 2600000 / 65000 = 40.0
        """
        fiat_rates: dict = {}
        btc = rates.get("BTC", {})

        if not btc:
            return fiat_rates

        # Будуємо словник fiat → вартість 1 BTC у цій валюті
        btc_prices: dict[str, float] = {}
        for fiat in FIAT_CURRENCIES:
            price = btc.get(fiat)
            if price:
                btc_prices[fiat.upper()] = price

        # Обчислюємо всі пари
        fiat_names = list(btc_prices.keys())
        for i, f1 in enumerate(fiat_names):
            for f2 in fiat_names[i + 1:]:
                rate = btc_prices[f2] / btc_prices[f1]
                fiat_rates[f"{f1}_{f2}"] = round(rate, 6)
                fiat_rates[f"{f2}_{f1}"] = round(btc_prices[f1] / btc_prices[f2], 6)

        # Додаємо 1:1 для однакових валют
        for f in fiat_names:
            fiat_rates[f"{f}_{f}"] = 1.0

        return fiat_rates


# ── Глобальний екземпляр ────────────────────────────────────────────────────
coingecko = CoinGeckoClient()
