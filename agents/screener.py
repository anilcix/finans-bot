"""AJAN 8: Top 200 coin hacim/OI tarayıcı."""
import requests,time
COINGECKO_BASE="https://api.coingecko.com/api/v3"; BINANCE_FAPI="https://fapi.binance.com"; BINANCE_DATA="https://fapi.binance.com/futures/data"

def _top_200():
    r=requests.get(f"{COINGECKO_BASE}/coins/markets",params={"vs_currency":"usd","order":"market_cap_desc","per_page":200,"page":1,"price_change_percentage":"24h"},timeout=20); r.raise_for_status(); return r.json()

def _symbols():
    r=requests.get(f"{BINANCE_FAPI}/fapi/v1/exchangeInfo",timeout=20); r.raise_for_status(); return {s["symbol"] for s in r.json()["symbols"] if s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT"}

def _oi_change(symbol):
    r=requests.get(f"{BINANCE_DATA}/openInterestHist",params={"symbol":symbol,"period":"1h","limit":24},timeout=15); r.raise_for_status(); d=r.json()
    if len(d)<2:return None
    a=float(d[0]["sumOpenInterest"]); b=float(d[-1]["sumOpenInterest"]); return None if a==0 else (b-a)/a*100

def scan_top_movers(min_volume_mcap_ratio=.15,min_oi_change=10,max_results=10,max_oi_checks=60):
    syms=_symbols(); candidates=[]
    for c in _top_200():
        m=c.get("market_cap") or 0; v=c.get("total_volume") or 0
        if not m: continue
        ratio=v/m
        if ratio>=min_volume_mcap_ratio: candidates.append({"symbol":c["symbol"].upper(),"name":c["name"],"price":c["current_price"],"change_24h":c.get("price_change_percentage_24h") or 0,"volume_mcap_ratio":ratio,"binance_symbol":c["symbol"].upper()+"USDT"})
    candidates=sorted(candidates,key=lambda x:x["volume_mcap_ratio"],reverse=True)[:max_oi_checks]; out=[]
    for c in candidates:
        if c["binance_symbol"] not in syms: continue
        try: ch=_oi_change(c["binance_symbol"])
        except Exception: ch=None
        if ch is not None and ch>=min_oi_change: c["oi_change_24h"]=ch; out.append(c)
        time.sleep(.05)
    return sorted(out,key=lambda x:x["oi_change_24h"],reverse=True)[:max_results]

def build_report():
    try: m=scan_top_movers()
    except Exception as e:return f"🔍 *TARAYICI*\n⚠️ {e}"
    return "\n".join(["🔍 *TARAYICI — Top 200 Coin*",f"• {x['symbol']}: OI {x['oi_change_24h']:+.1f}% · Hacim/MCap {x['volume_mcap_ratio']:.2f}" for x in m] if m else ["🔍 *TARAYICI — Top 200 Coin*","Şu an kriterlere uyan coin yok."])

def get_analysis_data():
    try:return {"movers":scan_top_movers(),"window":"24h","rule":"Hacim/MCap >= 0.15 ve OI artışı >= %10"}
    except Exception as e:return {"movers":[],"window":"24h","rule":"Hacim/MCap >= 0.15 ve OI artışı >= %10","error":str(e)}
