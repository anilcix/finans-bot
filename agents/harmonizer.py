"""MERKEZ HARMANLAYICI.

9 uzman ajanın mevcut çıktısını tekrar veri çekmeden birleştirir.
Amaç: mekanizma -> kısa vade -> alttaki neden -> teyit -> model yatırım görüşü.
Bu katman kişisel risk profili bilmez; yatırım görüşü model portföyü içindir.
"""
from statistics import mean


def _clamp(x,a=0,b=100): return max(a,min(b,x))
def _v(d,*path,default=None):
    cur=d
    for p in path:
        if not isinstance(cur,dict) or p not in cur:return default
        cur=cur[p]
    return cur


def _latest_news(data):
    items=[]
    for t in _v(data,"news","topics",default=[]) or []:
        for x in t.get("items",[]) or []:items.append(x)
    return sorted(items,key=lambda x:x.get("published_at",''),reverse=True)


def _buyback_news(news):
    keys=("buyback","buybacks","treasury steps up","bond yields dive","borç geri al","tahvil geri al")
    return [x for x in news if any(k in (x.get("title","").lower()) for k in keys)]


def _macro_score(m):return float(m.get("composite_score") or 50)


def _credit_score(c):
    phase=_v(c,"credit_cycle","phase",default="") or "";base=50
    if phase.startswith("Expansion"):base=76
    elif phase.startswith("Recovery"):base=62
    elif phase.startswith("Late"):base=43
    elif phase.startswith("Contraction"):base=20
    tr=c.get("spread_trends") or {};ccc=_v(tr,"ccc","change_3m");ig=_v(tr,"ig","change_3m");hy=_v(tr,"hy","change_3m")
    if ccc is not None and ccc>0.5:base-=10
    if ig is not None and ig>0.04:base-=5
    if hy is not None and hy<0:base+=4
    return _clamp(base)


def _options_score(o):
    vix=float(_v(o,"vix","price",default=20) or 20);ts=(o.get("term_structure") or "").upper();s=50
    if vix<16:s+=18
    elif vix<20:s+=8
    elif vix>28:s-=22
    if "CONTANGO" in ts:s+=10
    if "BACKWARD" in ts or "INVERT" in ts:s-=18
    return _clamp(s)


def _crypto_score(c,d):
    """Spot momentumu likidite ve on-chain teyidi olmadan tek başına ödüllendirmez."""
    btc=float(_v(c,"btc","change_24h",default=0) or 0);eth=float(_v(c,"eth","change_24h",default=0) or 0);fear=float(_v(d,"fear_greed","value",default=50) or 50)
    s=50+_clamp((btc+eth)/2,-12,12)*0.75
    if 40<=fear<=70:s+=4
    elif fear>85:s-=7
    elif fear<20:s-=4
    stable=_v(c,"stablecoin_7d_change_pct")
    if stable is not None:
        if stable>1:s+=5
        elif stable>0.25:s+=2
        elif stable<-1:s-=6
        elif stable<-0.25:s-=2
    acts=[_v(c,"network",a,"active_addresses_7d_change_pct") for a in ("btc","eth")]
    acts=[x for x in acts if x is not None]
    if acts:
        av=sum(acts)/len(acts)
        if av>10:s+=4
        elif av>2:s+=2
        elif av<-10:s-=4
    # Fiyat yükselirken Kraken CVD teyit etmiyorsa momentum puanını geri al.
    cvd=_v(d,"kraken","cvd_change_24h");oi24=_v(d,"kraken","open_interest_change_24h_pct")
    if btc>2 and cvd is not None and cvd<0:s-=7
    elif btc>0 and cvd is not None and cvd>0:s+=4
    if oi24 is not None and oi24>10:s-=5
    return _clamp(s)


