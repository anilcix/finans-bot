"""AJAN 8: Top 200 spot akış tarayıcı.

Amaç:
1) CoinGecko piyasa değerine göre Top 200 evrenini al.
2) Binance resmi market-data-only Spot API'de USDT paritesi bulunanları tara.
3) 5 dakikalık klines verisini 10 dakikalık mumlara birleştir.
4) Son tamamlanmış 10dk mumun quote-volume Z-score'unu önceki 30 mumla hesapla.
5) Taker-buy quote volume ile alıcı payı ve spot CVD delta üret.
6) Yüksek Z-score + alıcı baskısı olan coinleri sinyal olarak listele.
7) Son 3 adet 10dk CVD mumundan son 2/3 veya 3/3 yeşilse not düş.

Coinalyze burada kullanılmaz; rate-limit bütçesi Kripto Türev ajanına bırakılır.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import statistics
import time
import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_BASES = (
    "https://data-api.binance.vision",  # resmi market-data-only endpoint
    "https://api-gcp.binance.com",      # resmi yedek public endpoint
)
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0)", "Accept": "application/json"}
STABLES = {"USDT","USDC","DAI","FDUSD","TUSD","USDE","USDS","PYUSD","USD1","USDD","GUSD"}
_ACTIVE_BINANCE_BASE = None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _pct(now, old):
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


def _binance_get(path, params=None, timeout=18):
    global _ACTIVE_BINANCE_BASE
    bases = []
    if _ACTIVE_BINANCE_BASE:
        bases.append(_ACTIVE_BINANCE_BASE)
    bases += [x for x in BINANCE_BASES if x not in bases]
    errors = []
    for base in bases:
        for attempt in range(2):
            try:
                r = requests.get(f"{base}{path}", params=params or {}, headers=UA, timeout=timeout)
                if r.status_code == 429 and attempt == 0:
                    try:
                        wait = float(r.headers.get("Retry-After") or 1.5)
                    except Exception:
                        wait = 1.5
                    time.sleep(max(1.0, min(wait, 5.0)))
                    continue
                r.raise_for_status()
                _ACTIVE_BINANCE_BASE = base
                return r.json()
            except Exception as e:
                errors.append(f"{base}: {str(e)[:100]}")
                break
    raise RuntimeError("Binance Spot public market data alınamadı: " + " | ".join(errors[:2]))


def _spot_symbol_map():
    payload = _binance_get("/api/v3/exchangeInfo")
    out = {}
    for x in payload.get("symbols", []) or []:
        if x.get("status") != "TRADING":
            continue
        if x.get("quoteAsset") != "USDT":
            continue
        if x.get("isSpotTradingAllowed") is False:
            continue
        base = str(x.get("baseAsset") or "").upper()
        symbol = x.get("symbol")
        if base and symbol:
            out[base] = symbol
    return out


def _klines_5m(symbol, limit=90):
    rows = _binance_get(
        "/api/v3/klines",
        params={"symbol": symbol, "interval": "5m", "limit": limit},
    )
    return rows if isinstance(rows, list) else []


def _aggregate_10m(rows):
    """Binance 5m klines -> tamamlanmış 10m mumlar + taker-buy tabanlı CVD delta."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    grouped = {}
    for r in rows:
        if not isinstance(r, list) or len(r) < 11:
            continue
        try:
            open_ts = int(r[0]); close_ts = int(r[6])
            if close_ts >= now_ms:
                continue
            bucket = (open_ts // 600_000) * 600_000
            grouped.setdefault(bucket, []).append(r)
        except Exception:
            continue

    out = []
    for bucket in sorted(grouped):
        bars = sorted(grouped[bucket], key=lambda x: int(x[0]))
        # Tam 10dk için iki tamamlanmış 5dk mum gerekir.
        if len(bars) < 2:
            continue
        bars = bars[-2:]
        if int(bars[1][0]) - int(bars[0][0]) != 300_000:
            continue
        try:
            total_quote = sum(float(x[7]) for x in bars)
            taker_buy_quote = sum(float(x[10]) for x in bars)
            taker_sell_quote = max(0.0, total_quote - taker_buy_quote)
            delta_quote = taker_buy_quote - taker_sell_quote
            o = float(bars[0][1]); c = float(bars[-1][4])
            h = max(float(x[2]) for x in bars); l = min(float(x[3]) for x in bars)
        except Exception:
            continue
        out.append({
            "ts": bucket,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "quote_volume": total_quote,
            "taker_buy_quote": taker_buy_quote,
            "taker_sell_quote": taker_sell_quote,
            "delta_quote": delta_quote,
            "buyer_share_pct": (taker_buy_quote / total_quote * 100) if total_quote else None,
            "price_change_pct": _pct(c, o),
            "price_green": c >= o,
            "cvd_green": delta_quote > 0,
        })
    return out


def _analyze_coin(coin, exchange_symbol, min_z=2.0, min_buyer_share=55.0):
    bars = _aggregate_10m(_klines_5m(exchange_symbol))
    if len(bars) < 22:
        return None
    latest = bars[-1]
    hist = bars[:-1][-30:]
    vols = [x["quote_volume"] for x in hist if x.get("quote_volume") is not None]
    if len(vols) < 20:
        return None
    avg = statistics.mean(vols)
    sd = statistics.pstdev(vols)
    z = (latest["quote_volume"] - avg) / sd if sd else 0.0
    buyer_share = latest.get("buyer_share_pct")

    # "Yüksek alıcılı hacim mumu": sıra dışı hacim + taker buyer üstünlüğü + pozitif spot delta.
    if z < min_z or buyer_share is None or buyer_share < min_buyer_share or latest["delta_quote"] <= 0:
        return None

    last3 = bars[-3:]
    colors = [bool(x["cvd_green"]) for x in last3]
    streak = 0
    for green in reversed(colors):
        if green:
            streak += 1
        else:
            break
    if streak >= 3:
        cvd_note = "✅ Spot CVD son 3×10dk mum yeşil"
    elif streak >= 2:
        cvd_note = "✅ Spot CVD son 2×10dk mum yeşil"
    else:
        cvd_note = "CVD devam teyidi henüz yok"

    score = z + max(0.0, (buyer_share - 50.0) / 10.0) + min(streak, 3) * 0.35
    return {
        "symbol": str(coin.get("symbol") or "").upper(),
        "name": coin.get("name"),
        "coingecko_id": coin.get("id"),
        "exchange": "Binance Spot",
        "exchange_symbol": exchange_symbol,
        "price": coin.get("current_price"),
        "change_24h": coin.get("price_change_percentage_24h") or 0,
        "volume_zscore_10m": z,
        "volume_10m_usd": latest["quote_volume"],
        "volume_mean_10m_usd": avg,
        "buyer_share_pct": buyer_share,
        "taker_buy_10m_usd": latest["taker_buy_quote"],
        "taker_sell_10m_usd": latest["taker_sell_quote"],
        "spot_delta_10m_usd": latest["delta_quote"],
        "price_change_10m_pct": latest["price_change_pct"],
        "price_candle_green": latest["price_green"],
        "cvd_last3": [
            {"ts": x["ts"], "delta_usd": x["delta_quote"], "green": x["cvd_green"]}
            for x in last3
        ],
        "cvd_green_count_3": sum(1 for x in colors if x),
        "cvd_green_streak": streak,
        "cvd_30m_delta_usd": sum(x["delta_quote"] for x in last3),
        "cvd_note": cvd_note,
        "signal_score": score,
        "signal": "Yüksek alıcılı hacim",
        "signal_time_utc": datetime.fromtimestamp(latest["ts"] / 1000, tz=timezone.utc).isoformat(),
    }


def scan_top_movers(min_z=2.0, min_buyer_share=55.0, max_results=15, workers=10):
    coins = _top_200()
    universe = [c for c in coins if str(c.get("symbol") or "").upper() not in STABLES]
    symbol_map = _spot_symbol_map()

    matched = []
    for c in universe:
        base = str(c.get("symbol") or "").upper()
        exchange_symbol = symbol_map.get(base)
        if exchange_symbol:
            matched.append((c, exchange_symbol))

    signals = []
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(_analyze_coin, c, sym, min_z, min_buyer_share): (c, sym)
            for c, sym in matched
        }
        for fut in as_completed(futs):
            try:
                row = fut.result()
                if row:
                    signals.append(row)
            except Exception:
                failed += 1

    signals.sort(
        key=lambda x: (x["signal_score"], x["volume_zscore_10m"], x["buyer_share_pct"]),
        reverse=True,
    )
    return signals[:max_results], {
        "top200_received": len(coins),
        "non_stable_universe": len(universe),
        "binance_spot_matched": len(matched),
        "scanned": max(0, len(matched) - failed),
        "failed": failed,
        "signal_count_before_cap": len(signals),
        "source_endpoint": _ACTIVE_BINANCE_BASE or BINANCE_BASES[0],
    }


