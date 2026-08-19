"""GitHub Pages için tüm uzman ajanları, Treasury buyback verisini ve Harmanlayıcıyı üretir."""
import json,os
from datetime import datetime,timezone
from agents import macro,credit,crypto,crypto_derivatives,options,equities,hidden_pressure,screener,news,harmonizer
from common.treasury_buyback import fetch_treasury_buybacks
from common.coinalyze import fetch_coinalyze_btc

OUTPUT_DIR=os.path.join(os.path.dirname(__file__),"docs","data")
AGENTS={"macro":macro,"credit":credit,"crypto":crypto,"crypto_derivatives":crypto_derivatives,"options":options,"equities":equities,"hidden_pressure":hidden_pressure,"screener":screener,"news":news}


def _write(name,data):
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,name+".json"),"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)


def _merge_coinalyze(data):
    ca=fetch_coinalyze_btc(); data["coinalyze"]=ca
    q=data.setdefault("data_quality",{})
    sources=q.setdefault("sources",{})
    sources["coinalyze"]=bool(ca.get("ok"))
    q["source_count"]=len(sources)
    q["ok_count"]=sum(1 for x in sources.values() if x)
    q["grade"]="A" if q["ok_count"]>=4 else "B" if q["ok_count"]>=3 else "C"
    q["coinalyze_configured"]=bool(ca.get("configured"))

    readings=data.setdefault("derivatives_reading",[])
    if ca.get("ok"):
        oi=ca.get("oi_change_24h_pct"); fw=ca.get("oi_weighted_funding_pct"); liq=ca.get("liquidations_24h") or {}
        if oi is not None:readings.append(f"Coinalyze çoklu-borsa BTC OI 24s %{oi:+.2f}.")
        if fw is not None:readings.append(f"Coinalyze OI-ağırlıklı funding %{fw:+.4f}.")
        if liq.get("total_usd") is not None:readings.append(f"Coinalyze 24s tasfiye toplamı ${liq['total_usd']/1e6:.1f}M; baskın taraf {liq.get('dominant_side','—')}.")
        b=ca.get("binance") or {}
        if ca.get("binance_available"):
            boi=b.get("open_interest_change_24h_pct"); bf=b.get("funding_pct"); bls=b.get("long_short_ratio")
            parts=["Binance (Coinalyze)"]
            if boi is not None:parts.append(f"OI 24s %{boi:+.2f}")
            if bf is not None:parts.append(f"funding %{bf:+.4f}")
            if bls is not None:parts.append(f"L/S {bls:.2f}")
            readings.append(" · ".join(parts)+".")
    return data


def main():
    now=datetime.now(timezone.utc).isoformat(); payloads={}
    for name,module in AGENTS.items():
        try:
            data=module.get_analysis_data()
            if name=="crypto_derivatives":data=_merge_coinalyze(data)
            data["generated_at"]=now
        except Exception as e:data={"generated_at":now,"error":str(e)}
        payloads[name]=data; _write(name,data); print("Yazıldı:",name)

    try: buyback=fetch_treasury_buybacks()
    except Exception as e: buyback={"generated_at":now,"error":str(e),"schedule":[],"recent_results":[]}
    _write("treasury_buybacks",buyback); print("Yazıldı: treasury_buybacks")

    try:
        center=harmonizer.synthesize(payloads,buyback); center["generated_at"]=now
    except Exception as e:
        center={"generated_at":now,"error":str(e)}
    _write("harmonizer",center); print("Yazıldı: harmonizer")

if __name__=="__main__":main()
