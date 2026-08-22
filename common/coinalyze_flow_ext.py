"""Coinalyze Binance BTC 10dk akış serileri.

Aynı zaman ekseninde dört veri üretir:
- Spot CVD
- Futures/Perp CVD
- Perp Open Interest
- Funding Rate

Coinalyze 5dk serileri ikişer birleştirilerek 10dk bucket yapılır.
"""
from datetime import datetime, timedelta, timezone
import os

from common.coinalyze import (
    _clean_key,
    _get,
    _exchange_map,
    _canon_exchange,
    _hist_map,
)


def _pick_binance_market(rows, exchange_names, *, spot=False, require_buy_sell=False):
    candidates=[]
    for x in rows if isinstance(rows,list) else []:
        if str(x.get("base_asset","")).upper()!="BTC":
            continue
        if not spot and not x.get("is_perpetual"):
            continue
        quote=str(x.get("quote_asset","")).upper()
        if quote not in ("USDT","USD","USDC"):
            continue
        code=str(x.get("exchange", ""))
        exchange=_canon_exchange(exchange_names.get(code, code))
        if exchange!="Binance":
            continue
        if require_buy_sell and not x.get("has_buy_sell_data"):
            continue
        if not spot and x.get("has_ohlcv_data") is False:
            continue
        stable=0 if spot or str(x.get("margined","")).upper()=="STABLE" else 1
        qrank={"USDT":0,"USD":1,"USDC":2}.get(quote,9)
        candidates.append((stable,qrank,x))
    candidates.sort(key=lambda z:z[:2])
    return candidates[0][2] if candidates else None


def _rows_by_time(history):
    return {int(x.get("t")):x for x in history if isinstance(x,dict) and x.get("t") is not None}


def _to_10m(spot_hist, perp_hist, oi_hist, funding_hist):
    sources={
        "spot":_rows_by_time(spot_hist),
        "perp":_rows_by_time(perp_hist),
        "oi":_rows_by_time(oi_hist),
        "funding":_rows_by_time(funding_hist),
    }
    all_ts=sorted(set().union(*(set(v) for v in sources.values())))
    buckets={}
    for ts in all_ts:
        bucket=(ts//600)*600
        b=buckets.setdefault(bucket,{"spot":[],"perp":[],"oi":[],"funding":[]})
        for name,mapping in sources.items():
            if ts in mapping:
                b[name].append(mapping[ts])

    points=[]
    spot_cum=0.0
    perp_cum=0.0
    for bucket in sorted(buckets):
        b=buckets[bucket]
        spot=sorted(b["spot"],key=lambda x:x.get("t",0))
        perp=sorted(b["perp"],key=lambda x:x.get("t",0))
        oi=sorted(b["oi"],key=lambda x:x.get("t",0))
        funding=sorted(b["funding"],key=lambda x:x.get("t",0))

        spot_delta=None
        if spot:
            total=sum(float(x.get("v") or 0) for x in spot)
            buy=sum(float(x.get("bv") or 0) for x in spot)
            spot_delta=buy-max(0.0,total-buy)
            spot_cum+=spot_delta

        perp_delta=None
        if perp:
            total=sum(float(x.get("v") or 0) for x in perp)
            buy=sum(float(x.get("bv") or 0) for x in perp)
            perp_delta=buy-max(0.0,total-buy)
            perp_cum+=perp_delta

        oi_usd=float(oi[-1].get("c")) if oi and oi[-1].get("c") is not None else None
        funding_pct=float(funding[-1].get("c")) if funding and funding[-1].get("c") is not None else None

        points.append({
            "ts":datetime.fromtimestamp(bucket+600,timezone.utc).isoformat(),
            "spot_cvd_delta_btc":spot_delta,
            "spot_cvd_cumulative_btc":spot_cum if spot_delta is not None else None,
            "perp_cvd_delta_btc":perp_delta,
            "perp_cvd_cumulative_btc":perp_cum if perp_delta is not None else None,
            "binance_oi_usd":oi_usd,
            "binance_funding_pct":funding_pct,
        })
    return points[-144:]


def fetch_binance_flow_history(hours=24):
    key=_clean_key(os.getenv("COINALYZE_API_KEY"))
    out={
        "source":"Coinalyze","venue":"Binance","interval_minutes":10,
        "window_hours":hours,"points":[],"ok":False,"error":None,
    }
    if not key:
        out["error"]="COINALYZE_API_KEY tanımlı değil."
        return out
    try:
        exchanges=_exchange_map(_get("exchanges",key))
        spot_markets=_get("spot-markets",key) or []
        future_markets=_get("future-markets",key) or []
        spot=_pick_binance_market(spot_markets,exchanges,spot=True,require_buy_sell=True)
        perp=_pick_binance_market(future_markets,exchanges,spot=False,require_buy_sell=True)
        if not spot:
            raise ValueError("Coinalyze Binance BTC spot buy/sell market bulunamadı")
        if not perp:
            raise ValueError("Coinalyze Binance BTC perpetual buy/sell market bulunamadı")

        now=datetime.now(timezone.utc)
        frm=int((now-timedelta(hours=hours,minutes=20)).timestamp())
        to=int(now.timestamp())
        spot_symbol=spot["symbol"]
        perp_symbol=perp["symbol"]
        base={"interval":"5min","from":frm,"to":to}

        spot_rows=_get("ohlcv-history",key,{**base,"symbols":spot_symbol}) or []
        perp_rows=_get("ohlcv-history",key,{**base,"symbols":perp_symbol}) or []
        oi_rows=_get("open-interest-history",key,{**base,"symbols":perp_symbol,"convert_to_usd":"true"}) or []
        funding_rows=_get("funding-rate-history",key,{**base,"symbols":perp_symbol}) or []

        spot_hist=_hist_map(spot_rows).get(spot_symbol) or []
        perp_hist=_hist_map(perp_rows).get(perp_symbol) or []
        oi_hist=_hist_map(oi_rows).get(perp_symbol) or []
        funding_hist=_hist_map(funding_rows).get(perp_symbol) or []
        points=_to_10m(spot_hist,perp_hist,oi_hist,funding_hist)

        out.update({
            "ok":bool(points),"points":points,
            "spot_symbol":spot_symbol,"spot_symbol_on_exchange":spot.get("symbol_on_exchange"),
            "perp_symbol":perp_symbol,"perp_symbol_on_exchange":perp.get("symbol_on_exchange"),
            "spot_source":"Coinalyze Binance spot OHLCV buy/sell volume",
            "perp_cvd_source":"Coinalyze Binance perpetual OHLCV buy/sell volume",
            "oi_source":"Coinalyze Binance perpetual OI history",
            "funding_source":"Coinalyze Binance perpetual funding-rate history",
            "definition":"Spot/Futures CVD = kümülatif (buy volume - sell volume); OI USD; funding Coinalyze oranı. Tümü 5dk serilerden 10dk bucket'a çevrilir.",
        })
    except Exception as e:
        out["error"]=str(e)[:300]
    return out
