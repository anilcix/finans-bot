"""15 dakikalık Binance BTC akış geçmişi.

- Spot CVD: Binance BTCUSDT spot aggregate trade akışından agresif buy - sell notional USDT.
- OI: Coinalyze üzerinden Binance BTC perpetual açık pozisyon snapshotı.
- Her çalışma tamamlanmış son 15dk bucket'ı üretir; son 96 bucket (24s) tutulur.
- Binance Spot API erişilemezse CVD uydurulmaz; bucket unavailable olarak kaydedilir.
"""
import json
import os
from datetime import datetime, timezone
import requests

BINANCE_SPOT_API = "https://api.binance.com/api/v3/aggTrades"
SYMBOL = "BTCUSDT"
BUCKET_SECONDS = 15 * 60
MAX_BUCKETS = 96
SCHEMA_VERSION = 2
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0; market-research)", "Accept": "application/json"}


def _completed_bucket(now=None):
    now = now or datetime.now(timezone.utc)
    ts = int(now.timestamp())
    end_ts = (ts // BUCKET_SECONDS) * BUCKET_SECONDS
    start_ts = end_ts - BUCKET_SECONDS
    return start_ts, end_ts


def fetch_binance_spot_cvd_15m(now=None):
    """Tamamlanmış son 15dk Binance BTCUSDT spot CVD; USDT notional bazında."""
    start_ts, end_ts = _completed_bucket(now)
    start_ms = start_ts * 1000
    end_ms = end_ts * 1000 - 1
    buy_usdt = 0.0
    sell_usdt = 0.0
    trade_count = 0
    first_trade_ms = None
    last_trade_ms = None
    from_id = None

    # İlk çağrı zaman aralığı ile bucket başını bulur. Sonraki sayfalar fromId ile devam eder.
    for page in range(80):
        params = {"symbol": SYMBOL, "limit": 1000}
        if from_id is None:
            params.update({"startTime": start_ms, "endTime": end_ms})
        else:
            params["fromId"] = from_id
        r = requests.get(BINANCE_SPOT_API, params=params, headers=UA, timeout=15)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            break

        last_id = None
        reached_end = False
        for x in rows:
            try:
                trade_id = int(x["a"])
                t_ms = int(x["T"])
                price = float(x["p"])
                qty = float(x["q"])
                buyer_is_maker = bool(x.get("m"))
            except Exception:
                continue
            last_id = trade_id
            if t_ms < start_ms:
                continue
            if t_ms > end_ms:
                reached_end = True
                break
            notional = price * qty
            # m=True: buyer maker, dolayısıyla agresif taraf seller.
            if buyer_is_maker:
                sell_usdt += notional
            else:
                buy_usdt += notional
            trade_count += 1
            first_trade_ms = t_ms if first_trade_ms is None else min(first_trade_ms, t_ms)
            last_trade_ms = t_ms if last_trade_ms is None else max(last_trade_ms, t_ms)

        if reached_end or last_id is None or len(rows) < 1000:
            break
        from_id = last_id + 1

    coverage_seconds = 0.0
    if first_trade_ms is not None and last_trade_ms is not None:
        coverage_seconds = max(0.0, (last_trade_ms - first_trade_ms) / 1000.0)

    return {
        "source": "Binance Spot BTCUSDT",
        "bucket_start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
        "bucket_end": datetime.fromtimestamp(end_ts, timezone.utc).isoformat(),
        "buy_notional_usdt": buy_usdt,
        "sell_notional_usdt": sell_usdt,
        "cvd_delta_usdt": buy_usdt - sell_usdt,
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

    points = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        # Kraken/aggregate eski şemayı Binance grafiğine karıştırma.
        if old.get("schema_version") == SCHEMA_VERSION and old.get("venue") == "Binance":
            points = list(old.get("points") or [])
    except Exception:
        pass

    try:
        spot = fetch_binance_spot_cvd_15m(now)
    except Exception as e:
        spot = {
            "source": "Binance Spot BTCUSDT",
            "bucket_start": datetime.fromtimestamp(start_ts, timezone.utc).isoformat(),
            "bucket_end": bucket_end,
            "ok": False,
            "error": str(e)[:220],
        }

    ca = (derivatives_data or {}).get("coinalyze") or {}
    binance = ca.get("binance") or {}
    point = {
        "ts": bucket_end,
        "spot_cvd_delta_usd": spot.get("cvd_delta_usdt"),
        "spot_buy_usd": spot.get("buy_notional_usdt"),
        "spot_sell_usd": spot.get("sell_notional_usdt"),
        "spot_trade_count": spot.get("trade_count"),
        "spot_coverage_seconds": spot.get("coverage_seconds"),
        "spot_source": spot.get("source"),
        "spot_ok": bool(spot.get("ok")),
        "spot_error": spot.get("error"),
        "binance_oi_usd": binance.get("open_interest_usd"),
        "oi_source": "Coinalyze Binance BTC perpetual" if ca.get("binance_available") else None,
    }

    points = [p for p in points if p.get("ts") != bucket_end]
    points.append(point)
    points.sort(key=lambda p: p.get("ts") or "")
    points = points[-MAX_BUCKETS:]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "venue": "Binance",
        "generated_at": now.isoformat(),
        "interval_minutes": 15,
        "window_hours": 24,
        "max_points": MAX_BUCKETS,
        "spot_cvd_definition": "Binance BTCUSDT spot agresif alış notionalı eksi agresif satış notionalı; her nokta tamamlanmış 15 dakikalık bucket delta değeridir.",
        "oi_definition": "Coinalyze üzerinden Binance BTC perpetual USD açık pozisyon snapshotı.",
        "points": points,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload
