"""AJAN 1: Makro — FRED + Yahoo; barometre, kompozit skor ve rejimler."""
from common.fred import fetch_fred_history
from common.yahoo import fetch_yahoo_history
from common.stats import percentile_rank,composite_score,score_label
from common.regime import credit_cycle_phase,yield_curve_regime,hy_spread_warning,sloos_warning,ccc_hy_divergence_warning

BAROMETER_METRICS=[
("HY Kredi Spreadi","BAMLH0A0HYM2",None,True,3900,2.0),
("Fed Politika Faizi","FEDFUNDS",None,True,180,1.0),
("Enflasyon (CPI YoY)","CPIAUCSL","pc1",True,180,1.0),
("Banka Kredi Sıkılığı (SLOOS)","DRTSCLCC",None,True,60,1.0),
("IG Kredi Spreadi","BAMLC0A0CM",None,True,3900,.5),
("İşsizlik Oranı","UNRATE",None,True,180,.5),
("Reel Faiz (10Y TIPS)","DFII10",None,True,3900,.5),
("GDP Büyümesi (QoQ SAAR)","A191RL1Q225SBEA",None,False,60,.5),
]

def _yield_curve_entry():
    _,a=fetch_fred_history("DGS10",limit=3900); _,b=fetch_fred_history("DGS2",limit=3900); n=min(len(a),len(b)); hist=[a[i]-b[i] for i in range(n)]; cur=hist[0]
    return ("Eğri Seviyesi (10Y-2Y)",cur,percentile_rank(hist,cur),1.5,False)

def _compute_barometer():
    out=[]
    for label,sid,units,invert,limit,w in BAROMETER_METRICS:
        try:
            _,vals=fetch_fred_history(sid,limit=limit,units=units); cur=vals[0]; out.append((label,cur,percentile_rank(vals,cur),w,invert))
        except Exception: pass
    try: out.append(_yield_curve_entry())
    except Exception: pass
    return out

def _macro_market_history():
    """Son ~5 yıl için Core PCE YoY, Fed Funds ve S&P 500 geçmişi."""
    out={"core_pce":[],"fed_funds":[],"sp500":[]}
    try:
        dates,vals=fetch_fred_history("PCEPILFE",limit=72,units="pc1")
        pts=[{"date":d,"value":v} for d,v in zip(dates,vals) if v is not None]
        out["core_pce"]=list(reversed(pts[:61]))
    except Exception:
        pass
    try:
        dates,vals=fetch_fred_history("FEDFUNDS",limit=72)
        pts=[{"date":d,"value":v} for d,v in zip(dates,vals) if v is not None]
        out["fed_funds"]=list(reversed(pts[:61]))
    except Exception:
        pass
    try:
        hist=fetch_yahoo_history("^GSPC",range_="5y",interval="1mo")
        out["sp500"]=[{"date":d,"value":v} for d,v in hist[-61:]]
    except Exception:
        pass
    return out

def get_analysis_data():
    bar=_compute_barometer(); comps=[(p,w,i) for _,_,p,w,i in bar]; score=composite_score(comps) if len(bar)>=4 else None; lbl,emo=score_label(score) if score is not None else (None,None)
    credit={"phase":None,"emoji":None,"desc":None}
    try:
        _,h=fetch_fred_history("BAMLH0A0HYM2",limit=260); now=h[0]; avg=sum(h[:200])/min(200,len(h)); idx=min(125,len(h)-1); phase,e,d=credit_cycle_phase(now,avg,now-h[idx]); credit={"phase":phase,"emoji":e,"desc":d}
    except Exception: pass
    yc={"regime":None,"emoji":None,"desc":None,"spread":None}
    try:
        _,y10=fetch_fred_history("DGS10",limit=100); _,y2=fetch_fred_history("DGS2",limit=100); now=y10[0]-y2[0]; idx=min(63,len(y10)-1,len(y2)-1); old=y10[idx]-y2[idx]; reg,e,d=yield_curve_regime(now,old); yc={"regime":reg,"emoji":e,"desc":d,"spread":now}
    except Exception: pass
    warnings=[]; hyp=None
    try:
        _,hy=fetch_fred_history("BAMLH0A0HYM2",limit=3900); bps=hy[0]*100; warnings.append({"name":"HY Kredi Spreadi","value":f"{bps:.0f} bps","warn":"400+ bps","crisis":"600+ bps","status":hy_spread_warning(bps)}); hyp=percentile_rank(hy,hy[0])
    except Exception: pass
    try:
        _,sl=fetch_fred_history("DRTSCLCC",limit=60); v=sl[0]; warnings.append({"name":"SLOOS","value":f"%{v:+.1f}","warn":"+%10","crisis":"+%20","status":sloos_warning(v)})
    except Exception: pass
    try:
        if hyp is not None:
            _,cc=fetch_fred_history("BAMLH0A3HYC",limit=3900); cp=percentile_rank(cc,cc[0]); diff,status=ccc_hy_divergence_warning(cp,hyp); warnings.append({"name":"CCC-HY Ayrışması","value":f"fark {diff:+.0f} puan","warn":"30+","crisis":"50+","status":status})
    except Exception: pass
    return {"barometer":[{"label":l,"value":v,"percentile":p,"weight":w,"invert":i} for l,v,p,w,i in bar],"composite_score":score,"composite_label":lbl,"composite_emoji":emo,"credit_cycle":credit,"yield_curve":yc,"early_warnings":warnings,"macro_market_history":_macro_market_history()}

def build_report():
    d=get_analysis_data(); s=d.get("composite_score"); return f"🌡️ *MAKRO*\nKompozit: {s:.0f}/100 — {d.get('composite_label')}" if s is not None else "🌡️ *MAKRO*\n⚠️ Veri alınamadı"
