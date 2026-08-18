"""AJAN 8: Top 200 coin hacim/OI tarayıcı — CoinGecko + Bybit."""
import requests
import time

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BYBIT_BASE = "https://api.bybit.com"


def _top_200():
    r = requests.get(
        f"{COINGECKO_BASE}/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 200,
            "page": 1,
            "price_change_percentage": "24h",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _bybit_symbols():
    r = requests.get(
        f"{BYBIT_BASE}/v5/market/tickers",
        params={"category": "linear"},
        timeout=20,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(payload.get("retMsg") or "Bybit ticker verisi alınamadı")
    return {x.get("symbol") for x in payload.get("result", {}).get("list", []) if x.get("symbol")}


def _bybit_oi_change(symbol):
    r = requests.get(
        f"{BYBIT_BASE}/v5/market/open-interest",
        params={
            "category": "linear",
            "symbol": symbol,
            "intervalTime": "1h",
            "limit": 25,
        },
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("retCode") != 0:
        raise RuntimeError(payload.get("retMsg") or f"{symbol} OI verisi alınamadı")

    points = payload.get("result", {}).get("list", [])
    points = sorted(points, key=lambda x: int(x.get("timestamp", 0)))
    if len(points) < 2:
        return None

    old = float(points[0].get("openInterest") or 0)
    new = float(points[-1].get("openInterest") or 0)
    if old == 0:
        return None
    return (new - old) / old * 100


def scan_top_movers(
    min_volume_mcap_ratio=0.15,
    min_oi_change=10,
    max_results=10,
    max_oi_checks=35,
):
    bybit_symbols = _bybit_symbols()
    candidates = []

    for c in _top_200():
        market_cap = c.get("market_cap") or 0
        volume = c.get("total_volume") or 0
        if not market_cap:
            continue

        ratio = volume / market_cap
        if ratio < min_volume_mcap_ratio:
            continue

        symbol = c["symbol"].upper()
        bybit_symbol = symbol + "USDT"
        candidates.append(
            {
                "symbol": symbol,
                "name": c["name"],
                "price": c["current_price"],
                "change_24h": c.get("price_change_percentage_24h") or 0,
                "volume_mcap_ratio": ratio,
                "derivatives_symbol": bybit_symbol,
            }
        )

    candidates = sorted(
        candidates, key=lambda x: x["volume_mcap_ratio"], reverse=True
    )[:max_oi_checks]

    out = []
    checked = 0
    for c in candidates:
        if c["derivatives_symbol"] not in bybit_symbols:
            continue
        checked += 1
        try:
            oi_change = _bybit_oi_change(c["derivatives_symbol"])
        except Exception:
            oi_change = None

        if oi_change is not None and oi_change >= min_oi_change:
            c["oi_change_24h"] = oi_change
            c["oi_source"] = "Bybit"
            out.append(c)
        time.sleep(0.08)

    return (
        sorted(out, key=lambda x: x["oi_change_24h"], reverse=True)[:max_results],
        checked,
    )


def build_report():
    try:
        movers, checked = scan_top_movers()
    except Exception as e:
        return f"🔍 *TARAYICI*\n⚠️ {e}"

    lines = ["🔍 *TARAYICI — Top 200 Coin*"]
    if movers:
        lines.extend(
            f"• {x['symbol']}: OI {x['oi_change_24h']:+.1f}% · Hacim/MCap {x['volume_mcap_ratio']:.2f}"
            for x in movers
        )
    else:
        lines.append(f"Kriterleri geçen coin yok. OI kontrol edilen kontrat: {checked}")
    return "\n".join(lines)


def get_analysis_data():
    try:
        movers, checked = scan_top_movers()
        return {
            "movers": movers,
            "window": "24h",
            "rule": "Hacim/MCap >= 0.15 ve OI artışı >= %10",
            "oi_source": "Bybit",
            "oi_contracts_checked": checked,
        }
    except Exception as e:
        return {
            "movers": [],
            "window": "24h",
            "rule": "Hacim/MCap >= 0.15 ve OI artışı >= %10",
            "oi_source": "Bybit",
            "oi_contracts_checked": 0,
            "error": str(e),
        }