def _deriv_score(d):
    s=50;gex=d.get("gex_musd");iv=d.get("iv_rank_pct");fund=_v(d,"funding","avg_pct");basis=d.get("spot_perp_basis_pct")
    if gex is not None:s+=7 if gex>0 else -8
    if iv is not None and iv>90:s-=10
    if fund is not None and fund>0.02:s-=10
    elif fund is not None and 0<fund<=0.02:s+=2
    if basis is not None and abs(basis)<0.15:s+=3
    kr=d.get("kraken") or {};oi24=kr.get("open_interest_change_24h_pct");cvd=kr.get("cvd_change_24h");ls=kr.get("long_short_ratio")
    if oi24 is not None:
        if oi24>10:s-=8
        elif oi24>4:s-=3
        elif oi24<-8:s+=2
    if cvd is not None:s+=4 if cvd>0 else -4
    if ls is not None:
        if ls>1.4:s-=6
        elif ls<0.65:s-=3
    hl=d.get("hyperliquid") or {};okx=d.get("okx") or {};rates=[x.get("funding_pct") for x in (hl,okx) if x.get("funding_pct") is not None]
    if len(rates)>=2 and all(x>0.03 for x in rates):s-=6
    elif len(rates)>=2 and all(0<=x<=0.02 for x in rates):s+=2
    return _clamp(s)


def _equity_score(e):
    tech=e.get("tech") or []
    if not tech:return 50
    changes=[x.get("change_pct") for x in tech if x.get("change_pct") is not None]
    if not changes:return 50
    avg=mean(changes);pos=sum(x>0 for x in changes)/len(changes)
    return _clamp(45+avg*3+pos*20)


def _quality(data,buyback):
    score=92;issues=[]
    if _v(data,"screener","error"):
        score-=12;issues.append("Tarayıcı ajanı veri hatası veriyor; coin tarama sinyali karar skoruna dahil edilmedi.")
    hp=data.get("hidden_pressure") or {}
    if len(hp.get("unavailable") or [])>=5:
        score-=7;issues.append("Gizli Baskı ajanında veri kapsamı dar; özel akışların bir bölümü henüz yok.")
    opt=data.get("options") or {}
    if len(opt.get("unavailable") or [])>=4:
        score-=5;issues.append("Opsiyon ajanında SPX dealer GEX/wall gibi ücretli metrikler eksik.")
    cr=data.get("crypto") or {};der=data.get("crypto_derivatives") or {}
    cq=int(_v(cr,"data_quality","ok_count",default=0) or 0);dq=int(_v(der,"data_quality","ok_count",default=0) or 0)
    if cq<3:
        score-=7;issues.append(f"Kripto spot/on-chain katmanında yalnızca {cq}/4 ana ücretsiz kaynak aktif.")
    if dq<3:
        score-=9;issues.append(f"Kripto türev katmanında yalnızca {dq}/4 ana ücretsiz kaynak aktif; türev sinyaline güven azaltıldı.")
    if not _v(cr,"binance_status","ok",default=True) and dq<3:
        score-=2;issues.append("Binance Futures GitHub runner'da erişilemiyor ve alternatif türev teyidi de yetersiz.")
    elif not _v(cr,"binance_status","ok",default=True) and dq>=3:
        issues.append("Binance Futures erişilemiyor; ancak Kraken + Hyperliquid + OKX/Deribit çapraz teyidi çalıştığı için ek kalite cezası uygulanmadı.")
    if buyback and buyback.get("errors"):
        score-=3;issues.append("Treasury buyback sonuç tablosunun bazı alanları otomatik çekilemeyebilir; tentative schedule ve haber teyidi ayrı tutuluyor.")
    return _clamp(score),issues


