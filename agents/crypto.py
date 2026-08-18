"""AJAN 3: KRİPTO — CoinGecko + Binance Futures, OKX fallback."""
import requests
from common.report import safe_line, price_change_line, val_line, unavailable_note

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
OKX_BASE = "https://www.okx.com/api/v5"


def _okx(path, params):
    r = requests.get(f"{OKX_BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != "0" or not payload.get("data"):
        raise ValueError(payload.get("msg") or "OKX veri döndürmedi")
    return payload["data"]


def _btc_eth():
    r = requests.get(
        f"{COINGECKO_BASE}/simple/price",
        params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    return "\n".join(
        price_change_line(label, d[key]["usd"], d[key].get("usd_24h_change"))
        for key, label in [("bitcoin", "BTC"), ("ethereum", "ETH")]
    )


def _global_market():
    r = requests.get(f"{COINGECKO_BASE}/global", timeout=15)
    r.raise_for_status()
    d = r.json()["data"]
    total = d["total_market_cap"]["usd"]
    btc = d["market_cap_percentage"]["btc"]
    eth = d["market_cap_percentage"].get("eth", 0)
    return "\n".join(
        [
            val_line("BTC Dominance", btc, suffix="%", emoji="🟠"),
            val_line("TOTAL", total / 1e12, suffix="T $", emoji="🌐"),
            val_line("TOTAL2", total * (1 - btc / 100) / 1e12, suffix="T $", emoji="🌐"),
            val_line("TOTAL3", total * (1 - btc / 100 - eth / 100) / 1e12, suffix="T $", emoji="🌐"),
        ]
    )


def _stablecoin_supply():
    r = requests.get(
        f"{COINGECKO_BASE}/coins/markets",
        params={"vs_currency": "usd", "category": "stablecoins", "order": "market_cap_desc", "per_page": 50},
        timeout=15,
    )
    r.raise_for_status()
    return val_line(
        "Stablecoin Toplam Arzı",
        sum(c.get("market_cap", 0) or 0 for c in r.json()) / 1e9,
        suffix="B $",
        emoji="🪙",
        decimals=1,
    )


def _funding_value():
    try:
        r = requests.get(
            f"{BINANCE_FAPI}/premiumIndex",
            params={"symbol": "BTCUSDT"},
            timeout=6,
        )
        r.raise_for_status()
        return float(r.json()["lastFundingRate"]) * 100, "Binance"
    except Exception:
        rows = _okx(
            "/public/funding-rate-history",
            {"instId": "BTC-USDT-SWAP", "limit": 1},
        )
        row = rows[0]
        rate = row.get("realizedRate") or row.get("fundingRate")
        return float(rate) * 100, "OKX"


def _open_interest_value():
    try:
        r = requests.get(
            f"{BINANCE_FAPI}/openInterest",
            params={"symbol": "BTCUSDT"},
            timeout=6,
        )
        r.raise_for_status()
        return float(r.json()["openInterest"]), "Binance"
    except Exception:
        row = _okx(
            "/public/open-interest",
            {"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
        )[0]
        return float(row["oiCcy"]), "OKX"


def _funding_rate():
    rate, source = _funding_value()
    return f"💰 BTC Funding Rate ({source}): %{rate:+.4f}"


def _open_interest():
    value, source = _open_interest_value()
    return val_line(f"BTC Open Interest ({source})", value, suffix=" BTC", emoji="📐", decimals=0)


def build_report():
    lines = [
        "₿ *KRİPTO*",
        safe_line("BTC/ETH Fiyatları", _btc_eth),
        safe_line("Piyasa Genel Görünümü", _global_market),
        safe_line("Stablecoin Arzı", _stablecoin_supply),
        safe_line("Funding Rate", _funding_rate),
        safe_line("Open Interest", _open_interest),
        "",
        unavailable_note(
            ["Exchange Reserves", "ETF Flows", "CVD", "Liquidations", "MVRV", "NUPL", "SOPR", "Miner Reserves", "LTH Supply"]
        ),
    ]
    return "\n".join(lines)


def get_analysis_data():
    data = {
        "btc": None,
        "eth": None,
        "global": None,
        "stablecoin_supply_usd": None,
        "funding_pct": None,
        "funding_source": None,
        "open_interest_btc": None,
        "open_interest_source": None,
    }
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        data["btc"] = {"price": d["bitcoin"]["usd"], "change_24h": d["bitcoin"].get("usd_24h_change")}
        data["eth"] = {"price": d["ethereum"]["usd"], "change_24h": d["ethereum"].get("usd_24h_change")}
    except Exception:
        pass

    try:
        r = requests.get(f"{COINGECKO_BASE}/global", timeout=15)
        r.raise_for_status()
        d = r.json()["data"]
        total = d["total_market_cap"]["usd"]
        btc = d["market_cap_percentage"]["btc"]
        eth = d["market_cap_percentage"].get("eth", 0)
        data["global"] = {
            "total_usd": total,
            "total2_usd": total * (1 - btc / 100),
            "total3_usd": total * (1 - btc / 100 - eth / 100),
            "btc_dominance": btc,
            "eth_dominance": eth,
        }
    except Exception:
        pass

    try:
        r = requests.get(
            f"{COINGECKO_BASE}/coins/markets",
            params={"vs_currency": "usd", "category": "stablecoins", "order": "market_cap_desc", "per_page": 50},
            timeout=15,
        )
        r.raise_for_status()
        data["stablecoin_supply_usd"] = sum(c.get("market_cap", 0) or 0 for c in r.json())
    except Exception:
        pass

    try:
        data["funding_pct"], data["funding_source"] = _funding_value()
    except Exception:
        pass

    try:
        data["open_interest_btc"], data["open_interest_source"] = _open_interest_value()
    except Exception:
        pass

    return data
