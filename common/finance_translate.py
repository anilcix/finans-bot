"""Finans haberleri için güvenli Türkçe çeviri katmanı.

Amaç genel makine çevirisinin finans jargonunu bozmasını engellemek.
Kritik terimler placeholder ile korunur, çeviri sonrası kontrollü Türkçe
karşılıklarına çevrilir. Şüpheli çıktı tespit edilirse None döner; çağıran
katman yanlış Türkçe göstermek yerine orijinal metni kullanabilir.
"""
import re
import requests

UA={"User-Agent":"Mozilla/5.0 (compatible; finans-bot/1.0; +market-research)"}
_CACHE={}

# Uzun ifadeler önce korunur.
PROTECTED_TERMS=[
    (r"\bshort squeeze\b", "__FIN_SHORT_SQUEEZE__", "short pozisyon sıkışması"),
    (r"\blong squeeze\b", "__FIN_LONG_SQUEEZE__", "long pozisyon sıkışması"),
    (r"\bshort covering\b", "__FIN_SHORT_COVERING__", "short pozisyon kapatma"),
    (r"\blong liquidation(?:s)?\b", "__FIN_LONG_LIQ__", "long pozisyon tasfiyesi"),
    (r"\bshort liquidation(?:s)?\b", "__FIN_SHORT_LIQ__", "short pozisyon tasfiyesi"),
    (r"\bopen interest\b", "__FIN_OPEN_INTEREST__", "açık pozisyon (OI)"),
    (r"\bfunding rate\b", "__FIN_FUNDING_RATE__", "funding oranı"),
    (r"\bbasis points?\b", "__FIN_BPS__", "baz puan"),
    (r"\btreasury buybacks?\b", "__FIN_TSY_BUYBACK__", "ABD Hazine tahvil geri alımları"),
    (r"\bbond buybacks?\b", "__FIN_BOND_BUYBACK__", "tahvil geri alımları"),
    (r"\bquantitative easing\b", "__FIN_QE__", "parasal genişleme (QE)"),
    (r"\byield curve\b", "__FIN_YIELD_CURVE__", "getiri eğrisi"),
    (r"\bcredit spread(?:s)?\b", "__FIN_CREDIT_SPREAD__", "kredi spreadi"),
    (r"\bterm premium\b", "__FIN_TERM_PREMIUM__", "vade primi"),
    (r"\brisk[- ]on\b", "__FIN_RISK_ON__", "risk-on"),
    (r"\brisk[- ]off\b", "__FIN_RISK_OFF__", "risk-off"),
]

# Makine çevirisinin finans bağlamında sık yaptığı hatalar.
SUSPICIOUS_PAIRS=[
    ("short squeeze", ("kısa vadeli daralma", "kısa sıkışma", "kısa vadeli sıkışma")),
    ("long squeeze", ("uzun vadeli daralma", "uzun sıkışma")),
    ("open interest", ("açık faiz",)),
    ("funding rate", ("finansman oranı", "fonlama oranı")),
    ("basis points", ("temel noktalar", "temel puan")),
]

POST_FIXES=(
    (r"\bkısa vadeli daralma\b", "short pozisyon sıkışması"),
    (r"\bkısa vadeli sıkışma\b", "short pozisyon sıkışması"),
    (r"\baçık faiz\b", "açık pozisyon (OI)"),
    (r"\btemel noktalar\b", "baz puan"),
)


def _protect(text):
    out=text
    used=[]
    for pattern,token,tr in PROTECTED_TERMS:
        if re.search(pattern,out,flags=re.I):
            out=re.sub(pattern,token,out,flags=re.I)
            used.append((token,tr))
    return out,used


def _restore(text,used):
    out=text
    # Google bazen placeholder içindeki alt çizgileri ayırabiliyor; tokenın sade formunu da düzelt.
    for token,tr in used:
        candidates={token,token.replace("_"," "),token.replace("__","")}
        for c in candidates:
            out=out.replace(c,tr)
    for pattern,repl in POST_FIXES:
        out=re.sub(pattern,repl,out,flags=re.I)
    return " ".join(out.split()).strip()


def _looks_suspicious(original,translated):
    o=original.lower();t=translated.lower()
    for source,bad_outputs in SUSPICIOUS_PAIRS:
        if source in o and any(x in t for x in bad_outputs):
            return True
    # Placeholder sızdıysa çeviri güvenli değildir.
    if "__fin_" in t or "fin short squeeze" in t or "fin open interest" in t:
        return True
    return False


def translate_finance_tr(text):
    """Finans terminolojisini koruyarak Türkçeye çevirir; şüpheli sonuçta None."""
    text=" ".join((text or "").split()).strip()
    if not text:return None
    if text in _CACHE:return _CACHE[text]
    protected,used=_protect(text)
    try:
        r=requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client":"gtx","sl":"auto","tl":"tr","dt":"t","q":protected},
            headers=UA,timeout=12,
        )
        r.raise_for_status();data=r.json()
        raw="".join(x[0] for x in (data[0] or []) if x and x[0]).strip()
        out=_restore(raw,used) if raw else None
        if not out or _looks_suspicious(text,out):out=None
    except Exception:
        out=None
    _CACHE[text]=out
    return out
