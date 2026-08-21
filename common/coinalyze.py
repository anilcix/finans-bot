"""Coinalyze ücretsiz API key ile BTC türev + Binance spot akış verisi.

COINALYZE_API_KEY yoksa sessizce devre dışı kalır.
Ana katman büyük borsalardan BTC perpetual OI/funding/liquidation/L/S toplar.
Ek akış katmanı Binance BTC spot 5dk buy/sell volume ve Binance BTC perp 5dk OI
history verisini doğrudan Coinalyze API'den alıp 10dk seriye dönüştürür.
"""
from datetime import datetime, timedelta, timezone
import os
import requests

BASE = "https://api.coinalyze.net/v1"
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0)", "Accept": "application/json"}
PREFERRED = ("BINANCE", "BYBIT", "OKX", "HYPERLIQUID", "BITGET", "KRAKEN", "DERIBIT")


def _f(x):
    try:return float(x)
    except (TypeError, ValueError):return None


def _clean_key(value):
    return (value or "").strip().replace("\\n", "").replace("\\r", "").replace("\n", "").replace("\r", "").strip()


def _get(path, key, params=None):
    key=_clean_key(key)
    r=requests.get(f"{BASE}/{path}",params=params or {},headers={**UA,"api_key":key},timeout=20)
    r.raise_for_status();return r.json()


def _canon_exchange(name):
    raw=str(name or "Unknown");u=raw.upper()
    aliases={"BINANCE FUTURES":"Binance","BINANCE":"Binance","BYBIT":"Bybit","OKX":"OKX","HYPERLIQUID":"Hyperliquid","BITGET":"Bitget","KRAKEN":"Kraken","DERIBIT":"Deribit"}
    for needle,label in aliases.items():
        if needle in u:return label
    return raw


def _exchange_map(rows):
    out={}
    for x in rows if isinstance(rows,list) else []:
        code=str(x.get("code", ""));name=x.get("name")
        if code:out[code]=_canon_exchange(name)
    return out


def _pick_markets(rows, exchange_names, limit=7):
    candidates=[]
    for x in rows if isinstance(rows,list) else []:
        if str(x.get("base_asset","")).upper()!="BTC" or not x.get("is_perpetual"):continue
        quote=str(x.get("quote_asset","")).upper()
        if quote not in ("USDT","USD","USDC"):continue
        code=str(x.get("exchange",""));exch=_canon_exchange(exchange_names.get(code,code));eu=exch.upper()
        pref=next((i for i,p in enumerate(PREFERRED) if p in eu),99)
        stable=0 if str(x.get("margined","")).upper()=="STABLE" else 1
        quote_rank={"USDT":0,"USD":1,"USDC":2}.get(quote,9)
        candidates.append((pref,stable,quote_rank,exch,x))
    candidates.sort(key=lambda z:z[:4])
    selected=[];seen=set()
    for _,_,_,exch,x in candidates:
        if exch in seen:continue
        seen.add(exch);selected.append(x)
        if len(selected)>=limit:break
    return selected


def _pick_binance_spot(rows, exchange_names):
    candidates=[]
    for x in rows if isinstance(rows,list) else []:
        if str(x.get("base_asset","")).upper()!="BTC":continue
        quote=str(x.get("quote_asset","")).upper()
        if quote not in ("USDT","USD","USDC"):continue
        code=str(x.get("exchange",""));exch=_canon_exchange(exchange_names.get(code,code))
        if exch!="Binance":continue
        if not x.get("has_buy_sell_data"):continue
        qrank={"USDT":0,"USD":1,"USDC":2}.get(quote,9)
        candidates.append((qrank,x))
    candidates.sort(key=lambda z:z[0])
    return candidates[0][1] if candidates else None


def _pick_binance_perp(rows, exchange_names):
    candidates=[]
    for x in rows if isinstance(rows,list) else []:
        if str(x.get("base_asset","")).upper()!="BTC" or not x.get("is_perpetual"):continue
        quote=str(x.get("quote_asset","")).upper()
        if quote not in ("USDT","USD","USDC"):continue
        code=str(x.get("exchange",""));exch=_canon_exchange(exchange_names.get(code,code))
        if exch!="Binance":continue
        stable=0 if str(x.get("margined","")).upper()=="STABLE" else 1
        qrank={"USDT":0,"USD":1,"USDC":2}.get(quote,9)
        candidates.append((stable,qrank,x))
    candidates.sort(key=lambda z:z[:2])
    return candidates[0][2] if candidates else None


def _hist_map(rows):
    return {x.get("symbol"):x.get("history") or [] for x in rows if isinstance(x,dict)} if isinstance(rows,list) else {}


