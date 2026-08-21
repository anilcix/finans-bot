"""AJAN 8: Top 200 coin tarayıcı — CoinGecko spot + Coinalyze türev teyidi.

Akış:
1) CoinGecko Top 200 içinde olağandışı spot aktiviteyi Hacim/MCap ile seç.
2) Coinalyze desteklenen perpetual piyasalarından her coin için tercih edilen kontratı bul.
3) En fazla 18 adayda 24s Open Interest değişimini hesapla.
4) En güçlü en fazla 6 adayda funding, long/short ve 24s liquidations ile sinyali zenginleştir.

Coinalyze ücretsiz API limiti 40 sembol-çağrı/dk olduğu için varsayılan bütçe
18 OI + 6 funding + 6 liquidation + 6 long/short + 2 metadata = 38 çağrı eşdeğeridir.
"""
from datetime import datetime, timedelta, timezone
import os
import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINALYZE_BASE = "https://api.coinalyze.net/v1"
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0)", "Accept": "application/json"}

PREFERRED_EXCHANGES = ("binance", "bybit", "okx", "hyperliquid", "bitget", "kraken", "deribit")
PREFERRED_QUOTES = ("USDT", "USDC", "USD")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pct_change(now, old):
    if now is None or old in (None, 0):
        return None
    return (now / old - 1) * 100


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
        headers=UA,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _key():
    key = (os.getenv("COINALYZE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("COINALYZE_API_KEY GitHub Actions secret olarak tanımlı değil")
    return key


def _ca_get(path, params=None):
    r = requests.get(
        f"{COINALYZE_BASE}{path}",
        params=params or {},
        headers={**UA, "api_key": _key()},
        timeout=20,
    )
    if r.status_code == 429:
        raise RuntimeError(f"Coinalyze rate limit aşıldı; Retry-After={r.headers.get('Retry-After', '—')}")
    r.raise_for_status()
    return r.json()


def _exchange_map():
    rows = _ca_get("/exchanges")
    return {str(x.get("code")): str(x.get("name") or x.get("code")) for x in rows if x.get("code") is not None}


def _future_markets():
    rows = _ca_get("/future-markets")
    return rows if isinstance(rows, list) else []


def _exchange_rank(name):
    low = (name or "").lower()
    for i, wanted in enumerate(PREFERRED_EXCHANGES):
        if wanted in low:
            return i
    return len(PREFERRED_EXCHANGES) + 5


def _quote_rank(quote):
    q = (quote or "").upper()
    try:
        return PREFERRED_QUOTES.index(q)
    except ValueError:
        return len(PREFERRED_QUOTES) + 5


def _select_contracts(markets, exchange_names, candidate_symbols):
    wanted = {s.upper() for s in candidate_symbols}
    grouped = {}
    for m in markets:
        base = str(m.get("base_asset") or "").upper()
        if base not in wanted or not m.get("is_perpetual"):
            continue
        symbol = m.get("symbol")
        if not symbol:
            continue
        exchange_code = str(m.get("exchange") or "")
        exchange_name = exchange_names.get(exchange_code, exchange_code)
        quote = str(m.get("quote_asset") or "").upper()
        margin = str(m.get("margined") or "").upper()
        rank = (
            0 if margin == "STABLE" else 1,
            _exchange_rank(exchange_name),
            _quote_rank(quote),
        )
        row = {
            "symbol": symbol,
            "base": base,
            "exchange": exchange_name,
            "exchange_code": exchange_code,
            "symbol_on_exchange": m.get("symbol_on_exchange"),
            "quote": quote,
            "has_long_short_ratio_data": bool(m.get("has_long_short_ratio_data")),
        }
        if base not in grouped or rank < grouped[base][0]:
            grouped[base] = (rank, row)
    return {base: row for base, (_, row) in grouped.items()}


def _batches(items, n=20):
    for i in range(0, len(items), n):
        yield items[i:i+n]


def _oi_history(contract_rows, hours=25):
    now = datetime.now(timezone.utc)
    params_base = {
        "interval": "1hour",
        "from": int((now - timedelta(hours=hours)).timestamp()),
        "to": int(now.timestamp()),
        "convert_to_usd": "true",
    }
    by_symbol = {}
    symbols = [x["symbol"] for x in contract_rows]
    for batch in _batches(symbols, 20):
        rows = _ca_get("/open-interest-history", {**params_base, "symbols": ",".join(batch)})
        for row in rows or []:
            history = row.get("history") or []
            closes = [_f(x.get("c")) for x in history]
            closes = [x for x in closes if x is not None]
            if len(closes) < 2:
                continue
            by_symbol[row.get("symbol")] = {
                "oi_usd": closes[-1],
                "oi_change_24h": _pct_change(closes[-1], closes[0]),
                "samples": len(closes),
            }
    return by_symbol


def _funding_current(contract_rows):
    symbols = [x["symbol"] for x in contract_rows]
    if not symbols:
        return {}
    rows = _ca_get("/funding-rate", {"symbols": ",".join(symbols)})
    return {x.get("symbol"): _f(x.get("value")) for x in rows or []}


def _liquidations(contract_rows, hours=24):
    symbols = [x["symbol"] for x in contract_rows]
    if not symbols:
        return {}
    now = datetime.now(timezone.utc)
    rows = _ca_get(
        "/liquidation-history",
        {
            "symbols": ",".join(symbols),
            "interval": "1hour",
            "from": int((now - timedelta(hours=hours)).timestamp()),
            "to": int(now.timestamp()),
            "convert_to_usd": "true",
        },
    )
    out = {}
    for row in rows or []:
        longs = shorts = 0.0
        for x in row.get("history") or []:
            longs += abs(_f(x.get("l")) or 0)
            shorts += abs(_f(x.get("s")) or 0)
        out[row.get("symbol")] = {
            "long_liquidations_usd": longs,
            "short_liquidations_usd": shorts,
            "total_liquidations_usd": longs + shorts,
        }
    return out


def _long_short(contract_rows, hours=24):
    eligible = [x for x in contract_rows if x.get("has_long_short_ratio_data")]
    if not eligible:
        return {}
    symbols = [x["symbol"] for x in eligible]
    now = datetime.now(timezone.utc)
    rows = _ca_get(
        "/long-short-ratio-history",
        {
            "symbols": ",".join(symbols),
            "interval": "1hour",
            "from": int((now - timedelta(hours=hours)).timestamp()),
            "to": int(now.timestamp()),
        },
    )
    out = {}
    for row in rows or []:
        hist = row.get("history") or []
        if not hist:
            continue
        last = hist[-1]
        out[row.get("symbol")] = {
            "ratio": _f(last.get("r")),
            "long_pct": _f(last.get("l")),
            "short_pct": _f(last.get("s")),
        }
    return out


def _reading(x):
    price = x.get("change_24h") or 0
    oi = x.get("oi_change_24h") or 0
    funding = x.get("funding_pct")
    ls = x.get("long_short_ratio")
    liq_long = x.get("long_liquidations_usd") or 0
    liq_short = x.get("short_liquidations_usd") or 0

    if price > 4 and oi > 10:
        if funding is not None and funding > 0.05:
            return "Fiyat + OI güçlü ama funding yüksek: momentum var, long kalabalıklaşması riski de artıyor."
        if ls is not None and ls < 0.8:
            return "Fiyat + OI yükseliyor, short tarafı kalabalık: short-squeeze devamı ihtimali var."
        if liq_short > liq_long * 2 and liq_short > 0:
            return "Fiyat + OI yükselişine güçlü short tasfiyeleri eşlik ediyor: squeeze etkisi belirgin."
        return "Fiyat ve OI birlikte yükseliyor: yeni kaldıraçlı momentum girişi var."
    if price < -4 and oi > 10:
        if funding is not None and funding < -0.03:
            return "Fiyat düşerken OI artıyor ve funding negatif: yeni short birikimi güçlü."
        return "Fiyat düşerken OI artıyor: düşüş yönünde yeni kaldıraç ekleniyor."
    if oi > 10 and abs(price) < 2:
        return "Fiyat yatayken OI hızla artıyor: sıkışma sonrası sert hareket riski yükseliyor."
    return "OI artışı güçlü; yön teyidi için fiyat, funding ve pozisyonlanma birlikte izlenmeli."


def scan_top_movers(
    min_volume_mcap_ratio=0.15,
    min_oi_change=10,
    max_results=10,
    max_oi_checks=18,
    detail_checks=6,
):
    coins = _top_200()
    spot_candidates = []
    for c in coins:
        market_cap = c.get("market_cap") or 0
        volume = c.get("total_volume") or 0
        if not market_cap:
            continue
        ratio = volume / market_cap
        if ratio < min_volume_mcap_ratio:
            continue
        spot_candidates.append({
            "symbol": str(c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "price": c.get("current_price"),
            "change_24h": c.get("price_change_percentage_24h") or 0,
            "volume_mcap_ratio": ratio,
            "market_cap_usd": market_cap,
            "spot_volume_24h_usd": volume,
        })

    spot_candidates.sort(key=lambda x: x["volume_mcap_ratio"], reverse=True)
    exchange_names = _exchange_map()
    markets = _future_markets()
    contracts = _select_contracts(markets, exchange_names, [x["symbol"] for x in spot_candidates])

    eligible = []
    for c in spot_candidates:
        contract = contracts.get(c["symbol"])
        if not contract:
            continue
        c = dict(c)
        c["coinalyze_symbol"] = contract["symbol"]
        c["derivatives_symbol"] = contract.get("symbol_on_exchange")
        c["exchange"] = contract["exchange"]
        c["quote"] = contract["quote"]
        c["has_long_short_ratio_data"] = contract.get("has_long_short_ratio_data")
        eligible.append(c)
        if len(eligible) >= max_oi_checks:
            break

    oi_map = _oi_history(eligible)
    checked = 0
    preliminary = []
    for c in eligible:
        oi = oi_map.get(c["coinalyze_symbol"])
        if not oi or oi.get("oi_change_24h") is None:
            continue
        checked += 1
        row = dict(c)
        row.update(oi)
        if row["oi_change_24h"] >= min_oi_change:
            preliminary.append(row)

    preliminary.sort(key=lambda x: (x["oi_change_24h"], x["volume_mcap_ratio"]), reverse=True)
    details = preliminary[:detail_checks]
    contract_rows = [{
        "symbol": x["coinalyze_symbol"],
        "has_long_short_ratio_data": x.get("has_long_short_ratio_data"),
    } for x in details]

    funding = _funding_current(contract_rows) if contract_rows else {}
    liquidations = _liquidations(contract_rows) if contract_rows else {}
    long_short = _long_short(contract_rows) if contract_rows else {}

    detail_symbols = {x["coinalyze_symbol"] for x in details}
    out = []
    for row in preliminary[:max_results]:
        s = row["coinalyze_symbol"]
        row["oi_source"] = "Coinalyze"
        if s in detail_symbols:
            row["funding_pct"] = funding.get(s)
            row.update(liquidations.get(s) or {})
            ls = long_short.get(s) or {}
            row["long_short_ratio"] = ls.get("ratio")
            row["long_pct"] = ls.get("long_pct")
            row["short_pct"] = ls.get("short_pct")
        row["reading"] = _reading(row)
        out.append(row)

    return out, checked, {
        "spot_candidates": len(spot_candidates),
        "eligible_contracts": len(eligible),
        "details_enriched": len(details),
        "exchange_count": len(exchange_names),
    }


def build_report():
    try:
        movers, checked, meta = scan_top_movers()
    except Exception as e:
        return f"🔍 *TARAYICI*\n⚠️ {e}"

    lines = ["🔍 *TARAYICI — CoinGecko + Coinalyze*"]
    if movers:
        lines.extend(
            f"• {x['symbol']}: OI {x['oi_change_24h']:+.1f}% · Fiyat {x['change_24h']:+.1f}% · {x['exchange']}"
            for x in movers
        )
    else:
        lines.append(f"Kriterleri geçen coin yok. OI kontrol edilen kontrat: {checked}")
    return "\n".join(lines)


def get_analysis_data():
    try:
        movers, checked, meta = scan_top_movers()
        return {
            "movers": movers,
            "window": "24h",
            "rule": "CoinGecko Hacim/MCap >= 0.15 + Coinalyze OI 24s artışı >= %10",
            "oi_source": "Coinalyze",
            "derivatives_source": "Coinalyze",
            "oi_contracts_checked": checked,
            "scan_meta": meta,
            "rate_limit_design": "40 çağrı/dk limitine göre: 18 OI adayı + en güçlü 6 adayda funding/liquidation/long-short.",
        }
    except Exception as e:
        return {
            "movers": [],
            "window": "24h",
            "rule": "CoinGecko Hacim/MCap >= 0.15 + Coinalyze OI 24s artışı >= %10",
            "oi_source": "Coinalyze",
            "derivatives_source": "Coinalyze",
            "oi_contracts_checked": 0,
            "error": str(e),
        }
