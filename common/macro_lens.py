"""Makro yorumlama çerçevesi: mekanizma, ilk etki, alttaki neden, ufuk ve teyit."""
from common.fred import fetch_fred_history


def _latest_with_change(series_id, limit, lag, scale=1.0):
    dates, vals = fetch_fred_history(series_id, limit=limit)
    cur = vals[0] / scale
    old = vals[min(lag, len(vals)-1)] / scale
    return {"date": dates[0], "value": cur, "change": cur-old}


def liquidity_plumbing():
    """Fed/Treasury piyasa tesisatı. Birimleri mümkün olduğunca $bn ve yüzde puan."""
    out={}
    try: out["tga"]=_latest_with_change("WTREGEN",20,4,1000.0)
    except Exception: out["tga"]=None
    try: out["fed_assets"]=_latest_with_change("WALCL",20,4,1000.0)
    except Exception: out["fed_assets"]=None
    try: out["rrp"]=_latest_with_change("RRPONTSYD",40,21,1.0)
    except Exception: out["rrp"]=None
    try: out["ust10"]=_latest_with_change("DGS10",40,21,1.0)
    except Exception: out["ust10"]=None
    try: out["ust30"]=_latest_with_change("DGS30",40,21,1.0)
    except Exception: out["ust30"]=None

    # Sık kullanılan basit rezerv/likidite proxy'si. Tek başına yatırım sinyali değildir.
    if out.get("fed_assets") and out.get("tga") and out.get("rrp"):
        cur=out["fed_assets"]["value"]-out["tga"]["value"]-out["rrp"]["value"]
        old=(out["fed_assets"]["value"]-out["fed_assets"]["change"])-(out["tga"]["value"]-out["tga"]["change"])-(out["rrp"]["value"]-out["rrp"]["change"])
        out["net_liquidity_proxy"]={"value":cur,"change":cur-old,"unit":"$bn","note":"Fed assets - TGA - ON RRP; mekanik proxy, nedensellik değildir."}
    else:
        out["net_liquidity_proxy"]=None
    return out


def _metric(barometer, key):
    key=key.lower()
    for m in barometer or []:
        if key in (m.get("label") or "").lower(): return m
    return None


