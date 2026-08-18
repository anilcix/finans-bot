"""
FRED (Federal Reserve Economic Data) yardımcı fonksiyonları.
Tamamen ücretsiz, ama bir API key gerektirir.
Ortam değişkeni: FRED_API_KEY
"""

import os
import requests

FRED_API_KEY = os.environ.get("FRED_API_KEY")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch_fred_series(series_id, limit=14, units=None):
    if not FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY ayarlanmamış")
    params = {"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": limit}
    if units:
        params["units"] = units
    r = requests.get(FRED_BASE, params=params, timeout=20)
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", "", None)]
    return [(o["date"], float(o["value"])) for o in obs]


def fetch_fred_history(series_id, limit=300, units=None):
    obs = fetch_fred_series(series_id, limit=limit, units=units)
    if not obs:
        raise ValueError("Veri yok")
    return [d for d, _ in obs], [v for _, v in obs]


def latest_value(series_id):
    obs = fetch_fred_series(series_id, limit=1)
    if not obs:
        raise ValueError("Veri yok")
    return obs[0]


def yoy_change(series_id, lag=12):
    obs = fetch_fred_series(series_id, limit=lag + 2)
    if len(obs) < lag + 1:
        raise ValueError("Yeterli veri yok")
    latest_date, latest_val = obs[0]
    year_ago_val = obs[lag][1]
    return latest_date, latest_val, (latest_val - year_ago_val) / year_ago_val * 100


def mom_change(series_id):
    obs = fetch_fred_series(series_id, limit=2)
    if len(obs) < 2:
        raise ValueError("Yeterli veri yok")
    latest_date, latest_val = obs[0]
    prev_val = obs[1][1]
    return latest_date, latest_val, (latest_val - prev_val) / prev_val * 100
