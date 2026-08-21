"""Coinalyze ücretsiz API key ile BTC türev + Binance spot akış verisi.

COINALYZE_API_KEY yoksa sessizce devre dışı kalır.
Ana katman BTC perpetual OI/funding'i iki görünümde toplar:
- Tüm desteklenen borsalar: her borsadan bir ana BTC perpetual kontratı
- Core 3: Binance + OKX + Bybit

Mevcut Kripto Türev uyumluluğu için seçili büyük borsalarda 24s OI değişimi,
liquidation ve L/S katmanı da korunur. Aynı process içinde tekrar çağrılırsa
kısa süreli cache kullanılır; böylece Kripto ve Kripto Türev ajanları aynı
Coinalyze verisini ikinci kez çekmez.
"""
from datetime import datetime, timedelta, timezone
import os
import time
import requests

BASE = "https://api.coinalyze.net/v1"
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0)", "Accept":"application/json"}
PREFERRED = ("BINANCE", "BYBIT", "OKX", "HYPERLIQUID", "BITGET", "KRAKEN", "DERIBIT")
CORE_EXCHANGES = {"Binance", "OKX", "Bybit"}
_CACHE_VALUE = None
_CACHE_TS = 0.0
_CACHE_TTL_SECONDS = 45


def _f(x):
    try:return float(x)
    except (TypeError, ValueError):return None


def _clean_key(value):
    return (value or "").strip().replace("\\n", "").replace("\\r", "").replace("\n", "").replace("\r", "").strip()


def _retry_delay(response):
    raw=response.headers.get("Retry-After")
    try:return max(2.0,min(float(raw)+1.0,65.0))
    except (TypeError,ValueError):return 61.0


def _get(path, key, params=None, retry_rate_limit=True):
    key=_clean_key(key)
    for attempt in range(2 if retry_rate_limit else 1):
        r=requests.get(f"{BASE}/{path}",params=params or {},headers={**UA,"api_key":key},timeout=25)
        if r.status_code!=429:
            r.raise_for_status();return r.json()
        if attempt==0 and retry_rate_limit:
            time.sleep(_retry_delay(r));continue
        r.raise_for_status()
    return None


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


def _market_rank(x, exchange_name):
    quote=str(x.get("quote_asset","")).upper()
    stable=0 if str(x.get("margined","")).upper()=="STABLE" else 1
    quote_rank={"USDT":0,"USD":1,"USDC":2}.get(quote,9)
    eu=exchange_name.upper();pref=next((i for i,p in enumerate(PREFERRED) if p in eu),99)
    return stable,quote_rank,pref,str(x.get("symbol") or "")


def _all_exchange_markets(rows, exchange_names):
    """Her borsadan tek ana BTC perpetual seç; böylece aynı borsa iki kez sayılmaz."""
    grouped={}
    for x in rows if isinstance(rows,list) else []:
        if str(x.get("base_asset","")).upper()!="BTC" or not x.get("is_perpetual"):continue
        quote=str(x.get("quote_asset","")).upper()
        if quote not in ("USDT","USD","USDC"):continue
        symbol=x.get("symbol")
        if not symbol:continue
        code=str(x.get("exchange",""));exchange=_canon_exchange(exchange_names.get(code,code))
        rank=_market_rank(x,exchange)
        if exchange not in grouped or rank<grouped[exchange][0]:grouped[exchange]=(rank,x)
    return [grouped[k][1] for k in sorted(grouped)]


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


def _batches(items,n=20):
    for i in range(0,len(items),n):yield items[i:i+n]


def _fetch_current_maps(key, symbols):
    oi_map={};fund_map={}
    for batch in _batches(symbols,20):
        symstr=",".join(batch)
        oi_rows=_get("open-interest",key,{"symbols":symstr,"convert_to_usd":"true"}) or []
        for x in oi_rows:
            if isinstance(x,dict):oi_map[x.get("symbol")]=_f(x.get("value"))
        fund_rows=_get("funding-rate",key,{"symbols":symstr}) or []
        for x in fund_rows:
            if isinstance(x,dict):fund_map[x.get("symbol")]=_f(x.get("value"))
    return oi_map,fund_map