def _market_story(data,buyback):
    macro=data.get("macro") or {};credit=data.get("credit") or {};crypto=data.get("crypto") or {};der=data.get("crypto_derivatives") or {};opt=data.get("options") or {};eq=data.get("equities") or {}
    support=[];risks=[];cross=[];reading=macro.get("macro_reading") or {};support+=reading.get("short_term_support") or [];risks+=reading.get("structural_risks") or []
    phase=_v(credit,"credit_cycle","phase")
    if phase:support.append(f"Kredi döngüsü {phase}; HY spread seviyesi henüz geniş tabanlı stres göstermiyor.") if phase.startswith(("Expansion","Recovery")) else risks.append(f"Kredi döngüsü {phase}; kredi rejimi risk iştahını sınırlıyor.")
    ccc=_v(credit,"ccc_oas","value");ccc3=_v(credit,"spread_trends","ccc","change_3m")
    if ccc is not None and ccc3 is not None and ccc3>0.4:risks.append(f"CCC spreadi %{ccc:.2f} ve son 3 ayda +{ccc3:.2f} puan genişledi; düşük kaliteli kredide gizli stres var.")
    vix=_v(opt,"vix","price");ts=opt.get("term_structure")
    if vix is not None and vix<18 and ts and "CONTANGO" in ts.upper():support.append(f"VIX {vix:.2f} ve vade yapısı contango; opsiyon piyasası kısa vadede panik rejiminde değil.")

    btc=_v(crypto,"btc","change_24h");eth=_v(crypto,"eth","change_24h");iv=der.get("iv_rank_pct");posfund=_v(der,"funding","positive_pct")
    if btc is not None and eth is not None:cross.append(f"Kriptoda spot momentum: BTC 24s %{btc:+.1f}, ETH %{eth:+.1f}.")
    stable=_v(crypto,"stablecoin_7d_change_pct")
    if stable is not None:
        if stable>0.5:support.append(f"Stablecoin piyasa değeri 7 günde %{stable:+.2f}; kripto içi dolar likiditesi genişliyor.")
        elif stable<-0.5:risks.append(f"Stablecoin piyasa değeri 7 günde %{stable:+.2f}; kripto içi likidite daralıyor.")
    ba=_v(crypto,"network","btc","active_addresses_7d_change_pct");ea=_v(crypto,"network","eth","active_addresses_7d_change_pct")
    if ba is not None and ea is not None:
        if ba>0 and ea>0:cross.append(f"On-chain kullanım teyidi pozitif: BTC aktif adres 7g %{ba:+.1f}, ETH %{ea:+.1f}.")
        elif ba<0 and ea<0:risks.append(f"BTC ve ETH aktif adresleri aynı anda geriliyor: 7g BTC %{ba:+.1f}, ETH %{ea:+.1f}.")

    kr=der.get("kraken") or {};oi24=kr.get("open_interest_change_24h_pct");cvd=kr.get("cvd_change_24h");ls=kr.get("long_short_ratio")
    if btc is not None and cvd is not None:
        if btc>1 and cvd<0:risks.append("BTC yükselirken Kraken CVD negatif; fiyat hareketi agresif alıcı akışıyla teyit edilmiyor, kaldıraç kaynaklı yükseliş ihtimali var.")
        elif btc>0 and cvd>0:support.append("BTC yükselişi Kraken CVD tarafından da teyit ediliyor; agresif alıcı akışı fiyat yönüyle uyumlu.")
        elif btc<0 and cvd<0:risks.append("BTC düşüşü Kraken CVD ile teyit ediliyor; agresif satıcı baskısı devam ediyor.")
    if oi24 is not None:
        if oi24>10:risks.append(f"Kraken BTC OI 24 saatte %{oi24:+.1f}; kaldıraç çok hızlı birikiyor ve tasfiye/squeeze riski yükseliyor.")
        elif oi24>4:cross.append(f"Kraken BTC OI 24 saatte %{oi24:+.1f}; yeni kaldıraç girişi var, CVD/funding teyidiyle okunmalı.")
        elif oi24<-5:cross.append(f"Kraken BTC OI 24 saatte %{oi24:+.1f}; piyasa deleveraging yaşıyor.")
    if ls is not None and ls>1.35:risks.append(f"Kraken long/short {ls:.2f}; long tarafında kalabalıklaşma var.")
    hl=der.get("hyperliquid") or {};okx=der.get("okx") or {};rates=[x.get("funding_pct") for x in (hl,okx) if x.get("funding_pct") is not None]
    if len(rates)>=2:
        if all(x>0.03 for x in rates):risks.append("OKX ve Hyperliquid funding aynı anda yüksek pozitif; çapraz-borsada long carry kalabalıklaşıyor.")
        elif all(0<=x<=0.02 for x in rates):support.append("OKX ve Hyperliquid funding pozitif ama aşırı değil; perp talebi şimdilik kontrollü.")
    if iv is not None and iv>90:risks.append(f"Kripto opsiyon IV Rank %{iv:.0f}; oynaklık tarihsel olarak yüksek, yükselişi kovalamak riskli.")
    if posfund is not None and posfund>90:risks.append(f"Funding örneklerinin %{posfund:.0f}'ı pozitif; long tarafında kalabalıklaşma riski artmış.")

    tech=eq.get("tech") or [];com=eq.get("commodities") or [];losers=[x for x in tech if (x.get("change_pct") or 0)<-3]
    if losers:cross.append("Teknoloji içinde genişlik zayıf; bazı yüksek beta hisselerde sert satış varken endeks resmi daha sakin.")
    gold=next((x for x in com if x.get("label")=="Altın"),None);oil=next((x for x in com if "Petrol" in (x.get("label") or "")),None)
    if gold and (gold.get("change_pct") or 0)>2:cross.append(f"Altın %{gold.get('change_pct'):+.1f}; savunma/enflasyon hedge talebi aynı anda güçlü.")
    if oil and (oil.get("change_pct") or 0)>2:risks.append("Petrol de güçlü; büyüme desteği kadar enflasyon/jeopolitik baskı ihtimali de izlenmeli.")
    news=_latest_news(data);bbnews=_buyback_news(news)
    if bbnews:
        support.append("Hazine'nin uzun vadeli buyback adımı duration/dealer bilançosu tarafında kısa vadeli rahatlama yaratabilir.")
        risks.append("Buyback'i QE diye okumuyoruz: yeni ihraç/TGA finansmanı ve yüksek uzun-vade arzı nedeniyle kalıcı parasal genişleme sinyali değildir.")
    if buyback and buyback.get("schedule_count",0)>0:cross.append(f"Resmi Treasury tentative buyback takviminde {buyback.get('schedule_count')} operasyon kaydı otomatik izlendi; operasyon duyurusu takvimi supersede edebilir.")
    return support[:9],risks[:10],cross[:8],bbnews[:3]


