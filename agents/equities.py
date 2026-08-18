"""AJAN 6: AI/Tech hisseleri ve emtia."""
from common.yahoo import fetch_yahoo_quote
from common.report import safe_line, price_change_line, unavailable_note

TECH_TICKERS=[("QQQ","QQQ"),("SPY","SPY"),("NVDA","NVIDIA"),("MSFT","Microsoft"),("AMZN","Amazon"),("META","Meta"),("GOOGL","Alphabet"),("AAPL","Apple"),("AMD","AMD"),("AVGO","Broadcom"),("ORCL","Oracle"),("PLTR","Palantir")]
COMMODITY_TICKERS=[("GC=F","Altın"),("SI=F","Gümüş"),("BZ=F","Brent Petrol"),("CL=F","WTI Petrol")]

def _line(symbol,label):
    def fn():
        p,c=fetch_yahoo_quote(symbol); return price_change_line(label,p,c)
    return fn

def build_report():
    lines=["📈 *HİSSELER — AI / TECH*"]+[safe_line(l,_line(s,l)) for s,l in TECH_TICKERS]+["","🥇 *EMTİA*"]+[safe_line(l,_line(s,l)) for s,l in COMMODITY_TICKERS]
    lines+=['',unavailable_note(["AI ETF Flows","Hyperscaler CAPEX","Central Bank Gold Buying"])]
    return "\n".join(lines)

def get_analysis_data():
    def collect(items):
        rows=[]
        for symbol,label in items:
            try:
                price,chg=fetch_yahoo_quote(symbol); rows.append({"symbol":symbol,"label":label,"price":price,"change_pct":chg})
            except Exception: rows.append({"symbol":symbol,"label":label,"price":None,"change_pct":None})
        return rows
    return {"tech":collect(TECH_TICKERS),"commodities":collect(COMMODITY_TICKERS),"unavailable":["AI ETF Flows","Hyperscaler CAPEX","Central Bank Gold Buying"]}
