"""AJAN 1: Makro — tarihsel seviye + momentum + piyasa karşılaştırmaları."""
from common.fred import fetch_fred_history
from common.yahoo import fetch_yahoo_history
from common.stats import percentile_rank, risk_score, score_label
from common.regime import credit_cycle_phase, yield_curve_regime, hy_spread_warning, sloos_warning, ccc_hy_divergence_warning

LEVEL_WEIGHT = 0.65
MOMENTUM_WEIGHT = 0.35

# label, FRED series, units, higher_is_worse, history_limit, weight, ~1m lag, ~3m lag
BAROMETER_METRICS = [
    ("HY Kredi Spreadi", "BAMLH0A0HYM2", None, True, 1100, 2.0, 21, 63),
    ("Fed Politika Faizi", "FEDFUNDS", None, True, 240, 1.0, 1, 3),
    ("Enflasyon (CPI YoY)", "CPIAUCSL", "pc1", True, 240, 1.0, 1, 3),
    ("SLOOS — Kredi Kartı Standartları", "DRTSCLCC", None, True, 80, 1.0, None, 1),
    ("IG Kredi Spreadi", "BAMLC0A0CM", None, True, 1100, 0.5, 21, 63),
    ("İşsizlik Oranı", "UNRATE", None, True, 240, 0.5, 1, 3),
    ("Reel Faiz (Cleveland Fed 1Y)", "REAINTRATREARAT1YE", None, True, 240, 0.5, 1, 3),
    ("Reel Faiz (10Y TIPS)", "DFII10", None, True, 1100, 0.35, 21, 63),
    ("GDPNow Anlık Tahmin", "GDPNOW", None, False, 60, 0.65, None, 1),
    ("Gerçekleşmiş GDP (QoQ SAAR)", "A191RL1Q225SBEA", None, False, 80, 0.35, None, 1),
]


def _momentum(values, invert, lag1, lag3):
    parts=[]; out={"change_1m":None,"change_3m":None,"score":None}
    for key,lag in (("change_1m",lag1),("change_3m",lag3)):
        if lag is None or len(values) <= lag+5: continue
        cur=values[0]-values[lag]
        hist=[values[i]-values[i+lag] for i in range(len(values)-lag)]
        p=percentile_rank(hist,cur)
        parts.append(risk_score(p,invert)); out[key]=cur
    if parts: out["score"]=sum(parts)/len(parts)
    return out


def _entry(label, values, weight, invert, lag1=None, lag3=None):
    cur=values[0]; pct=percentile_rank(values,cur); level=risk_score(pct,invert); mom=_momentum(values,invert,lag1,lag3)
    combined=level if mom["score"] is None else LEVEL_WEIGHT*level+MOMENTUM_WEIGHT*mom["score"]
    lbl,emo=score_label(combined)
    return {"label":label,"value":cur,"percentile":pct,"weight":weight,"invert":invert,"level_score":level,"momentum_score":mom["score"],"change_1m":mom["change_1m"],"change_3m":mom["change_3m"],"combined_score":combined,"signal_label":lbl,"signal_emoji":emo}


def _yield_curve_history(limit=1100):
    d10,y10=fetch_fred_history("DGS10",limit=limit); d2,y2=fetch_fred_history("DGS2",limit=limit); m2=dict(zip(d2,y2)); pairs=[(d,v-m2[d]) for d,v in zip(d10,y10) if d in m2]
    if not pairs: raise ValueError("Yield curve verisi yok")
    return [d for d,_ in pairs],[v for _,v in pairs]


def _compute_barometer():
    out=[]
    for label,sid,units,invert,limit,w,l1,l3 in BAROMETER_METRICS:
        try:
            _,vals=fetch_fred_history(sid,limit=limit,units=units); out.append(_entry(label,vals,w,invert,l1,l3))
        except Exception: pass
    try:
        _,vals=_yield_curve_history(); out.append(_entry("Eğri Seviyesi (10Y-2Y)",vals,1.5,False,21,63))
    except Exception: pass
    return out


def _weighted_score(bar):
    tw=sum(x["weight"] for x in bar)
    return sum(x["combined_score"]*x["weight"] for x in bar)/tw if tw else None


def _series_points(series_id,limit=100,units=None,reverse=True):
    dates,vals=fetch_fred_history(series_id,limit=limit,units=units); pts=[{"date":d,"value":v} for d,v in zip(dates,vals) if v is not None]
    return list(reversed(pts)) if reverse else pts


def _macro_market_history():
    out={"core_pce":[],"fed_funds":[],"sp500":[]}
    try: out["core_pce"]=_series_points("PCEPILFE",72,"pc1")[-61:]
    except Exception: pass
    try: out["fed_funds"]=_series_points("FEDFUNDS",72)[-61:]
    except Exception: pass
    try: out["sp500"]=[{"date":d,"value":v} for d,v in fetch_yahoo_history("^GSPC",range_="5y",interval="1mo")[-61:]]
    except Exception: pass
    return out