def _investment_view(score,confidence,data):
    der=data.get("crypto_derivatives") or {}
    if score>=68:action="Seçici biçimde risk artır; yine de tek seferde tam pozisyona geçme."
    elif score>=55:action="Kademeli ve seçici risk al; nakit tamponunu koru, güçlü rallileri kovalamaktan kaçın."
    elif score>=45:action="Nötr kal; yeni risk eklemek için teyit bekle, mevcut pozisyonlarda kaliteyi artır."
    else:action="Riski azalt; likidite ve savunma ağırlığını yükselt, yüksek beta pozisyonları küçült."
    favored=["Geniş endeks / kaliteli büyük şirketler: tekil yüksek-beta teknolojiye göre daha dengeli.","Nakit veya kısa vadeli Hazine bonosu tamponu: yeni fırsatlar ve volatilite için opsiyonellik.","Altın: reel faiz/borç arzı ve makro belirsizliğe karşı portföy hedge'i olarak değerlendirilebilir."]
    avoid=["BTC/ETH dikey yükselirken OI hızla büyüyor fakat CVD teyit etmiyorsa FOMO alımı yapma.","Kredi kalitesi zayıf şirketlerde agresif risk almak; CCC spreadindeki bozulma teyit edilmeden göz ardı edilmemeli.","Tek bir buyback haberini 'QE başladı' kabul edip kaldıraç artırmak."]
    add=["CCC ve IG spreadleri yeniden daralmaya başlar, HY düşük kalırsa risk artırma teyidi.","VIX düşük kalıp contango korunur ve 10Y/30Y faizleri istikrar kazanırsa risk-on teyidi.","Kriptoda fiyat + CVD aynı yönde, OI kontrollü ve OKX/Hyperliquid funding aşırı değilse kripto riskini kademeli artır.","Makro kompozit skor 60+ bölgesine yerleşirse kademeli ek risk için daha güçlü zemin."]
    reduce=["HY OAS %4.0 üzerine çıkar veya kredi döngüsü Late Cycle/Contraction'a dönerse riski azalt.","VIX term structure backwardation/inversion'a dönerse kısa vadeli risk bütçesini düşür.","Kriptoda OI 24s çok hızlı artarken CVD ters yönde ve funding çapraz-borsada yükseliyorsa kaldıraçlı riski azalt.","Uzun vadeli faizler yeniden sert yükselirken CCC/IG spreadleri de açılırsa buyback rahatlamasının geçici kaldığını varsay."]
    return {"action":action,"favored":favored,"avoid":avoid,"add_risk_if":add,"reduce_risk_if":reduce,"confidence":confidence,"disclaimer":"Bu, ajanın genel piyasa koşullarına göre ürettiği model yatırım görüşüdür; kişisel risk toleransı, nakit ihtiyacı, mali durum veya vergi durumuna göre özelleştirilmiş tavsiye değildir."}


