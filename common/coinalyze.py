"""Coinalyze ücretsiz API key ile çoklu-borsa BTC türev verisi.

COINALYZE_API_KEY yoksa sessizce devre dışı kalır.
Büyük borsalardan birer temsilci BTC perpetual kontratı seçer; OI, funding,
liquidation ve long/short verilerini hem borsa bazında hem agregat olarak döndürür.
Binance doğrudan API erişimi GitHub runner'da engellense bile Coinalyze katmanı
üzerinden Binance verisi görünür tutulur.
"""
from datetime import datetime, timedelta, timezone
import os
import requests

BASE = "https://api.coinalyze.net/v1"
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0)", "Accept": "application/json"}
PREFERRED = ("BINANCE", "BYBIT", "OKX", "HYPERLIQUID", "BITGET", "KRAKEN", "DERIBIT")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _get(path, key, params=None):
    r = requests.get(f"{BASE}/{path}", params=params or {}, headers={**UA, "api_key": key}, timeout=20)
    r.raise_for_status()
    return r.json()


def _canon_exchange(name):
    u = str(name or "").upper()
    for p in PREFERRED:
        if p in u:
            return p.title() if p != "OKX" else "OKX"
    return str(name or "Unknown")


def _pick_markets(rows, limit=7):
    candidates = []
    for x in rows if isinstance(rows, list) else []:
        if str(x.get("base_asset", "")).upper() != "BTC":
            continue
        if not x.get("is_perpetual"):
            continue
        quote = str(x.get("quote_asset", "")).upper()
        if quote not in ("USDT", "USD", "USDC"):
            continue
        exch_raw = str(x.get("exchange", ""))
        exch = _canon_exchange(exch_raw)
        eu = exch.upper()
        pref = next((i for i, p in enumerate(PREFERRED) if p in eu), 99)
        stable = 0 if str(x.get("margined", "")).upper() == "STABLE" else 1
        quote_rank = {"USDT": 0, "USD": 1, "USDC": 2}.get(quote, 9)
        candidates.append((pref, stable, quote_rank, exch, x))
    candidates.sort(key=lambda z: z[:4])

    selected = []
    seen = set()
    for _, _, _, exch, x in candidates:
        if exch in seen:
            continue
        seen.add(exch)
        selected.append(x)
        if len(selected) >= limit:
            break
    return selected


def _hist_map(rows):
    return {x.get("symbol"): x.get("history") or [] for x in rows if isinstance(x, dict)} if isinstance(rows, list) else {}


