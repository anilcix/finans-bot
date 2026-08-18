"""AJAN 4: Kripto türev — Deribit opsiyon + Binance pozisyonlama."""
import requests
from datetime import datetime,timezone
from common.deribit import get_book_summary,get_index_price,get_historical_volatility,parse_instrument_name
from common.blackscholes import bs_gamma
from common.stats import percentile_rank
BINANCE_FAPI="https://fapi.binance.com"; BINANCE_DATA="https://fapi.binance.com/futures/data"

def _chain(currency="BTC"):
    ex={}
    for x in get_book_summary(currency):
        try:s,c,e=parse_instrument_name(x["instrument_name"])
        except Exception:continue
        ex.setdefault(e,[]).append((s,c,x.get("open_interest",0) or 0,x.get("mark_iv",0) or 0))
    if not ex:raise ValueError("Opsiyon verisi yok")
    return ex

def get_analysis_data(currency="BTC"):
    data={"fear_greed":None,"max_pain":None,"gex_musd":None,"iv_rank_pct":None,"current_iv":None,"funding":None,"positioning":None,"oi_zscore":None,"spot_perp_basis_pct":None}
    try:
        r=requests.get("https://api.alternative.me/fng/",timeout=15); r.raise_for_status(); d=r.json()["data"][0]; data["fear_greed"]={"value":int(d["value"]),"label":d["value_classification"]}
    except Exception: pass
    try:
        ex=_chain(currency); spot=get_index_price(currency); expiry=min(ex); chain=ex[expiry]; strikes=sorted(set(s for s,_,_,_ in chain)); pains={}
        for test in strikes:
            total=0
            for strike,is_call,oi,_ in chain:
                if is_call and test>strike:total+=(test-strike)*oi
                elif not is_call and test<strike:total+=(strike-test)*oi
            pains[test]=total
        mp=min(pains,key=pains.get); calls=sum(oi for _,c,oi,_ in chain if c); puts=sum(oi for _,c,oi,_ in chain if not c)
        data["max_pain"]={"strike":mp,"spot":spot,"expiry":expiry.isoformat(),"days_left":(expiry-datetime.now(timezone.utc)).days,"put_call_ratio":puts/calls if calls else 0}
    except Exception: pass
    try:
        summary=get_book_summary(currency); spot=get_index_price(currency); now=datetime.now(timezone.utc); g=0.0
        for x in summary:
            try:strike,is_call,expiry=parse_instrument_name(x["instrument_name"])
            except Exception:continue
            oi=x.get("open_interest",0) or 0; iv=x.get("mark_iv",0) or 0; t=(expiry-now).total_seconds()/(365*24*3600)
            if oi and iv and t>0:g+=(1 if is_call else -1)*bs_gamma(spot,strike,t,iv/100)*oi*(spot**2)*.01
        data["gex_musd"]=g/1e6
    except Exception: pass
    try:
        hist=get_historical_volatility(currency); vals=[v for _,v in hist]; data["current_iv"]=vals[-1]; data["iv_rank_pct"]=percentile_rank(vals,vals[-1])
    except Exception: pass
    try:
        r=requests.get(f"{BINANCE_FAPI}/fapi/v1/fundingRate",params={"symbol":f"{currency}USDT","limit":21},timeout=15); r.raise_for_status(); rates=[float(x["fundingRate"]) for x in r.json()]; avg=sum(rates)/len(rates); data["funding"]={"avg_pct":avg*100,"annualized_pct":avg*3*365*100,"positive_pct":sum(1 for x in rates if x>0)/len(rates)*100}
    except Exception: pass
    try:
        def lp(ep):
            r=requests.get(f"{BINANCE_DATA}/{ep}",params={"symbol":f"{currency}USDT","period":"1h","limit":1},timeout=15); r.raise_for_status(); return float(r.json()[0]["longAccount"])*100
        a=lp("topLongShortAccountRatio"); p=lp("topLongShortPositionRatio"); gl=lp("globalLongShortAccountRatio"); data["positioning"]={"top_account_long":a,"top_position_long":p,"global_long":gl,"whale_retail_gap":a-gl,"money_vs_heads_gap":p-a}
    except Exception: pass
    try:
        r=requests.get(f"{BINANCE_DATA}/openInterestHist",params={"symbol":f"{currency}USDT","period":"1h","limit":30},timeout=15); r.raise_for_status(); vals=[float(x["sumOpenInterest"]) for x in r.json()]; mean=sum(vals)/len(vals); std=(sum((v-mean)**2 for v in vals)/len(vals))**.5; data["oi_zscore"]=(vals[-1]-mean)/std if std else 0
    except Exception: pass
    try:
        r=requests.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex",params={"symbol":f"{currency}USDT"},timeout=15); r.raise_for_status(); x=r.json(); mark=float(x["markPrice"]); idx=float(x["indexPrice"]); data["spot_perp_basis_pct"]=(mark-idx)/idx*100
    except Exception: pass
    return data

def build_report():
    d=get_analysis_data(); mp=d.get("max_pain"); return f"₿📐 *KRİPTO TÜREV*\nMax Pain: ${mp['strike']:,.0f}" if mp else "₿📐 *KRİPTO TÜREV*\n⚠️ Veri alınamadı"