def synthesize(agent_data,buyback=None):
    macro=agent_data.get("macro") or {};credit=agent_data.get("credit") or {};crypto=agent_data.get("crypto") or {};der=agent_data.get("crypto_derivatives") or {};options=agent_data.get("options") or {};equities=agent_data.get("equities") or {}
    components={"macro":_macro_score(macro),"credit":_credit_score(credit),"options":_options_score(options),"crypto":_crypto_score(crypto,der),"crypto_derivatives":_deriv_score(der),"equities":_equity_score(equities)}
    weights={"macro":.28,"credit":.22,"options":.15,"crypto":.12,"crypto_derivatives":.10,"equities":.13}
    score=sum(components[k]*weights[k] for k in weights);quality,quality_issues=_quality(agent_data,buyback);score=50+(score-50)*(quality/100);score=_clamp(score)
    if score>=68:stance="Risk-On"
    elif score>=55:stance="Temkinli Risk-On"
    elif score>=45:stance="Nötr / Bekle-Gör"
    elif score>=32:stance="Temkinli Risk-Off"
    else:stance="Risk-Off"
    confidence=round(_clamp(quality*.78+15),0);support,risks,cross,bbnews=_market_story(agent_data,buyback)
    short="Kısa vadede kredi spreadleri, volatilite, likidite ve çapraz-varlık teyitleri birlikte risk iştahını belirliyor."
    medium="Orta vadede reel faiz, düşük kaliteli kredi, uzun-vade Hazine arzı ve kripto kaldıraç kalitesi ayrı risk katmanları olarak izleniyor."
    if score<45:
        short="Kısa vadeli destekler var ancak piyasa sinyalleri risk bütçesini artırmak için yeterli değil.";medium="Kredi, volatilite, faiz ve kripto akış teyitleri gelmeden savunmacı yaklaşım daha tutarlı."
    return {"market_score":round(score,1),"stance":stance,"confidence":confidence,"component_scores":{k:round(v,1) for k,v in components.items()},"plain_summary":[short,medium,"Tek bir veriyi tek başına yorumlamıyoruz: politika mekanizması, finansmanı, kredi teyidi, volatilite, on-chain likidite ve çapraz-borsa türev akışları birlikte okunuyor."],"supportive_factors":support,"risk_factors":risks,"cross_asset_read":cross,"investment_view":_investment_view(score,confidence,agent_data),"data_quality":{"score":quality,"issues":quality_issues},"treasury_buyback":buyback or {},"buyback_news":bbnews,"agent_status":{k:("error" if isinstance(v,dict) and v.get("error") else "ok") for k,v in agent_data.items()},"method":"9 uzman ajan -> normalize alt skorlar -> veri kalitesi cezası -> mekanizma + on-chain + çapraz-borsa türev + çapraz-varlık yorum katmanı."}


def build_report(result):
    iv=result.get("investment_view") or {}
    return f"🧠 *HARMANLAYICI*\nSkor: {result.get('market_score')}/100 — {result.get('stance')}\nGüven: %{result.get('confidence'):.0f}\n📌 {iv.get('action','')}"
