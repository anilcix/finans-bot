"""AJAN 7: Gizli baskı / özel izleme."""
from common.yahoo import fetch_yahoo_quote
from common.report import safe_line, price_change_line, unavailable_note

UNAVAILABLE=["MSTR mNAV","BTC Treasury şirketleri","Token Unlocks","Whale/VC/Foundation Wallets","Miner Selling","SEC filing sinyal motoru","RWA/Tokenization","Asia Liquidity","Korea Retail Flow"]

def _mstr():
    p,c=fetch_yahoo_quote("MSTR"); return price_change_line("MSTR (Strategy)",p,c)

def build_report():
    return "\n".join(["🕵️ *GİZLİ BASKI + ÖZEL İZLEME*",safe_line("MSTR",_mstr),"",unavailable_note(UNAVAILABLE)])

def get_analysis_data():
    mstr=None
    try:
        p,c=fetch_yahoo_quote("MSTR"); mstr={"price":p,"change_pct":c}
    except Exception: pass
    return {"mstr":mstr,"unavailable":UNAVAILABLE}
