"""AJAN 2: KREDİ — spreadler, banka koşulları, kredi döngüsü ve tarihsel rejim testi."""
import random
from statistics import mean, median

from common.fred import latest_value, fetch_fred_history
from common.yahoo import fetch_yahoo_history
from common.regime import credit_cycle_phase
from common.report import safe_line, val_line, unavailable_note

PHASE_NAMES = ["Expansion (Boğa)", "Late Cycle (Dikkat)", "Recovery (Toparlanma)", "Contraction (Kriz)"]


def _line_history(series_id, limit=520):
    try:
        dates, vals = fetch_fred_history(series_id, limit=limit)
        return list(reversed([{"date": d, "value": v} for d, v in zip(dates, vals)]))
    except Exception:
        return []


def _trend(series_id, lag_short=21, lag_long=63):
    try:
        _, vals = fetch_fred_history(series_id, limit=max(lag_long + 5, 80))
        return {
            "change_1m": vals[0] - vals[lag_short] if len(vals) > lag_short else None,
            "change_3m": vals[0] - vals[lag_long] if len(vals) > lag_long else None,
        }
    except Exception:
        return {"change_1m": None, "change_3m": None}


def _one(series_id):
    try:
        d, v = latest_value(series_id)
        return {"date": d, "value": v}
    except Exception:
        return None


def _current_cycle():
    try:
        _, h = fetch_fred_history("BAMLH0A0HYM2", limit=320)
        now = h[0]
        avg200 = sum(h[:200]) / min(200, len(h))
        lag = min(125, len(h) - 1)
        ch6 = now - h[lag]
        phase, emoji, desc = credit_cycle_phase(now, avg200, ch6)
        return {"phase": phase, "emoji": emoji, "desc": desc, "hy_now": now, "hy_200dma": avg200, "hy_6m_change": ch6, "level_axis": now / avg200 if avg200 else None, "direction_axis": ch6}
    except Exception:
        return {"phase": None}


def _aligned_phase_history():
    """HY OAS günlük serisini S&P 500 haftalık tarihlerine taşı ve kredi döngüsü evresini hesapla."""
    try:
        hd, hv = fetch_fred_history("BAMLH0A0HYM2", limit=8000)
        hy = sorted(zip(hd, hv))
        sp = fetch_yahoo_history("^GSPC", range_="10y", interval="1wk")
    except Exception:
        return []
    if len(hy) < 220 or len(sp) < 60:
        return []
    hdates = [d for d, _ in hy]
    hvals = [v for _, v in hy]
    out=[]; j=0
    for d, px in sp:
        while j + 1 < len(hdates) and hdates[j + 1] <= d:
            j += 1
        if j < 200 or j < 125:
            continue
        now=hvals[j]; avg200=sum(hvals[j-199:j+1])/200; ch6=now-hvals[j-125]
        ph,_,_=credit_cycle_phase(now,avg200,ch6)
        out.append({"date":d,"sp500":px,"hy":now,"hy_200dma":avg200,"hy_6m_change":ch6,"phase":ph})
    return out


def _forward_stats(history):
    """Aynı fazın haftalık gözlemlerini 4 haftada bir örnekleyerek ileri S&P 500 getirilerini ölç."""
    if len(history) < 60:
        return {"by_phase":{},"current_phase":None,"method":"Yetersiz veri"}
    horizons={"1m":4,"3m":13,"6m":26,"12m":52}
    buckets={p:{k:[] for k in horizons} for p in PHASE_NAMES}
    for i in range(0,len(history),4):
        p=history[i]["phase"]; p0=history[i]["sp500"]
        if p not in buckets or not p0: continue
        for k,step in horizons.items():
            if i+step < len(history):
                p1=history[i+step]["sp500"]
                buckets[p][k].append((p1/p0-1)*100)
    by={}
    rng=random.Random(42)
    for p,hs in buckets.items():
        by[p]={}
        for k,arr in hs.items():
            if not arr: continue
            boots=[]
            for _ in range(1000):
                sample=[arr[rng.randrange(len(arr))] for __ in range(len(arr))]
                boots.append(mean(sample))
            boots.sort(); lo=boots[int(.025*(len(boots)-1))]; hi=boots[int(.975*(len(boots)-1))]
            by[p][k]={"mean":mean(arr),"median":median(arr),"positive_pct":sum(x>0 for x in arr)/len(arr)*100,"n":len(arr),"ci95":[lo,hi]}
    cur=history[-1]["phase"] if history else None
    return {"by_phase":by,"current_phase":cur,"method":"10 yıllık haftalık S&P 500 + HY OAS; fazlar aynı modelimizle; gözlemler 4 haftada bir; %95 bootstrap CI (1000 örnek)."}