def build_report():
    try:
        movers, meta = scan_top_movers()
    except Exception as e:
        return f"🔍 *SPOT AKIŞ TARAYICI*\n⚠️ {e}"
    lines = ["🔍 *SPOT AKIŞ TARAYICI — Top 200*"]
    if movers:
        for x in movers:
            lines.append(
                f"• {x['symbol']}: Vol Z {x['volume_zscore_10m']:.1f} · Alıcı %{x['buyer_share_pct']:.0f} · {x['cvd_note']}"
            )
    else:
        lines.append(f"Sinyal yok. Taranan spot coin: {meta.get('scanned',0)}")
    return "\n".join(lines)


def get_analysis_data():
    try:
        movers, meta = scan_top_movers()
        return {
            "movers": movers,
            "window": "10m",
            "rule": "Top 200 → son tamamlanmış 10dk hacim Z-score >= 2.0 + taker alıcı payı >= %55 + Spot CVD delta > 0",
            "source": "Binance Spot public market-data-only API",
            "universe_source": "CoinGecko Top 200",
            "scan_meta": meta,
            "method": "5dk Binance spot klines iki mum birleştirilerek 10dk yapılır. Quote volume Z-score önceki 30 adet 10dk mumdan; Spot CVD delta taker-buy quote volume - taker-sell quote volume olarak hesaplanır.",
            "cvd_rule": "Son 3 tamamlanmış 10dk CVD mumunda art arda son 2 veya 3 pozitif delta varsa sinyal yanında teyit notu gösterilir.",
        }
    except Exception as e:
        return {
            "movers": [],
            "window": "10m",
            "rule": "Top 200 → son tamamlanmış 10dk hacim Z-score >= 2.0 + taker alıcı payı >= %55 + Spot CVD delta > 0",
            "source": "Binance Spot public market-data-only API",
            "universe_source": "CoinGecko Top 200",
            "scan_meta": {},
            "error": str(e),
        }