def _aggregate_current(markets, exchange_names, oi_map, fund_map, allowed_exchanges=None):
    total=0.0;fund_num=0.0;fund_den=0.0;rows=[]
    for meta in markets:
        code=str(meta.get("exchange",""));exchange=_canon_exchange(exchange_names.get(code,code))
        if allowed_exchanges is not None and exchange not in allowed_exchanges:continue
        symbol=meta.get("symbol");oi=oi_map.get(symbol);fund=fund_map.get(symbol)
        if oi is not None:total+=oi
        if oi is not None and fund is not None:fund_num+=oi*fund;fund_den+=oi
        rows.append({"exchange":exchange,"symbol":symbol,"symbol_on_exchange":meta.get("symbol_on_exchange"),"open_interest_usd":oi,"funding_pct":fund})
    return {
        "aggregate_oi_usd":total if total>0 else None,
        "oi_weighted_funding_pct":fund_num/fund_den if fund_den>0 else None,
        "exchange_count":len({x["exchange"] for x in rows}),
        "market_count":len(rows),
        "markets":rows,
    }


def _hist_map(rows):
    return {x.get("symbol"):x.get("history") or [] for x in rows if isinstance(x,dict)} if isinstance(rows,list) else {}


def _pair_5m_to_10m(spot_hist, oi_hist):
    """Coinalyze native 5m serileri 10m bucket'a çevirir."""
    spot_by_t={int(x.get("t")):x for x in spot_hist if isinstance(x,dict) and x.get("t") is not None}
    oi_by_t={int(x.get("t")):x for x in oi_hist if isinstance(x,dict) and x.get("t") is not None}
    all_ts=sorted(set(spot_by_t)|set(oi_by_t));buckets={}
    for ts in all_ts:
        bucket=(ts//600)*600;b=buckets.setdefault(bucket,{"spot":[],"oi":[]})
        if ts in spot_by_t:b["spot"].append(spot_by_t[ts])
        if ts in oi_by_t:b["oi"].append(oi_by_t[ts])
    points=[];cumulative_btc=0.0
    for bucket in sorted(buckets):
        b=buckets[bucket];spot_rows=sorted(b["spot"],key=lambda x:x.get("t",0));oi_rows=sorted(b["oi"],key=lambda x:x.get("t",0))
        delta_btc=None;buy_btc=sell_btc=None;close_price=None
        if spot_rows:
            total_v=sum(_f(x.get("v")) or 0 for x in spot_rows);buy_btc=sum(_f(x.get("bv")) or 0 for x in spot_rows);sell_btc=max(0.0,total_v-buy_btc);delta_btc=buy_btc-sell_btc;cumulative_btc+=delta_btc;close_price=_f(spot_rows[-1].get("c"))
        oi_usd=_f(oi_rows[-1].get("c")) if oi_rows else None
        points.append({"ts":datetime.fromtimestamp(bucket+600,timezone.utc).isoformat(),"spot_cvd_delta_btc":delta_btc,"spot_cvd_cumulative_btc":cumulative_btc if delta_btc is not None else None,"spot_buy_btc":buy_btc,"spot_sell_btc":sell_btc,"spot_close_usd":close_price,"binance_oi_usd":oi_usd})
    return points[-144:]


def fetch_coinalyze_binance_flow_history(hours=24):
    """Tamamen Coinalyze kaynaklı Binance Spot CVD + Binance Perp OI, 10dk seri."""
    key=_clean_key(os.getenv("COINALYZE_API_KEY"));out={"source":"Coinalyze","venue":"Binance","interval_minutes":10,"window_hours":hours,"points":[],"ok":False,"error":None}
    if not key:out["error"]="COINALYZE_API_KEY tanımlı değil.";return out
    try:
        exchange_names=_exchange_map(_get("exchanges",key));spot_meta=_pick_binance_spot(_get("spot-markets",key),exchange_names);perp_meta=_pick_binance_perp(_get("future-markets",key),exchange_names)
        if not spot_meta:raise ValueError("Coinalyze Binance BTC spot market bulunamadı")
        if not perp_meta:raise ValueError("Coinalyze Binance BTC perpetual market bulunamadı")
        now=datetime.now(timezone.utc);frm=int((now-timedelta(hours=hours,minutes=20)).timestamp());to=int(now.timestamp());spot_symbol=spot_meta["symbol"];perp_symbol=perp_meta["symbol"]
        spot_rows=_get("ohlcv-history",key,{"symbols":spot_symbol,"interval":"5min","from":frm,"to":to});oi_rows=_get("open-interest-history",key,{"symbols":perp_symbol,"interval":"5min","from":frm,"to":to,"convert_to_usd":"true"})
        spot_hist=_hist_map(spot_rows).get(spot_symbol) or [];oi_hist=_hist_map(oi_rows).get(perp_symbol) or [];points=_pair_5m_to_10m(spot_hist,oi_hist)
        out.update({"ok":bool(points),"points":points,"spot_symbol":spot_symbol,"spot_symbol_on_exchange":spot_meta.get("symbol_on_exchange"),"perp_symbol":perp_symbol,"perp_symbol_on_exchange":perp_meta.get("symbol_on_exchange"),"spot_source":"Coinalyze Binance spot OHLCV buy/sell volume","oi_source":"Coinalyze Binance BTC perpetual OI history","definition":"Spot CVD = kümülatif (buy volume - sell volume). Coinalyze 5m v/bv serileri ikişer birleştirilerek 10m bucket yapılır; OI aynı 10m bucket'ta son 5m close snapshotıdır."})
    except Exception as e:out["error"]=str(e)[:300]
    return out


def fetch_coinalyze_btc(force=False):
    global _CACHE_VALUE,_CACHE_TS
    if not force and _CACHE_VALUE is not None and time.time()-_CACHE_TS<_CACHE_TTL_SECONDS:return _CACHE_VALUE
    key=_clean_key(os.getenv("COINALYZE_API_KEY"))
    out={"source":"Coinalyze","configured":bool(key),"ok":False,"markets":[],"by_exchange":{},"binance":None,"binance_available":False,"aggregate_oi_usd":None,"oi_change_24h_pct":None,"oi_weighted_funding_pct":None,"liquidations_24h":None,"long_short_ratio_avg":None,"total_all_exchanges":None,"core_exchanges":None,"note":None,"error":None}
    if not key:
        out["note"]="COINALYZE_API_KEY GitHub Secret olarak tanımlı değil.";_CACHE_VALUE=out;_CACHE_TS=time.time();return out
    try:
        exchange_names=_exchange_map(_get("exchanges",key));out["exchange_codes"]=exchange_names
        future_markets=_get("future-markets",key) or []

        # Ana Kripto görünümü: tüm desteklenen borsalardan birer ana BTC perpetual.
        all_markets=_all_exchange_markets(future_markets,exchange_names)
        all_symbols=[x["symbol"] for x in all_markets]
        oi_map,fund_map=_fetch_current_maps(key,all_symbols)
        total_all=_aggregate_current(all_markets,exchange_names,oi_map,fund_map)
        core3=_aggregate_current(all_markets,exchange_names,oi_map,fund_map,CORE_EXCHANGES)
        core3["exchanges"]=[x for x in ("Binance","OKX","Bybit") if any(r.get("exchange")==x for r in core3.get("markets") or [])]
        total_all["definition"]="Her desteklenen borsadan bir ana BTC perpetual kontratı; OI USD olarak toplanır, funding OI-ağırlıklı ortalamadır."
        core3["definition"]="Yalnız Binance + OKX + Bybit ana BTC perpetual kontratları; OI USD toplamı ve OI-ağırlıklı funding."
        out["total_all_exchanges"]=total_all;out["core_exchanges"]=core3
        out["aggregate_oi_usd"]=total_all.get("aggregate_oi_usd");out["oi_weighted_funding_pct"]=total_all.get("oi_weighted_funding_pct")

        # Kripto Türev uyumluluğu: seçili 7 büyük venue için 24s geçmiş + liquidation + L/S.
        picked=_pick_markets(future_markets,exchange_names,limit=7)
        symbols=[x["symbol"] for x in picked];symstr=",".join(symbols)
        now=datetime.now(timezone.utc);frm=int((now-timedelta(hours=26)).timestamp());to=int(now.timestamp());common={"symbols":symstr,"interval":"1hour","from":frm,"to":to}
        oi_hist=_get("open-interest-history",key,{**common,"convert_to_usd":"true"}) or []
        liq_hist=_get("liquidation-history",key,{**common,"convert_to_usd":"true"}) or []
        ls_hist=_get("long-short-ratio-history",key,common) or []
        oih=_hist_map(oi_hist);lqh=_hist_map(liq_hist);lsh=_hist_map(ls_hist)
        venue_rows=[];old_total=liq_long=liq_short=0.0;old_count=0;ratios=[];selected_current=0.0
        by_symbol={x["symbol"]:x for x in picked}
        for symbol in symbols:
            meta=by_symbol[symbol];code=str(meta.get("exchange",""));exchange=_canon_exchange(exchange_names.get(code,code));oi=oi_map.get(symbol);fund=fund_map.get(symbol);hist=oih.get(symbol) or [];oi_old=_f(hist[0].get("c")) if hist else None
            oi_change=(oi/oi_old-1)*100 if oi is not None and oi_old not in (None,0) else None
            liqs=lqh.get(symbol) or [];l_long=sum(_f(x.get("l")) or 0 for x in liqs);l_short=sum(_f(x.get("s")) or 0 for x in liqs);lsrows=lsh.get(symbol) or [];ratio=_f(lsrows[-1].get("r")) if lsrows else None
            if oi is not None:selected_current+=oi
            if oi_old is not None:old_total+=oi_old;old_count+=1
            liq_long+=l_long;liq_short+=l_short
            if ratio is not None:ratios.append(ratio)
            row={"exchange":exchange,"exchange_code":code,"symbol":symbol,"symbol_on_exchange":meta.get("symbol_on_exchange"),"open_interest_usd":oi,"open_interest_24h_ago_usd":oi_old,"open_interest_change_24h_pct":oi_change,"funding_pct":fund,"long_short_ratio":ratio,"long_liquidations_24h_usd":l_long,"short_liquidations_24h_usd":l_short,"total_liquidations_24h_usd":l_long+l_short}
            venue_rows.append(row);out["by_exchange"][exchange]=row
        out["markets"]=venue_rows;out["binance"]=out["by_exchange"].get("Binance");out["binance_available"]=bool(out["binance"])
        if selected_current>0 and old_count and old_total>0:out["oi_change_24h_pct"]=(selected_current/old_total-1)*100
        out["liquidations_24h"]={"long_usd":liq_long,"short_usd":liq_short,"total_usd":liq_long+liq_short,"dominant_side":"long" if liq_long>liq_short else "short" if liq_short>liq_long else "balanced"}
        out["long_short_ratio_avg"]=sum(ratios)/len(ratios) if ratios else None;out["market_count"]=len(venue_rows);out["all_exchange_count"]=total_all.get("exchange_count");out["ok"]=out["aggregate_oi_usd"] is not None
        out["note"]="Tüm-borsa görünümü her desteklenen borsadan bir ana BTC perpetual kontratını kapsar; Binance+OKX+Bybit ayrıca core-3 olarak hesaplanır."
    except Exception as e:out["error"]=str(e)[:300]
    _CACHE_VALUE=out;_CACHE_TS=time.time();return out
