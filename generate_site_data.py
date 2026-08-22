"""GitHub Pages için tüm uzman ajanları, Treasury buyback verisini ve Harmanlayıcıyı üretir."""
import json,os
from datetime import datetime,timezone
from agents import macro,credit,crypto,crypto_derivatives,options,equities,hidden_pressure,screener,news,harmonizer
from common.treasury_buyback import fetch_treasury_buybacks
from common.coinalyze import fetch_coinalyze_btc
from common.crypto_flow_history import update_history as update_crypto_flow_history

# Güvenilir haber whitelist'i: resmi kaynaklar + büyük finans yayıncıları.
# Google News yalnız keşif katmanıdır; news.py gerçek yayıncı URL'sini çözmeden
# ve izin verilen domaini doğrulamadan içeriği Harmanlayıcıya almaz.
news.GOOGLE_TRUSTED=[
    {
        "label":"Bitcoin",
        "query":"Bitcoin BTC crypto Reuters CoinDesk CNBC Yahoo Finance Bloomberg",
        "allowed":(
            "reuters.com","coindesk.com","cnbc.com","finance.yahoo.com",
            "yahoo.com","bloomberg.com",
        ),
    },
    {
        "label":"Makro / Fed / Hazine",
        "query":"Federal Reserve inflation CPI payrolls GDP Treasury yields Reuters CNBC Yahoo Finance Bloomberg",
        "allowed":(
            "reuters.com","cnbc.com","finance.yahoo.com","yahoo.com","bloomberg.com",
            "federalreserve.gov","bls.gov","bea.gov","home.treasury.gov","treasury.gov",
        ),
    },
]
news.SOURCE_POLICY={
    "Bitcoin":["CoinDesk","Reuters","CNBC","Yahoo Finance","Bloomberg"],
    "Makro":["Federal Reserve","U.S. Treasury","BLS","BEA","Reuters","CNBC","Yahoo Finance","Bloomberg"],
    "Şant Manukyan":["İş Yatırım resmi YouTube + transcript"],
    "X":["@realDonaldTrump","@elonmusk","@saylor — yalnız X API ile"],
}

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


def _decisive_market_view(center):
    """Metodolojiyi değil, sistemin mevcut piyasa kararını kısa ve net yazar."""
    score=float(center.get("market_score") or 50)
    stance=str(center.get("stance") or "Nötr")
    if score>=65:
        verdict="Ana görüş: risk varlıklarında yükseliş yönü güçlü. Geri çekilmeler şu aşamada satış sinyalinden çok pozisyon ekleme fırsatı olarak değerlendirilebilir; yine de kaldıraç kontrollü tutulmalı."
    elif score>=55:
        verdict="Ana görüş: yukarı yön hâlâ avantajlı, fakat güçlü bir risk-on rejiminde değiliz. Seçici şekilde risk alınabilir; agresif kaldıraç ve yükselişi kovalamak için yeterli teyit yok."
    elif score>=45:
        verdict="Ana görüş: piyasa yönü kararsız. Yeni büyük risk almak yerine mevcut pozisyonları korumak ve daha net teyit beklemek daha uygun."
    elif score>=35:
        verdict="Ana görüş: aşağı yönlü risk belirginleşmiş durumda. Yeni risk eklemek yerine pozisyon boyutunu küçültmek ve savunmayı artırmak daha uygun."
    else:
        verdict="Ana görüş: güçlü risk-off rejimi. Sermaye koruma öncelikli; yüksek beta ve kaldıraçlı pozisyonlardan kaçınmak daha uygun."

    support=[x for x in (center.get("supportive_factors") or []) if x]
    risks=[x for x in (center.get("risk_factors") or []) if x]
    why=[]
    if support:why.append("Pozitif taraf: "+support[0])
    if risks:why.append("Temkin nedeni: "+risks[0])
    reason=" ".join(why) if why else f"Mevcut birleşik skor {score:.0f}/100 ve rejim {stance}."

    iv=center.get("investment_view") or {}
    add=[x for x in (iv.get("add_risk_if") or []) if x]
    cut=[x for x in (iv.get("reduce_risk_if") or []) if x]
    if add and cut:
        trigger=f"Görüşü güçlendirecek teyit: {add[0]} Görüşü bozacak sinyal: {cut[0]}"
    elif cut:
        trigger=f"Görüşü bozacak ana sinyal: {cut[0]}"
    elif add:
        trigger=f"Daha güçlü risk almak için gereken ana teyit: {add[0]}"
    else:
        trigger="Bu görüş, kredi/volatilite ve likidite tarafında belirgin bir rejim değişimi oluşursa yeniden aşağı veya yukarı revize edilir."
    return [verdict,reason,trigger]


def main():
    now_dt=datetime.now(timezone.utc); now=now_dt.isoformat(); payloads={}
    for name,module in AGENTS.items():
        try:
            data=module.get_analysis_data()
            if name=="crypto_derivatives":data=_merge_coinalyze(data)
            data["generated_at"]=now
        except Exception as e:data={"generated_at":now,"error":str(e)}
        payloads[name]=data; _write(name,data); print("Yazıldı:",name)

    try:
        flow=update_crypto_flow_history(OUTPUT_DIR,payloads.get("crypto_derivatives") or {},now_dt)
        print("Yazıldı: crypto_flow_history",len(flow.get("points") or []),"nokta")
    except Exception as e:
        print("crypto_flow_history güncellenemedi:",e)

    try: buyback=fetch_treasury_buybacks()
    except Exception as e: buyback={"generated_at":now,"error":str(e),"schedule":[],"recent_results":[]}
    _write("treasury_buybacks",buyback); print("Yazıldı: treasury_buybacks")

    try:
        center=harmonizer.synthesize(payloads,buyback)
        center["plain_summary"]=_decisive_market_view(center)
        center["generated_at"]=now
    except Exception as e:
        center={"generated_at":now,"error":str(e)}
    _write("harmonizer",center); print("Yazıldı: harmonizer")

if __name__=="__main__":main()