def build_macro_reading(barometer, credit_cycle, yield_curve, early_warnings, plumbing):
    """Aynı veriyi tek yönlü değil, destek + alttaki kırılganlık olarak okur."""
    supportive=[]; structural=[]; confirmations=[]
    hy=_metric(barometer,"hy kredi"); cpi=_metric(barometer,"enflasyon"); real1=_metric(barometer,"cleveland"); real10=_metric(barometer,"10y tips"); gdp=_metric(barometer,"gdpnow"); sloos=_metric(barometer,"sloos")

    if hy:
        if (hy.get("change_3m") or 0) < 0: supportive.append("HY spread son 3 ayda daralıyor; kredi koşulları kısa vadede riskli varlıkları destekliyor.")
        if hy.get("percentile",50) < 20: confirmations.append("HY spread tarihsel olarak düşük bölgede; piyasa henüz geniş tabanlı kredi stresi fiyatlamıyor.")
    if gdp and gdp.get("value",0) > 2: supportive.append("GDPNow büyüme momentumu resesyon baskısını kısa vadede azaltıyor.")
    if credit_cycle and credit_cycle.get("phase"): confirmations.append(f"Kredi döngüsü modeli: {credit_cycle.get('phase')}.")

    if cpi and cpi.get("combined_score",50) < 40: structural.append("Enflasyon seviyesi hâlâ makro rahatlama alanını sınırlıyor.")
    if real1 and real1.get("combined_score",50) < 30: structural.append("1 yıllık reel faiz yüksek; finansal koşulların görünenden daha sıkı kalmasına yol açabilir.")
    if real10 and real10.get("combined_score",50) < 30: structural.append("10 yıllık reel faiz yüksek; uzun duration teknoloji/hisse değerlemeleri için yapısal baskı oluşturabilir.")
    if sloos and sloos.get("change_3m") is not None and sloos.get("change_3m") > 0: structural.append("Banka kredi standartları son çeyrekte sıkılaşıyor; piyasa fiyatı rahat olsa da kredi kanalı gecikmeli risk taşıyor.")

    u30=(plumbing or {}).get("ust30")
    tga=(plumbing or {}).get("tga")
    rrp=(plumbing or {}).get("rrp")
    fed=(plumbing or {}).get("fed_assets")
    if u30:
        if u30["change"] > 0.15: structural.append("30 yıllık Hazine faizi son ay belirgin yükseldi; uzun uçta arz/term-premium baskısı teyit istiyor.")
        elif u30["change"] < -0.15: supportive.append("30 yıllık faiz son ay geriliyor; duration baskısı kısa vadede hafifliyor.")
    if tga:
        if tga["change"] > 50: structural.append("TGA son 4 haftada yükseliyor; Hazine nakit birikimi banka rezervlerinden likidite çekebilir.")
        elif tga["change"] < -50: supportive.append("TGA düşüyor; Hazine harcaması sisteme kısa vadeli likidite bırakıyor.")
    if rrp and rrp["value"] < 20: structural.append("ON RRP tamponu neredeyse tükenmiş; yeni Hazine arzını absorbe edecek eski likidite yastığı çok daha küçük.")
    if fed:
        if fed["change"] > 25: supportive.append("Fed bilançosu son 4 haftada genişlemiş; fakat bunun QE olup olmadığı ayrıca mekanizma bazında kontrol edilmeli.")
        elif fed["change"] < -25: structural.append("Fed bilançosu daralıyor; piyasa rahatlaması varsa bunun kaynağı QE değil başka likidite kanalları olabilir.")

    # Erken uyarıları ikinci katman olarak koru.
    for w in early_warnings or []:
        st=w.get("status","")
        if "KRİZ" in st or "UYARI" in st:
            structural.append(f"Erken uyarı: {w.get('name')} {st}.")

    if supportive and structural: headline="Kısa vadeli rahatlama var, fakat alttaki kırılganlık sürüyor"
    elif supportive: headline="Kısa vadeli makro akış destekleyici"
    elif structural: headline="Makro tesisatta yapısal baskı baskın"
    else: headline="Makro görünüm karışık; tek yönlü sinyal yok"

    framework=[
        {"step":"1. Mekanizmayı sınıflandır","rule":"Fed QE/bilanço işlemi, Treasury borç yönetimi-buyback, mali harcama ve piyasa içi teknik akışı birbirine karıştırma."},
        {"step":"2. İlk etkiyi ölç","rule":"Faiz, volatilite, dealer bilançosu, kredi spreadi ve riskli varlıklar üzerindeki 1-20 günlük mekanik etkiyi ayrı yaz."},
        {"step":"3. Neden ihtiyaç duyulduğunu sor","rule":"Destekleyici bir müdahale otomatik olarak sağlıklı piyasa demek değildir; müdahalenin hangi stresi bastırmaya çalıştığını ara."},
        {"step":"4. Karşı finansmanı kontrol et","rule":"Bir alım/rahatlama varsa bunun hangi ihraç, TGA, bill arzı veya bilanço kalemiyle dengelendiğini kontrol et; net likiditeyi bul."},
        {"step":"5. Zaman ufkunu ayır","rule":"Kısa vade relief ile 1-3 aylık rejim ve 6-12 aylık yapısal trendi aynı sonuç cümlesine sıkıştırma."},
        {"step":"6. Teyit ara","rule":"10Y/30Y faiz, TGA, RRP, Fed bilançosu, HY/CCC spread, SLOOS ve volatilite aynı hikâyeyi doğruluyor mu bak."},
        {"step":"7. Hipotezi gerçek diye yazma","rule":"Seçim, politik niyet veya gizli amaç gibi motivasyonları resmi kanıt yoksa 'olası açıklama' olarak etiketle."},
    ]
    return {"headline":headline,"short_term_support":supportive[:5],"structural_risks":structural[:6],"confirmations":confirmations[:4],"framework":framework,"principle":"Piyasa desteğini hem etkisiyle hem de neden gerekli olduğuyla birlikte oku."}