def _phase_contrasts(stats):
    """12 aylık ortalama getiri farklarını basit yorum etiketiyle özetle; p-value iddiası üretme."""
    out=[]; by=stats.get("by_phase",{})
    pairs=[("Recovery (Toparlanma)","Contraction (Kriz)"),("Late Cycle (Dikkat)","Expansion (Boğa)")]
    for a,b in pairs:
        x=by.get(a,{}).get("12m"); y=by.get(b,{}).get("12m")
        if x and y:
            diff=x["mean"]-y["mean"]
            out.append({"contrast":f"{a} − {b}","difference_pp":diff,"note":"Pozitif fark ilk faz lehine; örneklem ve bootstrap CI ile birlikte okunmalı."})
    return out


def _spread_market_history():
    out={"hy":[],"bb":[],"ig":[],"ccc":[],"sp500":[]}
    for key,sid in (("hy","BAMLH0A0HYM2"),("bb","BAMLH0A1HYBB"),("ig","BAMLC0A0CM"),("ccc","BAMLH0A3HYC")):
        try: out[key]=_line_history(sid,800)
        except Exception: pass
    try: out["sp500"]=[{"date":d,"value":v} for d,v in fetch_yahoo_history("^GSPC",range_="3y",interval="1wk")]
    except Exception: pass
    return out


def build_report():
    lines=["💳 *KREDİ PİYASALARI*"]
    for name,sid in (("HY OAS","BAMLH0A0HYM2"),("IG OAS","BAMLC0A0CM"),("CCC OAS","BAMLH0A3HYC")):
        def f(s=sid,n=name):
            _,v=latest_value(s); return val_line(n,v,suffix="%",emoji="🏦",decimals=2)
        lines.append(safe_line(name,f))
    lines.append("")
    lines.append(unavailable_note(["CDS spreadleri (Bloomberg/Markit ücretli)"]))
    return "\n".join(lines)


def get_analysis_data():
    phase_hist=_aligned_phase_history(); phase_stats=_forward_stats(phase_hist)
    return {
        "hy_oas":_one("BAMLH0A0HYM2"),"bb_oas":_one("BAMLH0A1HYBB"),"ig_oas":_one("BAMLC0A0CM"),"ccc_oas":_one("BAMLH0A3HYC"),
        "sloos_credit_card":_one("DRTSCLCC"),"sloos_business_large":_one("DRTSCILM"),"sloos_business_small":_one("DRTSCIS"),
        "credit_card_delinquency":_one("DRCCLACBS"),"business_delinquency":_one("DRBLACBS"),
        "business_charge_off":_one("CORBLACBS"),"consumer_charge_off":_one("CORCACBS"),
        "spread_trends":{"hy":_trend("BAMLH0A0HYM2"),"ig":_trend("BAMLC0A0CM"),"ccc":_trend("BAMLH0A3HYC")},
        "history":{
            "hy":_line_history("BAMLH0A0HYM2"),"ig":_line_history("BAMLC0A0CM"),"ccc":_line_history("BAMLH0A3HYC"),
            "sloos_business":_line_history("DRTSCILM",80),"sloos_credit_card":_line_history("DRTSCLCC",80),
            "credit_card_delinquency":_line_history("DRCCLACBS",60),"business_delinquency":_line_history("DRBLACBS",60),
            "business_charge_off":_line_history("CORBLACBS",60),"consumer_charge_off":_line_history("CORCACBS",60),
        },
        "credit_cycle":_current_cycle(),"phase_history":phase_hist,"phase_forward_stats":phase_stats,"phase_contrasts":_phase_contrasts(phase_stats),
        "spread_market_history":_spread_market_history(),
        "method_note":"Kredi döngüsü: HY OAS seviyesi / 200 günlük ortalama ve yaklaşık 6 aylık yön. Geçmiş test kendi kurallarımızla hesaplanır; başka sitenin sonuçları kopyalanmaz.",
        "unavailable":["CDS spreadleri (Bloomberg/Markit ücretli)"],
    }