def fetch_coinalyze_btc():
    key = os.getenv("COINALYZE_API_KEY")
    out = {
        "source": "Coinalyze",
        "configured": bool(key),
        "ok": False,
        "markets": [],
        "by_exchange": {},
        "binance": None,
        "binance_available": False,
        "aggregate_oi_usd": None,
        "oi_change_24h_pct": None,
        "oi_weighted_funding_pct": None,
        "liquidations_24h": None,
        "long_short_ratio_avg": None,
        "note": None,
        "error": None,
    }
    if not key:
        out["note"] = "COINALYZE_API_KEY GitHub Secret olarak tanımlı değil."
        return out

    try:
        markets = _get("future-markets", key)
        picked = _pick_markets(markets, limit=7)
        if not picked:
            raise ValueError("Uygun BTC perpetual market bulunamadı")
        symbols = [x["symbol"] for x in picked]
        symstr = ",".join(symbols)
        now = datetime.now(timezone.utc)
        frm = int((now - timedelta(hours=26)).timestamp())
        to = int(now.timestamp())
        common = {"symbols": symstr, "interval": "1hour", "from": frm, "to": to}

        oi_now = _get("open-interest", key, {"symbols": symstr, "convert_to_usd": "true"})
        fund_now = _get("funding-rate", key, {"symbols": symstr})
        oi_hist = _get("open-interest-history", key, {**common, "convert_to_usd": "true"})
        liq_hist = _get("liquidation-history", key, {**common, "convert_to_usd": "true"})
        ls_hist = _get("long-short-ratio-history", key, common)

        oi_map = {x.get("symbol"): _f(x.get("value")) for x in oi_now if isinstance(x, dict)}
        fund_map = {x.get("symbol"): _f(x.get("value")) for x in fund_now if isinstance(x, dict)}
        oih = _hist_map(oi_hist)
        lqh = _hist_map(liq_hist)
        lsh = _hist_map(ls_hist)

        venue_rows = []
        current_total = old_total = fund_num = fund_den = liq_long = liq_short = 0.0
        old_count = 0
        ratios = []
        by_symbol = {x["symbol"]: x for x in picked}

        for symbol in symbols:
            meta = by_symbol[symbol]
            exchange = _canon_exchange(meta.get("exchange"))
            oi = oi_map.get(symbol)
            fund = fund_map.get(symbol)
            hist = oih.get(symbol) or []
            oi_old = _f(hist[0].get("c")) if hist else None
            oi_change = (oi / oi_old - 1) * 100 if oi is not None and oi_old not in (None, 0) else None
            liqs = lqh.get(symbol) or []
            l_long = sum(_f(x.get("l")) or 0 for x in liqs)
            l_short = sum(_f(x.get("s")) or 0 for x in liqs)
            lsrows = lsh.get(symbol) or []
            ratio = _f(lsrows[-1].get("r")) if lsrows else None

            if oi is not None:
                current_total += oi
            if oi_old is not None:
                old_total += oi_old
                old_count += 1
            if oi is not None and fund is not None:
                fund_num += oi * fund
                fund_den += oi
            liq_long += l_long
            liq_short += l_short
            if ratio is not None:
                ratios.append(ratio)

            row = {
                "exchange": exchange,
                "exchange_raw": meta.get("exchange"),
                "symbol": symbol,
                "symbol_on_exchange": meta.get("symbol_on_exchange"),
                "open_interest_usd": oi,
                "open_interest_24h_ago_usd": oi_old,
                "open_interest_change_24h_pct": oi_change,
                "funding_pct": fund,
                "long_short_ratio": ratio,
                "long_liquidations_24h_usd": l_long,
                "short_liquidations_24h_usd": l_short,
                "total_liquidations_24h_usd": l_long + l_short,
            }
            venue_rows.append(row)
            out["by_exchange"][exchange] = row

        out["markets"] = venue_rows
        out["binance"] = out["by_exchange"].get("Binance")
        out["binance_available"] = bool(out["binance"])
        out["aggregate_oi_usd"] = current_total if current_total > 0 else None
        if current_total > 0 and old_count and old_total > 0:
            out["oi_change_24h_pct"] = (current_total / old_total - 1) * 100
        if fund_den > 0:
            out["oi_weighted_funding_pct"] = fund_num / fund_den
        out["liquidations_24h"] = {
            "long_usd": liq_long,
            "short_usd": liq_short,
            "total_usd": liq_long + liq_short,
            "dominant_side": "long" if liq_long > liq_short else "short" if liq_short > liq_long else "balanced",
        }
        out["long_short_ratio_avg"] = sum(ratios) / len(ratios) if ratios else None
        out["market_count"] = len(venue_rows)
        out["ok"] = out["aggregate_oi_usd"] is not None or bool(ratios)
        if out["binance_available"]:
            out["note"] = "Binance dahil seçili büyük borsalarda birer temsilci BTC perpetual kontratı kullanılır; tam piyasa toplamı değildir."
        else:
            out["note"] = "Coinalyze çalışıyor ancak bu üretimde seçilen BTC perpetual setinde Binance bulunamadı; diğer büyük borsalar kullanılmaya devam ediyor."
    except Exception as e:
        out["error"] = str(e)[:300]
    return out
