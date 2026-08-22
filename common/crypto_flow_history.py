"""Binance BTC 10dk akış geçmişi — tamamen Coinalyze kaynaklı."""
import json
import os
from datetime import datetime, timezone
from common.coinalyze_flow_ext import fetch_binance_flow_history

SCHEMA_VERSION = 5
MAX_BUCKETS = 144


def update_history(output_dir, derivatives_data=None, now=None):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "crypto_flow_history.json")
    now = now or datetime.now(timezone.utc)
    flow = fetch_binance_flow_history(hours=24)
    points = list(flow.get("points") or [])[-MAX_BUCKETS:]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "venue": "Binance",
        "generated_at": now.isoformat(),
        "interval_minutes": 10,
        "window_hours": 24,
        "max_points": MAX_BUCKETS,
        "source": "Coinalyze",
        "spot_symbol": flow.get("spot_symbol"),
        "spot_symbol_on_exchange": flow.get("spot_symbol_on_exchange"),
        "perp_symbol": flow.get("perp_symbol"),
        "perp_symbol_on_exchange": flow.get("perp_symbol_on_exchange"),
        "spot_source": flow.get("spot_source"),
        "perp_cvd_source": flow.get("perp_cvd_source"),
        "oi_source": flow.get("oi_source"),
        "funding_source": flow.get("funding_source"),
        "spot_cvd_definition": "Coinalyze Binance spot 5dk OHLCV: delta = buy volume (bv) - sell volume (v-bv). İkişer 5dk bar 10dk bucket olarak birleştirilir ve kümülatif CVD hesaplanır.",
        "perp_cvd_definition": "Coinalyze Binance BTC perpetual 5dk OHLCV: delta = buy volume (bv) - sell volume (v-bv). İkişer 5dk bar 10dk bucket olarak birleştirilir ve kümülatif Futures CVD hesaplanır.",
        "oi_definition": "Coinalyze Binance BTC perpetual 5dk OI history; her 10dk bucket için son 5dk close OI snapshotı kullanılır.",
        "funding_definition": "Coinalyze Binance BTC perpetual funding-rate-history; her 10dk bucket için mevcut son funding close değeri kullanılır.",
        "ok": bool(flow.get("ok")),
        "error": flow.get("error"),
        "points": points,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload
