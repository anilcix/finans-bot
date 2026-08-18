"""AJAN 5: VIX / hisse opsiyon volatilitesi."""
from common.yahoo import fetch_yahoo_quote
from common.report import safe_line, price_change_line, unavailable_note

TICKERS=[("vix","^VIX","VIX"),("vix9d","^VIX9D","VIX9D"),("vix3m","^VIX3M","VIX3M")]

def _line(symbol,label):
    def fn():
        price,chg=fetch_yahoo_quote(symbol)
        return price_change_line(label,price,chg,emoji_pos="🔴",emoji_neg="🟢",prefix="")
    return fn

def build_report():
    lines=["📐 *OPSİYON / VOLATİLİTE*"]
    for _,symbol,label in TICKERS: lines.append(safe_line(label,_line(symbol,label)))
    lines.append(""); lines.append(unavailable_note(["SPX GEX","Zero Gamma","Call Wall","Put Wall","Dealer Gamma/Charm/Vanna","Put/Call Ratio"]))
    return "\n".join(lines)

def get_analysis_data():
    out={}
    for key,symbol,_ in TICKERS:
        try:
            price,chg=fetch_yahoo_quote(symbol); out[key]={"price":price,"change_pct":chg}
        except Exception: out[key]=None
    out["term_structure"]="CONTANGO / normal" if out.get("vix") and out.get("vix3m") and out["vix"]["price"]<out["vix3m"]["price"] else ("BACKWARDATION / stres" if out.get("vix") and out.get("vix3m") else None)
    out["unavailable"]=["SPX GEX","Zero Gamma","Call Wall","Put Wall","Dealer Gamma/Charm/Vanna","Put/Call Ratio"]
    return out
