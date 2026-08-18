"""Senaryo → Beklenti Matrisi."""

SCENARIOS = {
    "İdeal (CPI↓, Fed↓)": {"emoji":"🟢","koşul":"Enflasyon düşüyor VE Fed faiz indiriyor","S&P 500":"Çok iyi","Finansallar":"Çok iyi","Net Likidite":"Çok iyi","HY Spread":"Çok kötü (daralır)","IG Spread":"Çok kötü (daralır)","Dolar":"Kötü","Altın":"İyi","Tahvil":"Çok iyi"},
    "Yumuşak İniş": {"emoji":"🟡","koşul":"Enflasyon kademeli düşüyor, Fed temkinli indiriyor","S&P 500":"İyi","Finansallar":"İyi","Net Likidite":"İyi","HY Spread":"Kötü (daralır)","IG Spread":"Kötü (daralır)","Dolar":"Nötr","Altın":"İyi","Tahvil":"İyi"},
    "Fed Geride Kaldı": {"emoji":"🔴","koşul":"Enflasyon yükseliyor ama Fed henüz sıkılaştırmadı","S&P 500":"Kötü","Finansallar":"Kötü","Net Likidite":"İyi","HY Spread":"İyi (genişler)","IG Spread":"Nötr","Dolar":"Çok kötü","Altın":"Çok iyi","Tahvil":"Nötr"},
    "Pauz / Bekle-Gör": {"emoji":"🟢","koşul":"Enflasyon yatay, Fed faizi sabit tutuyor","S&P 500":"İyi","Finansallar":"Çok iyi","Net Likidite":"Nötr","HY Spread":"Kötü (daralır)","IG Spread":"Kötü (daralır)","Dolar":"Nötr","Altın":"Nötr","Tahvil":"İyi"},
    "Mevcut Durum Devam": {"emoji":"🟡","koşul":"Belirgin bir trend yok, veri karışık","S&P 500":"Nötr","Finansallar":"Nötr","Net Likidite":"Nötr","HY Spread":"Nötr","IG Spread":"Nötr","Dolar":"Nötr","Altın":"Nötr","Tahvil":"Nötr"},
    "Stagflasyon": {"emoji":"🔴","koşul":"Enflasyon yüksek/yükseliyor VE büyüme zayıflıyor","S&P 500":"Kötü","Finansallar":"Kötü","Net Likidite":"Kötü","HY Spread":"İyi (genişler)","IG Spread":"İyi (genişler)","Dolar":"Nötr","Altın":"İyi","Tahvil":"Kötü"},
    "Yeniden Faiz Artışı": {"emoji":"🔴","koşul":"Enflasyon yeniden yükseliyor, Fed faiz artırmayı düşünüyor","S&P 500":"Çok kötü","Finansallar":"Kötü","Net Likidite":"Çok kötü","HY Spread":"Çok iyi (genişler)","IG Spread":"Çok iyi (genişler)","Dolar":"Çok iyi","Altın":"Kötü","Tahvil":"Çok kötü"}
}


def guess_current_scenario(cpi_trend, fed_trend, growth_weak):
    if growth_weak and cpi_trend == "up": return "Stagflasyon"
    if cpi_trend == "up" and fed_trend == "up": return "Yeniden Faiz Artışı"
    if cpi_trend == "up" and fed_trend != "up": return "Fed Geride Kaldı"
    if cpi_trend == "down" and fed_trend == "down": return "İdeal (CPI↓, Fed↓)"
    if cpi_trend == "down" and fed_trend == "flat": return "Yumuşak İniş"
    if cpi_trend == "flat" and fed_trend == "flat": return "Pauz / Bekle-Gör"
    return "Mevcut Durum Devam"


def format_scenario_matrix(active_scenario=None):
    lines=["🎭 *Senaryo → Beklenti Matrisi* (referans tablo)"]
    for name,s in SCENARIOS.items():
        marker=" 👈 *ŞU AN BUNA YAKIN*" if name==active_scenario else ""
        lines.append(f"\n{s['emoji']} *{name}*{marker}")
        lines.append(f"   _{s['koşul']}_")
        lines.append(f"   S&P: {s['S&P 500']} · Altın: {s['Altın']} · Dolar: {s['Dolar']} · Tahvil: {s['Tahvil']}")
    return "\n".join(lines)
