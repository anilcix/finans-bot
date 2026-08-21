"""AJAN 3: KRİPTO — CoinGecko + Coin Metrics + DefiLlama + Coinalyze BTC OI/Funding."""
import requests
from common.report import safe_line, price_change_line, val_line, unavailable_note
from common.crypto_free_sources import fetch_coinmetrics_network, fetch_defillama_snapshot
from common.coinalyze import fetch_coinalyze_btc

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
OKX_BASE = "https://www.okx.com/api/v5"
BINANCE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _binance_probe():
    try:
        r=requests.get(f"{BINANCE_FAPI}/ping",timeout=6,headers=BINANCE_HEADERS);r.raise_for_status()
        return {"ok":True,"status":r.status_code,"message":"Binance Futures erişimi başarılı"}
    except requests.HTTPError as e:
        status=e.response.status_code if e.response is not None else None
        message="HTTP 451 — GitHub runner üzerinden Binance Futures erişimi reddedildi" if status==451 else str(e)
        return {"ok":False,"status":status,"message":message}
    except Exception as e:return {"ok":False,"status":None,"message":str(e)[:180]}


def _okx(path,params):
    r=requests.get(f"{OKX_BASE}{path}",params=params,timeout=15);r.raise_for_status();payload=r.json()
    if payload.get("code")!="0" or not payload.get("data"):raise ValueError(payload.get("msg") or "OKX veri döndürmedi")
    return payload["data"]


def _btc_eth():
    r=requests.get(f"{COINGECKO_BASE}/simple/price",params={"ids":"bitcoin,ethereum","vs_currencies":"usd","include_24hr_change":"true"},timeout=15);r.raise_for_status();d=r.json()
    return "\n".join(price_change_line(label,d[key]["usd"],d[key].get("usd_24h_change")) for key,label in [("bitcoin","BTC"),("ethereum","ETH")])


def _global_market():
    r=requests.get(f"{COINGECKO_BASE}/global",timeout=15);r.raise_for_status();d=r.json()["data"]
    total=d["total_market_cap"]["usd"];btc=d["market_cap_percentage"]["btc"];eth=d["market_cap_percentage"].get("eth",0)
    return "\n".join([val_line("BTC Dominance",btc,suffix="%",emoji="🟠"),val_line("TOTAL",total/1e12,suffix="T $",emoji="🌐"),val_line("TOTAL2",total*(1-btc/100)/1e12,suffix="T $",emoji="🌐"),val_line("TOTAL3",total*(1-btc/100-eth/100)/1e12,suffix="T $",emoji="🌐")])


def _stablecoin_top50_market_cap():
    r=requests.get(f"{COINGECKO_BASE}/coins/markets",params={"vs_currency":"usd","category":"stablecoins","order":"market_cap_desc","per_page":50},timeout=15);r.raise_for_status()
    return sum(c.get("market_cap",0) or 0 for c in r.json())


def _funding_value_fallback():
    try:
        r=requests.get(f"{BINANCE_FAPI}/premiumIndex",params={"symbol":"BTCUSDT"},timeout=6,headers=BINANCE_HEADERS);r.raise_for_status()
        return float(r.json()["lastFundingRate"])*100,"Binance"
    except Exception:
        row=_okx("/public/funding-rate-history",{"instId":"BTC-USDT-SWAP","limit":1})[0]
        return float(row.get("realizedRate") or row.get("fundingRate"))*100,"OKX"


def _open_interest_value_fallback():
    try:
        r=requests.get(f"{BINANCE_FAPI}/openInterest",params={"symbol":"BTCUSDT"},timeout=6,headers=BINANCE_HEADERS);r.raise_for_status()
        return float(r.json()["openInterest"]),"Binance"
    except Exception:
        row=_okx("/public/open-interest",{"instType":"SWAP","instId":"BTC-USDT-SWAP"})[0]
        return float(row["oiCcy"]),"OKX"


def _coinalyze_lines():
    ca=fetch_coinalyze_btc();total=ca.get("total_all_exchanges") or {};core=ca.get("core_exchanges") or {}
    if not ca.get("ok"):
        rate,rs=_funding_value_fallback();oi,os=_open_interest_value_fallback()
        return f"💰 BTC Funding ({rs} fallback): %{rate:+.4f}\n📐 BTC OI ({os} fallback): {oi:,.0f} BTC"
    toi=total.get("aggregate_oi_usd");tf=total.get("oi_weighted_funding_pct");coi=core.get("aggregate_oi_usd");cf=core.get("oi_weighted_funding_pct")
    return "\n".join([
        f"🌐 BTC OI — Tüm Borsalar: ${toi/1e9:.2f}B" if toi is not None else "🌐 BTC OI — Tüm Borsalar: —",
        f"💰 BTC Funding — Tüm Borsalar (OI-ağırlıklı): %{tf:+.4f}" if tf is not None else "💰 BTC Funding — Tüm Borsalar: —",
        f"🏦 BTC OI — Binance+OKX+Bybit: ${coi/1e9:.2f}B" if coi is not None else "🏦 BTC OI — Binance+OKX+Bybit: —",
        f"💵 BTC Funding — Binance+OKX+Bybit (OI-ağırlıklı): %{cf:+.4f}" if cf is not None else "💵 BTC Funding — Binance+OKX+Bybit: —",
    ])


