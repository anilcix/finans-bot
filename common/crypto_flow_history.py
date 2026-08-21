"""15 dakikalık kripto akış geçmişi.

- Spot CVD: Kraken BTC/USD spot trade akışından agresif buy - sell notional USD.
- OI: Coinalyze çoklu-borsa BTC perpetual aggregate OI snapshot.
- Her çalışma bir tamamlanmış 15dk bucket üretir; son 96 bucket (24s) tutulur.
"""
import json
import os
from datetime import datetime, timezone
import requests

KRAKEN_API = "https://api.kraken.com/0/public/Trades"
PAIR = "XBTUSD"
BUCKET_SECONDS = 15 * 60
MAX_BUCKETS = 96
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0; market-research)"}


def _completed_bucket(now=None):
    now = now or datetime.now(timezone.utc)
    ts = int(now.timestamp())
    end_ts = (ts // BUCKET_SECONDS) * BUCKET_SECONDS
    start_ts = end_ts - BUCKET_SECONDS
    return start_ts, end_ts


def fetch_kraken_spot_cvd_15m(now=None):
    """Tamamlanmış son 15 dakikadaki Kraken BTC/USD spot CVD'yi USD notional olarak hesaplar."""
    start_ts, end_ts = _completed_bucket(now)
    since = str(start_ts * 1_000_000_000)
    buy_usd = 0.0
    sell_usd = 0.0
    trade_count = 0
    first_trade_ts = None
    last_trade_ts = None
    seen_last = None

    for _ in range(30):
        r = requests.get(KRAKEN_API, params={"pair": PAIR, "since": since}, headers=UA, timeout=15)
        r.raise_for_status()
        payload = r.json()
        if payload.get("error"):
            raise ValueError(str(payload["error"]))
        result = payload.get("result") or {}
        key = next((k for k in result if k != "last"), None)
        if not key:
            break
        rows = result.get(key) or []
        for row in rows:
            try:
                price = float(row[0]); volume = float(row[1]); t = float(row[2]); side = row[3]
            except Exception:
                continue
            if t < start_ts:
                continue
            if t >= end_ts:
                continue
            notional = price * volume
            if side == "b":
                buy_usd += notional
            else:
                sell_usd += notional
            trade_count += 1
            first_trade_ts = t if first_trade_ts is None else min(first_trade_ts, t)
            last_trade_ts = t if last_trade_ts is None else max(last_trade_ts, t)

        cursor = str(result.get("last") or "")
        if not cursor or cursor == seen_last:
            break
        seen_last = cursor
        since = cursor

        # Son dönen trade bucket sonuna ulaştıysa daha fazla sayfa gerekmiyor.
        if rows:
            try:
                if float(rows[-1][2]) >= end_ts:
                    break
            except Exception:
                pass

    coverage_seconds = 0.0
    if first_trade_ts is not None and last_trade_ts is not None:
        coverage_seconds = max(0.0, last_trade_ts - first_trade_ts)

    return {
        "source": "Kraken Spot BTC/USD",
        "bucket_start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
        "bucket_end": datetime.fromtimestamp(end_ts, timezone.utc).isoformat(),
        "buy_notional_usd": buy_usd,
        "sell_notional_usd": sell_usd,
        "cvd_delta_usd": buy_usd - sell_usd,
        "trade_count": trade_count,
        "coverage_seconds": coverage_seconds,
        "ok": trade_count > 0,
    }


def update_history(output_dir, derivatives_data, now=None):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "crypto_flow_history.json")
    now = now or datetime.now(timezone.utc)
    start_ts, end_ts = _completed_bucket(now)
    bucket_end = datetime.fromtimestamp(end_ts, timezone.utc).isoformat()

    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        points = list(old.get("points") or [])
    except Exception:
        points = []

    try:
        spot = fetch_kraken_spot_cvd_15m(now)
    except Exception as e:
        spot = {
            "source": "Kraken Spot BTC/USD",
            "bucket_start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
            "bucket_end": bucket_end,
            "ok": False,
            "error": str(e)[:220],
        }

    ca = (derivatives_data or {}).get("coinalyze") or {}
    binance = ca.get("binance") or {}
    point = {
        "ts": bucket_end,
        "spot_cvd_delta_usd": spot.get("cvd_delta_usd"),
        "spot_buy_usd": spot.get("buy_notional_usd"),
        "spot_sell_usd": spot.get("sell_notional_usd"),
        "spot_trade_count": spot.get("trade_count"),
        "spot_coverage_seconds": spot.get("coverage_seconds"),
        "spot_source": spot.get("source"),
        "spot_ok": bool(spot.get("ok")),
        "spot_error": spot.get("error"),
        "aggregate_oi_usd": ca.get("aggregate_oi_usd"),
        "binance_oi_usd": binance.get("open_interest_usd"),
        "oi_source": "Coinalyze multi-exchange BTC perpetual" if ca.get("ok") else None,
    }

    # Aynı 15dk bucket yeniden üretilirse replace et.
    points = [p for p in points if p.get("ts") != bucket_end]
    points.append(point)
    points.sort(key=lambda p: p.get("ts") or "")
    points = points[-MAX_BUCKETS:]

    payload = {
        "generated_at": now.isoformat(),
        "interval_minutes": 15,
        "window_hours": 24,
        "max_points": MAX_BUCKETS,
        "spot_cvd_definition": "Kraken BTC/USD spot agresif alış notionalı eksi agresif satış notionalı; her nokta tamamlanmış 15 dakikalık bucket delta değeridir.",
        "oi_definition": "Coinalyze seçili büyük BTC perpetual piyasalarının USD aggregate açık pozisyon snapshotı.",
        "points": points,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload
