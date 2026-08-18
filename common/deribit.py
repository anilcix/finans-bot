"""
Deribit public API - tamamen ücretsiz, key gerekmez.
Piyasanın çoğunluğunu elinde tutan kripto opsiyon borsası.
"""

import requests
from datetime import datetime, timezone

DERIBIT_BASE = "https://www.deribit.com/api/v2"


def get_book_summary(currency="BTC"):
    """Tüm opsiyon enstrümanlarının özetini (OI, hacim, mark IV) tek çağrıda döner."""
    r = requests.get(
        f"{DERIBIT_BASE}/public/get_book_summary_by_currency",
        params={"currency": currency, "kind": "option"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["result"]


def get_index_price(currency="BTC"):
    r = requests.get(
        f"{DERIBIT_BASE}/public/get_index_price",
        params={"index_name": f"{currency.lower()}_usd"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["result"]["index_price"]


def get_historical_volatility(currency="BTC"):
    """[[timestamp_ms, dvol], ...] - IV Rank/Percentile hesaplamak için."""
    r = requests.get(
        f"{DERIBIT_BASE}/public/get_historical_volatility",
        params={"currency": currency},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["result"]


def parse_instrument_name(name):
    """'BTC-29AUG26-70000-C' formatını (strike, is_call, expiry_datetime) olarak ayrıştırır."""
    parts = name.split("-")
    if len(parts) != 4:
        raise ValueError(f"Beklenmeyen enstrüman adı formatı: {name}")
    _, expiry_str, strike_str, opt_type = parts
    strike = float(strike_str)
    is_call = opt_type == "C"
    expiry = datetime.strptime(expiry_str, "%d%b%y").replace(
        hour=8, tzinfo=timezone.utc
    )
    return strike, is_call, expiry
