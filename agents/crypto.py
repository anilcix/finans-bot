"""AJAN 3: KRİPTO — CoinGecko + Binance Futures."""
import requests
from common.report import safe_line, price_change_line, val_line, unavailable_note
COINGECKO_BASE="https://api.coingecko.com/api/v3"
BINANCE_FAPI="https://fapi.binance.com/fapi/v1"

def _btc_eth():
    r=requests.get(f"{COINGECKO_BASE}/simple/price",params={"ids":"bitcoin,ethereum","vs_currencies":"usd","include_24hr_change":"true"},timeout=15); r.raise_for_status(); d=r.json()
    return "\n".join(price_change_line(label,d[key]["usd"],d[key].get("usd_24h_change")) for key,label in [("bitcoin","BTC"),("ethereum","ETH")])

def _global_market():
    r=requests.get(f"{COINGECKO_BASE}/global",timeout=15); r.raise_for_status(); d=r.json()["data"]
    total=d["total_market_cap"]["usd"]; btc=d["market_cap_percentage"]["btc"]; eth=d["market_cap_percentage"].get("eth",0)
    return "\n".join([val_line("BTC Dominance",btc,suffix="%",emoji="🟠"),val_line("TOTAL",total/1e12,suffix="T $",emoji="🌐"),val_line("TOTAL2",total*(1-btc/100)/1e12,suffix="T $",emoji="🌐"),val_line("TOTAL3",total*(1-btc/100-eth/100)/1e12,suffix="T $",emoji="🌐")])

def _stablecoin_supply():
    r=requests.get(f"{COINGECKO_BASE}/coins/markets",params={"vs_currency":"usd","category":"stablecoins","order":"market_cap_desc","per_page":50},timeout=15); r.raise_for_status()
    return val_line("Stablecoin Toplam Arzı",sum(c.get("market_cap",0) or 0 for c in r.json())/1e9,suffix="B $",emoji="🪙",decimals=1)

def _funding_rate():
    r=requests.get(f"{BINANCE_FAPI}/premiumIndex",params={"symbol":"BTCUSDT"},timeout=15); r.raise_for_status(); rate=float(r.json()["lastFundingRate"])*100
    return f"💰 BTC Funding Rate: %{rate:+.4f}"

def _open_interest():
    r=requests.get(f"{BINANCE_FAPI}/openInterest",params={"symbol":"BTCUSDT"},timeout=15); r.raise_for_status(); return val_line("BTC Open Interest",float(r.json()["openInterest"]),suffix=" BTC",emoji="📐",decimals=0)

def build_report():
    lines=["₿ *KRİPTO*",safe_line("BTC/ETH Fiyatları",_btc_eth),safe_line("Piyasa Genel Görünümü",_global_market),safe_line("Stablecoin Arzı",_stablecoin_supply),safe_line("Funding Rate",_funding_rate),safe_line("Open Interest",_open_interest),"",unavailable_note(["Exchange Reserves","ETF Flows","CVD","Liquidations","MVRV","NUPL","SOPR","Miner Reserves","LTH Supply"])]
    return "\n".join(lines)

def get_analysis_data():
    data={"btc":None,"eth":None,"global":None,"stablecoin_supply_usd":None,"funding_pct":None,"open_interest_btc":None}
    try:
        r=requests.get(f"{COINGECKO_BASE}/simple/price",params={"ids":"bitcoin,ethereum","vs_currencies":"usd","include_24hr_change":"true"},timeout=15); r.raise_for_status(); d=r.json(); data["btc"]={"price":d["bitcoin"]["usd"],"change_24h":d["bitcoin"].get("usd_24h_change")}; data["eth"]={"price":d["ethereum"]["usd"],"change_24h":d["ethereum"].get("usd_24h_change")}
    except Exception: pass
    try:
        r=requests.get(f"{COINGECKO_BASE}/global",timeout=15); r.raise_for_status(); d=r.json()["data"]; total=d["total_market_cap"]["usd"]; btc=d["market_cap_percentage"]["btc"]; eth=d["market_cap_percentage"].get("eth",0); data["global"]={"total_usd":total,"total2_usd":total*(1-btc/100),"total3_usd":total*(1-btc/100-eth/100),"btc_dominance":btc,"eth_dominance":eth}
    except Exception: pass
    try:
        r=requests.get(f"{COINGECKO_BASE}/coins/markets",params={"vs_currency":"usd","category":"stablecoins","order":"market_cap_desc","per_page":50},timeout=15); r.raise_for_status(); data["stablecoin_supply_usd"]=sum(c.get("market_cap",0) or 0 for c in r.json())
    except Exception: pass
    try:
        r=requests.get(f"{BINANCE_FAPI}/premiumIndex",params={"symbol":"BTCUSDT"},timeout=15); r.raise_for_status(); data["funding_pct"]=float(r.json()["lastFundingRate"])*100
    except Exception: pass
    try:
        r=requests.get(f"{BINANCE_FAPI}/openInterest",params={"symbol":"BTCUSDT"},timeout=15); r.raise_for_status(); data["open_interest_btc"]=float(r.json()["openInterest"])
    except Exception: pass
    return data