def _credit_history():
    out={"hy":[],"ig":[],"ccc":[],"yield_curve":[]}
    for key,sid in (("hy","BAMLH0A0HYM2"),("ig","BAMLC0A0CM"),("ccc","BAMLH0A3HYC")):
        try: out[key]=_series_points(sid,800)[-520:]
        except Exception: pass
    try:
        d,v=_yield_curve_history(800); out["yield_curve"]=list(reversed([{"date":x,"value":y} for x,y in zip(d,v)]))[-520:]
    except Exception: pass
    return out


def _asset_history():
    out={}
    for key,sym in (("SPY","SPY"),("QQQ","QQQ"),("BTC","BTC-USD")):
        try:
            h=fetch_yahoo_history(sym,range_="5y",interval="1mo")[-61:]; base=h[0][1]; out[key]=[{"date":d,"value":v/base*100,"raw":v} for d,v in h]
        except Exception: out[key]=[]
    return out


def _score_history_current_method():
    """Yaklaşık aylık skor geçmişi. FRED'in bugün görünen revize edilmiş geçmiş serilerini kullanır; vintage backtest değildir."""
    try: anchors=[d for d,_ in fetch_yahoo_history("SPY",range_="5y",interval="1mo")[-61:]]
    except Exception: return []
    raw={}
    for label,sid,units,invert,limit,w,l1,l3 in BAROMETER_METRICS:
        try:
            dates,vals=fetch_fred_history(sid,limit=limit,units=units); raw[label]={"pairs":list(zip(dates,vals)),"invert":invert,"weight":w,"l1":l1,"l3":l3}
        except Exception: pass
    result=[]
    for anchor in anchors:
        entries=[]
        for label,s in raw.items():
            vals=[v for d,v in s["pairs"] if d<=anchor]
            if len(vals)<12: continue
            try: entries.append(_entry(label,vals,s["weight"],s["invert"],s["l1"],s["l3"]))
            except Exception: pass
        if len(entries)>=4:
            result.append({"date":anchor,"value":_weighted_score(entries)})
    return result


def get_analysis_data():
    bar=_compute_barometer(); score=_weighted_score(bar) if len(bar)>=4 else None; lbl,emo=score_label(score) if score is not None else (None,None)
    credit={"phase":None,"emoji":None,"desc":None}
    try:
        _,h=fetch_fred_history("BAMLH0A0HYM2",limit=260); now=h[0]; avg=sum(h[:200])/min(200,len(h)); idx=min(125,len(h)-1); p,e,d=credit_cycle_phase(now,avg,now-h[idx]); credit={"phase":p,"emoji":e,"desc":d}
    except Exception: pass
    yc={"regime":None,"emoji":None,"desc":None,"spread":None}
    try:
        _,v=_yield_curve_history(120); now=v[0]; old=v[min(63,len(v)-1)]; reg,e,d=yield_curve_regime(now,old); yc={"regime":reg,"emoji":e,"desc":d,"spread":now}
    except Exception: pass
    warnings=[]; hyp=None
    try:
        _,hy=fetch_fred_history("BAMLH0A0HYM2",limit=1100); bps=hy[0]*100; warnings.append({"name":"HY Kredi Spreadi","value":f"{bps:.0f} bps","warn":"400+ bps","crisis":"600+ bps","status":hy_spread_warning(bps)}); hyp=percentile_rank(hy,hy[0])
    except Exception: pass
    try:
        _,sl=fetch_fred_history("DRTSCLCC",limit=80); v=sl[0]; warnings.append({"name":"SLOOS — Kredi Kartı","value":f"%{v:+.1f}","warn":"+%10","crisis":"+%20","status":sloos_warning(v)})
    except Exception: pass
    try:
        if hyp is not None:
            _,cc=fetch_fred_history("BAMLH0A3HYC",limit=1100); cp=percentile_rank(cc,cc[0]); diff,status=ccc_hy_divergence_warning(cp,hyp); warnings.append({"name":"CCC-HY Ayrışması","value":f"fark {diff:+.0f} puan","warn":"30+","crisis":"50+","status":status})
    except Exception: pass
    return {"barometer":bar,"composite_score":score,"score_method":{"level_weight":LEVEL_WEIGHT,"momentum_weight":MOMENTUM_WEIGHT},"composite_label":lbl,"composite_emoji":emo,"credit_cycle":credit,"yield_curve":yc,"early_warnings":warnings,"macro_market_history":_macro_market_history(),"credit_history":_credit_history(),"asset_history":_asset_history(),"score_history":_score_history_current_method(),"backtest_note":"Geçmiş skor bugünkü revize edilmiş FRED serileriyle yaklaşık hesaplanır; gerçek vintage/point-in-time backtest değildir."}


def build_report():
    d=get_analysis_data(); s=d.get("composite_score"); return f"🌡️ *MAKRO*\nKompozit: {s:.0f}/100 — {d.get('composite_label')}" if s is not None else "🌡️ *MAKRO*\n⚠️ Veri alınamadı"