def _pair_5m_to_10m(spot_hist, oi_hist):
    """Coinalyze native 5m serileri 10m bucket'a çevirir."""
    spot_by_t={int(x.get("t")):x for x in spot_hist if isinstance(x,dict) and x.get("t") is not None}
    oi_by_t={int(x.get("t")):x for x in oi_hist if isinstance(x,dict) and x.get("t") is not None}
    all_ts=sorted(set(spot_by_t)|set(oi_by_t))
    buckets={}
    for ts in all_ts:
        bucket=(ts//600)*600
        b=buckets.setdefault(bucket,{"spot":[],"oi":[]})
        if ts in spot_by_t:b["spot"].append(spot_by_t[ts])
        if ts in oi_by_t:b["oi"].append(oi_by_t[ts])
    points=[]
    cumulative_btc=0.0
    for bucket in sorted(buckets):
        b=buckets[bucket];spot_rows=sorted(b["spot"],key=lambda x:x.get("t",0));oi_rows=sorted(b["oi"],key=lambda x:x.get("t",0))
        delta_btc=None;buy_btc=sell_btc=None;close_price=None
        if spot_rows:
            total_v=sum(_f(x.get("v")) or 0 for x in spot_rows)
            buy_btc=sum(_f(x.get("bv")) or 0 for x in spot_rows)
            sell_btc=max(0.0,total_v-buy_btc)
            delta_btc=buy_btc-sell_btc
            cumulative_btc+=delta_btc
            close_price=_f(spot_rows[-1].get("c"))
        oi_usd=_f(oi_rows[-1].get("c")) if oi_rows else None
        points.append({
            "ts":datetime.fromtimestamp(bucket+600,timezone.utc).isoformat(),
            "spot_cvd_delta_btc":delta_btc,
            "spot_cvd_cumulative_btc":cumulative_btc if delta_btc is not None else None,
            "spot_buy_btc":buy_btc,
            "spot_sell_btc":sell_btc,
            "spot_close_usd":close_price,
            "binance_oi_usd":oi_usd,
        })
    return points[-144:]


def fetch_coinalyze_binance_flow_history(hours=24):
    """Tamamen Coinalyze kaynaklı Binance Spot CVD + Binance Perp OI, 10dk seri."""
    key=_clean_key(os.getenv("COINALYZE_API_KEY"))
    out={"source":"Coinalyze","venue":"Binance","interval_minutes":10,"window_hours":hours,"points":[],"ok":False,"error":None}
    if not key:
        out["error"]="COINALYZE_API_KEY tanımlı değil.";return out
    try:
        exchange_names=_exchange_map(_get("exchanges",key))
        spot_meta=_pick_binance_spot(_get("spot-markets",key),exchange_names)
        perp_meta=_pick_binance_perp(_get("future-markets",key),exchange_names)
        if not spot_meta:raise ValueError("Coinalyze Binance BTC spot market bulunamadı")
        if not perp_meta:raise ValueError("Coinalyze Binance BTC perpetual market bulunamadı")
        now=datetime.now(timezone.utc);frm=int((now-timedelta(hours=hours,minutes=20)).timestamp());to=int(now.timestamp())
        spot_symbol=spot_meta["symbol"];perp_symbol=perp_meta["symbol"]
        spot_rows=_get("ohlcv-history",key,{"symbols":spot_symbol,"interval":"5min","from":frm,"to":to})
        oi_rows=_get("open-interest-history",key,{"symbols":perp_symbol,"interval":"5min","from":frm,"to":to,"convert_to_usd":"true"})
        spot_hist=_hist_map(spot_rows).get(spot_symbol) or []
        oi_hist=_hist_map(oi_rows).get(perp_symbol) or []
        points=_pair_5m_to_10m(spot_hist,oi_hist)
        out.update({
            "ok":bool(points),
            "points":points,
            "spot_symbol":spot_symbol,
            "spot_symbol_on_exchange":spot_meta.get("symbol_on_exchange"),
            "perp_symbol":perp_symbol,
            "perp_symbol_on_exchange":perp_meta.get("symbol_on_exchange"),
            "spot_source":"Coinalyze Binance spot OHLCV buy/sell volume",
            "oi_source":"Coinalyze Binance BTC perpetual OI history",
            "definition":"Spot CVD = kümülatif (buy volume - sell volume). Coinalyze 5m v/bv serileri ikişer birleştirilerek 10m bucket yapılır; OI aynı 10m bucket'ta son 5m close snapshotıdır.",
        })
    except Exception as e:out["error"]=str(e)[:300]
    return out


def fetch_coinalyze_btc():
    key=_clean_key(os.getenv("COINALYZE_API_KEY"))
    out={"source":"Coinalyze","configured":bool(key),"ok":False,"markets":[],"by_exchange":{},"binance":None,"binance_available":False,"aggregate_oi_usd":None,"oi_change_24h_pct":None,"oi_weighted_funding_pct":None,"liquidations_24h":None,"long_short_ratio_avg":None,"note":None,"error":None}
    if not key:
        out["note"]="COINALYZE_API_KEY GitHub Secret olarak tanımlı değil.";return out
    try:
        exchange_names=_exchange_map(_get("exchanges",key));out["exchange_codes"]=exchange_names
        markets=_get("future-markets",key);picked=_pick_markets(markets,exchange_names,limit=7)
        if not picked:raise ValueError("Uygun BTC perpetual market bulunamadı")
        symbols=[x["symbol"] for x in picked];symstr=",".join(symbols)
        now=datetime.now(timezone.utc);frm=int((now-timedelta(hours=26)).timestamp());to=int(now.timestamp())
        common={"symbols":symstr,"interval":"1hour","from":frm,"to":to}
        oi_now=_get("open-interest",key,{"symbols":symstr,"convert_to_usd":"true"})
        fund_now=_get("funding-rate",key,{"symbols":symstr})
        oi_hist=_get("open-interest-history",key,{**common,"convert_to_usd":"true"})
        liq_hist=_get("liquidation-history",key,{**common,"convert_to_usd":"true"})
        ls_hist=_get("long-short-ratio-history",key,common)
        oi_map={x.get("symbol"):_f(x.get("value")) for x in oi_now if isinstance(x,dict)}
        fund_map={x.get("symbol"):_f(x.get("value")) for x in fund_now if isinstance(x,dict)}
        oih=_hist_map(oi_hist);lqh=_hist_map(liq_hist);lsh=_hist_map(ls_hist)
        venue_rows=[];current_total=old_total=fund_num=fund_den=liq_long=liq_short=0.0;old_count=0;ratios=[]
        by_symbol={x["symbol"]:x for x in picked}
        for symbol in symbols:
            meta=by_symbol[symbol];code=str(meta.get("exchange",""));exchange=_canon_exchange(exchange_names.get(code,code))
            oi=oi_map.get(symbol);fund=fund_map.get(symbol);hist=oih.get(symbol) or [];oi_old=_f(hist[0].get("c")) if hist else None
            oi_change=(oi/oi_old-1)*100 if oi is not None and oi_old not in (None,0) else None
            liqs=lqh.get(symbol) or [];l_long=sum(_f(x.get("l")) or 0 for x in liqs);l_short=sum(_f(x.get("s")) or 0 for x in liqs)
            lsrows=lsh.get(symbol) or [];ratio=_f(lsrows[-1].get("r")) if lsrows else None
            if oi is not None:current_total+=oi
            if oi_old is not None:old_total+=oi_old;old_count+=1
            if oi is not None and fund is not None:fund_num+=oi*fund;fund_den+=oi
            liq_long+=l_long;liq_short+=l_short
            if ratio is not None:ratios.append(ratio)
            row={"exchange":exchange,"exchange_code":code,"symbol":symbol,"symbol_on_exchange":meta.get("symbol_on_exchange"),"open_interest_usd":oi,"open_interest_24h_ago_usd":oi_old,"open_interest_change_24h_pct":oi_change,"funding_pct":fund,"long_short_ratio":ratio,"long_liquidations_24h_usd":l_long,"short_liquidations_24h_usd":l_short,"total_liquidations_24h_usd":l_long+l_short}
            venue_rows.append(row);out["by_exchange"][exchange]=row
        out["markets"]=venue_rows;out["binance"]=out["by_exchange"].get("Binance");out["binance_available"]=bool(out["binance"])
        out["aggregate_oi_usd"]=current_total if current_total>0 else None
        if current_total>0 and old_count and old_total>0:out["oi_change_24h_pct"]=(current_total/old_total-1)*100
        if fund_den>0:out["oi_weighted_funding_pct"]=fund_num/fund_den
        out["liquidations_24h"]={"long_usd":liq_long,"short_usd":liq_short,"total_usd":liq_long+liq_short,"dominant_side":"long" if liq_long>liq_short else "short" if liq_short>liq_long else "balanced"}
        out["long_short_ratio_avg"]=sum(ratios)/len(ratios) if ratios else None;out["market_count"]=len(venue_rows);out["ok"]=out["aggregate_oi_usd"] is not None or bool(ratios)
        out["note"]="Binance dahil seçili büyük borsalarda birer temsilci BTC perpetual kontratı kullanılır; tam piyasa toplamı değildir." if out["binance_available"] else "Coinalyze çalışıyor ancak seçilen BTC perpetual setinde Binance bulunamadı."
    except Exception as e:out["error"]=str(e)[:300]
    return out