def build_report():
    lines=["₿ *KRİPTO*",safe_line("BTC/ETH Fiyatları",_btc_eth),safe_line("Piyasa Genel Görünümü",_global_market),safe_line("Coinalyze BTC OI & Funding",_coinalyze_lines),"",unavailable_note(["ETF Flows","Exchange Reserves","MVRV","NUPL","SOPR","Miner Reserves","LTH Supply"])]
    return "\n".join(lines)


def get_analysis_data():
    data={
        "btc":None,"eth":None,"global":None,
        "stablecoin_supply_usd":None,
        "stablecoin_market_cap_usd":None,"stablecoin_source":None,"stablecoin_7d_change_pct":None,
        "defi":None,"network":None,
        "coinalyze":None,
        "funding_pct":None,"funding_source":None,
        "open_interest_btc":None,"open_interest_usd":None,"open_interest_source":None,
        "core3_open_interest_usd":None,"core3_funding_pct":None,"core3_exchanges":[],
        "binance_status":_binance_probe(),"data_quality":{},
    }
    try:
        r=requests.get(f"{COINGECKO_BASE}/simple/price",params={"ids":"bitcoin,ethereum","vs_currencies":"usd","include_24hr_change":"true"},timeout=15);r.raise_for_status();d=r.json()
        data["btc"]={"price":d["bitcoin"]["usd"],"change_24h":d["bitcoin"].get("usd_24h_change")}
        data["eth"]={"price":d["ethereum"]["usd"],"change_24h":d["ethereum"].get("usd_24h_change")}
    except Exception:pass

    try:
        r=requests.get(f"{COINGECKO_BASE}/global",timeout=15);r.raise_for_status();d=r.json()["data"]
        total=d["total_market_cap"]["usd"];btc=d["market_cap_percentage"]["btc"];eth=d["market_cap_percentage"].get("eth",0)
        data["global"]={"total_usd":total,"total2_usd":total*(1-btc/100),"total3_usd":total*(1-btc/100-eth/100),"btc_dominance":btc,"eth_dominance":eth}
    except Exception:pass

    try:
        top50=_stablecoin_top50_market_cap();data["stablecoin_supply_usd"]=top50;data["stablecoin_top50_market_cap_usd"]=top50
    except Exception:pass

    dl=fetch_defillama_snapshot();data["defi"]=dl
    if dl.get("stablecoin_market_cap_usd") is not None:
        data["stablecoin_market_cap_usd"]=dl["stablecoin_market_cap_usd"];data["stablecoin_source"]="DefiLlama";data["stablecoin_7d_change_pct"]=dl.get("stablecoin_7d_change_pct")
    elif data.get("stablecoin_top50_market_cap_usd") is not None:
        data["stablecoin_market_cap_usd"]=data["stablecoin_top50_market_cap_usd"];data["stablecoin_source"]="CoinGecko Top-50"

    cm=fetch_coinmetrics_network();data["network"]=cm

    ca=fetch_coinalyze_btc();data["coinalyze"]=ca
    total_ca=ca.get("total_all_exchanges") or {};core=ca.get("core_exchanges") or {}
    if ca.get("ok"):
        data["open_interest_usd"]=total_ca.get("aggregate_oi_usd");data["open_interest_source"]="Coinalyze · Tüm Borsalar"
        data["funding_pct"]=total_ca.get("oi_weighted_funding_pct");data["funding_source"]="Coinalyze · Tüm Borsalar · OI-ağırlıklı"
        data["core3_open_interest_usd"]=core.get("aggregate_oi_usd");data["core3_funding_pct"]=core.get("oi_weighted_funding_pct");data["core3_exchanges"]=core.get("exchanges") or []
        data["coinalyze_all_exchange_count"]=total_ca.get("exchange_count")
    else:
        try:data["funding_pct"],data["funding_source"]=_funding_value_fallback()
        except Exception:pass
        try:data["open_interest_btc"],data["open_interest_source"]=_open_interest_value_fallback()
        except Exception:pass

    checks={"coingecko":bool(data.get("btc") and data.get("global")),"defillama":bool(dl.get("ok")),"coinmetrics":bool(cm.get("ok")),"coinalyze":bool(ca.get("ok"))}
    ok=sum(1 for v in checks.values() if v)
    data["data_quality"]={"sources":checks,"ok_count":ok,"source_count":len(checks),"grade":"A" if ok==4 else "B" if ok>=3 else "C" if ok>=2 else "D"}
    return data
