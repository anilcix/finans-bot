"""Coinalyze BTC 10dk akış ve kaldıraç geçmişi.

Son 24 saatte aynı 10dk ekseninde:
- Binance Spot CVD
- Binance Futures CVD
- Tüm borsalar BTC perpetual OI toplamı
- Tüm borsalar OI-ağırlıklı funding
- Tüm borsalar liquidation
- Binance OI
- Binance funding
- Binance long/short
- Binance liquidation

Coinalyze native 5dk serileri ikişer birleştirilerek 10dk bucket yapılır.
"""
from datetime import datetime, timedelta, timezone
import os

from common.coinalyze import (
    _clean_key,
    _get,
    _exchange_map,
    _canon_exchange,
    _hist_map,
    _all_exchange_markets,
)


def _pick_binance_market(rows, exchange_names, *, spot=False, require_buy_sell=False):
    candidates=[]
    for x in rows if isinstance(rows,list) else []:
        if str(x.get("base_asset","")).upper()!="BTC":continue
        if not spot and not x.get("is_perpetual"):continue
        quote=str(x.get("quote_asset","")).upper()
        if quote not in ("USDT","USD","USDC"):continue
        code=str(x.get("exchange", ""));exchange=_canon_exchange(exchange_names.get(code, code))
        if exchange!="Binance":continue
        if require_buy_sell and not x.get("has_buy_sell_data"):continue
        if not spot and x.get("has_ohlcv_data") is False:continue
        stable=0 if spot or str(x.get("margined","")).upper()=="STABLE" else 1
        qrank={"USDT":0,"USD":1,"USDC":2}.get(quote,9)
        candidates.append((stable,qrank,x))
    candidates.sort(key=lambda z:z[:2])
    return candidates[0][2] if candidates else None


def _by_time(history):
    return {int(x.get("t")):x for x in history if isinstance(x,dict) and x.get("t") is not None}


def _latest_before(history, ts, field):
    best=None
    for row in history:
        rt=row.get("t")
        if rt is None:continue
        rt=int(rt)
        if rt<=ts:best=row
        else:break
    if not best:return None
    try:return float(best.get(field))
    except (TypeError,ValueError):return None


def _bucket_sum(history,start,end,fields):
    sums={f:0.0 for f in fields};found=False
    for row in history:
        rt=row.get("t")
        if rt is None:continue
        rt=int(rt)
        if start<=rt<end:
            found=True
            for f in fields:
                try:sums[f]+=float(row.get(f) or 0)
                except (TypeError,ValueError):pass
    return sums if found else None


def _cvd_bucket(history,start,end):
    rows=[x for x in history if x.get("t") is not None and start<=int(x.get("t"))<end]
    if not rows:return None
    total=sum(float(x.get("v") or 0) for x in rows)
    buy=sum(float(x.get("bv") or 0) for x in rows)
    return buy-max(0.0,total-buy)


