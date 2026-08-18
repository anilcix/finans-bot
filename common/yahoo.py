"""Yahoo Finance'in ücretsiz, key gerektirmeyen chart endpoint'i."""
import requests
YAHOO_HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def fetch_yahoo_quote(symbol):
    r=requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",params={"interval":"1d","range":"5d"},headers=YAHOO_HEADERS,timeout=15)
    r.raise_for_status(); result=r.json().get("chart",{}).get("result")
    if not result: raise ValueError("Veri bulunamadı")
    meta=result[0]["meta"]; price=meta.get("regularMarketPrice"); prev=meta.get("previousClose") or meta.get("chartPreviousClose")
    if price is None: raise ValueError("Fiyat verisi yok")
    return price, ((price-prev)/prev*100 if prev else None)