def _to_10m(spot_hist,perp_hist,oi_by_symbol,funding_by_symbol,liq_by_symbol,ls_by_symbol,binance_symbol,start_ts,end_ts):
    points=[];spot_cum=0.0;perp_cum=0.0
    bucket=(start_ts//600)*600
    if bucket<start_ts:bucket+=600
    while bucket<end_ts:
        bend=bucket+600
        spot_delta=_cvd_bucket(spot_hist,bucket,bend)
        perp_delta=_cvd_bucket(perp_hist,bucket,bend)
        if spot_delta is not None:spot_cum+=spot_delta
        if perp_delta is not None:perp_cum+=perp_delta

        aggregate_oi=0.0;fund_num=0.0;fund_den=0.0;oi_count=0
        agg_long=agg_short=0.0;liq_found=False
        for symbol,hist in oi_by_symbol.items():
            oi=_latest_before(hist,bend-1,"c")
            fund=_latest_before(funding_by_symbol.get(symbol,[]),bend-1,"c")
            if oi is not None:
                aggregate_oi+=oi;oi_count+=1
                if fund is not None:fund_num+=oi*fund;fund_den+=oi
            liq=_bucket_sum(liq_by_symbol.get(symbol,[]),bucket,bend,("l","s"))
            if liq:
                liq_found=True;agg_long+=liq["l"];agg_short+=liq["s"]

        b_oi=_latest_before(oi_by_symbol.get(binance_symbol,[]),bend-1,"c")
        b_funding=_latest_before(funding_by_symbol.get(binance_symbol,[]),bend-1,"c")
        b_ls=_latest_before(ls_by_symbol.get(binance_symbol,[]),bend-1,"r")
        b_liq=_bucket_sum(liq_by_symbol.get(binance_symbol,[]),bucket,bend,("l","s"))

        points.append({
            "ts":datetime.fromtimestamp(bend,timezone.utc).isoformat(),
            "spot_cvd_delta_btc":spot_delta,
            "spot_cvd_cumulative_btc":spot_cum if spot_delta is not None else None,
            "perp_cvd_delta_btc":perp_delta,
            "perp_cvd_cumulative_btc":perp_cum if perp_delta is not None else None,
            "aggregate_oi_usd":aggregate_oi if oi_count else None,
            "aggregate_oi_weighted_funding_pct":fund_num/fund_den if fund_den else None,
            "aggregate_liquidations_10m_usd":agg_long+agg_short if liq_found else None,
            "aggregate_long_liquidations_10m_usd":agg_long if liq_found else None,
            "aggregate_short_liquidations_10m_usd":agg_short if liq_found else None,
            "binance_oi_usd":b_oi,
            "binance_funding_pct":b_funding,
            "binance_long_short_ratio":b_ls,
            "binance_liquidations_10m_usd":(b_liq["l"]+b_liq["s"]) if b_liq else None,
            "binance_long_liquidations_10m_usd":b_liq["l"] if b_liq else None,
            "binance_short_liquidations_10m_usd":b_liq["s"] if b_liq else None,
        })
        bucket=bend
    return points[-144:]


def fetch_binance_flow_history(hours=24):
    key=_clean_key(os.getenv("COINALYZE_API_KEY"))
    out={"source":"Coinalyze","venue":"Binance","interval_minutes":10,"window_hours":hours,"points":[],"ok":False,"error":None}
    if not key:
        out["error"]="COINALYZE_API_KEY tanımlı değil.";return out
    try:
        exchanges=_exchange_map(_get("exchanges",key))
        spot_markets=_get("spot-markets",key) or []
        future_markets=_get("future-markets",key) or []
        spot=_pick_binance_market(spot_markets,exchanges,spot=True,require_buy_sell=True)
        perp=_pick_binance_market(future_markets,exchanges,spot=False,require_buy_sell=True)
        all_markets=_all_exchange_markets(future_markets,exchanges)
        if not spot:raise ValueError("Coinalyze Binance BTC spot buy/sell market bulunamadı")
        if not perp:raise ValueError("Coinalyze Binance BTC perpetual buy/sell market bulunamadı")
        if not all_markets:raise ValueError("Coinalyze BTC perpetual market seti bulunamadı")

        now=datetime.now(timezone.utc);frm=int((now-timedelta(hours=hours,minutes=20)).timestamp());to=int(now.timestamp())
        spot_symbol=spot["symbol"];perp_symbol=perp["symbol"];symbols=[x["symbol"] for x in all_markets];symstr=",".join(symbols)
        base={"interval":"5min","from":frm,"to":to}

        spot_rows=_get("ohlcv-history",key,{**base,"symbols":spot_symbol}) or []
        perp_rows=_get("ohlcv-history",key,{**base,"symbols":perp_symbol}) or []
        oi_rows=_get("open-interest-history",key,{**base,"symbols":symstr,"convert_to_usd":"true"}) or []
        funding_rows=_get("funding-rate-history",key,{**base,"symbols":symstr}) or []
        liq_rows=_get("liquidation-history",key,{**base,"symbols":symstr,"convert_to_usd":"true"}) or []
        ls_rows=_get("long-short-ratio-history",key,{**base,"symbols":perp_symbol}) or []

        spot_hist=_hist_map(spot_rows).get(spot_symbol) or []
        perp_hist=_hist_map(perp_rows).get(perp_symbol) or []
        oi_map=_hist_map(oi_rows);fund_map=_hist_map(funding_rows);liq_map=_hist_map(liq_rows);ls_map=_hist_map(ls_rows)
        for m in (oi_map,fund_map,liq_map,ls_map):
            for hist in m.values():hist.sort(key=lambda x:int(x.get("t",0)))
        points=_to_10m(spot_hist,perp_hist,oi_map,fund_map,liq_map,ls_map,perp_symbol,frm,to)

        out.update({
            "ok":bool(points),"points":points,
            "spot_symbol":spot_symbol,"spot_symbol_on_exchange":spot.get("symbol_on_exchange"),
            "perp_symbol":perp_symbol,"perp_symbol_on_exchange":perp.get("symbol_on_exchange"),
            "aggregate_exchange_count":len(all_markets),
            "aggregate_exchanges":[_canon_exchange(exchanges.get(str(x.get("exchange","")),str(x.get("exchange","")))) for x in all_markets],
            "spot_source":"Coinalyze Binance spot OHLCV buy/sell volume",
            "perp_cvd_source":"Coinalyze Binance perpetual OHLCV buy/sell volume",
            "oi_source":"Coinalyze all-exchange + Binance BTC perpetual OI history",
            "funding_source":"Coinalyze all-exchange + Binance BTC perpetual funding-rate history",
            "liquidation_source":"Coinalyze all-exchange + Binance liquidation history",
            "long_short_source":"Coinalyze Binance BTC perpetual long-short-ratio history",
            "definition":"Tüm seriler 5dk Coinalyze verilerinden 10dk bucket'a çevrilir. Aggregate OI her borsadan bir ana BTC perpetualın USD OI toplamı; aggregate funding OI-ağırlıklı; liquidation her 10dk bucket toplamıdır.",
        })
    except Exception as e:out["error"]=str(e)[:300]
    return out
