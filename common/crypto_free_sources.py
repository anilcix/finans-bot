"""Ücretsiz / public kripto veri kaynakları.

Amaç CoinGlass/Velo olmadan çapraz kaynak teyidi üretmek:
- Coin Metrics Community: BTC/ETH ağ aktivitesi
- DefiLlama free endpoints: DeFi TVL + stablecoin piyasa değeri
- Hyperliquid public info: BTC perp OI/funding/hacim
- Kraken Futures public charts: OI yönü, CVD, liquidation, long/short, basis, funding
- Coinalyze: ücretsiz key varsa durum kontrolü; key yoksa sistemi bozmaz

Her fonksiyon kendi hatasını payload içinde taşır; bir kaynağın hatası ajanı durdurmaz.
"""
from datetime import datetime, timedelta, timezone
import os
import statistics
import requests

UA={"User-Agent":"Mozilla/5.0 (compatible; finans-bot/1.0)","Accept":"application/json"}
COINMETRICS="https://community-api.coinmetrics.io/v4"
DEFILLAMA="https://api.llama.fi"
DEFILLAMA_STABLES="https://stablecoins.llama.fi"
HYPERLIQUID="https://api.hyperliquid.xyz/info"
KRAKEN_CHARTS="https://futures.kraken.com/api/charts/v1/analytics"
COINALYZE="https://api.coinalyze.net/v1"


def _f(x):
    try:return float(x)
    except (TypeError,ValueError):return None


def _pct_change(now,old):
    if now is None or old in (None,0):return None
    return (now/old-1)*100


def _last_numeric(values):
    """Farklı API shape'lerinden son sayısal değeri güvenli seçer."""
    if values is None:return None
    if isinstance(values,(int,float,str)):
        return _f(values)
    if isinstance(values,dict):
        for k in ("close","c","value","openInterest","cvd","ratio","basis","funding","rate"):
            if k in values:
                x=_last_numeric(values[k])
                if x is not None:return x
        for v in reversed(list(values.values())):
            x=_last_numeric(v)
            if x is not None:return x
        return None
    if isinstance(values,list):
        for v in reversed(values):
            x=_last_numeric(v)
            if x is not None:return x
    return None


def _numeric_series(data,preferred=()):
    """Kraken analytics response'undaki yaygın shape'leri tek numeric seri haline getirir."""
    target=data
    if isinstance(data,dict):
        for key in preferred:
            if key in data:
                target=data[key];break
    if isinstance(target,list):
        out=[]
        for row in target:
            x=_last_numeric(row)
            if x is not None:out.append(x)
        return out
    if isinstance(target,dict):
        for key in preferred:
            if key in target and isinstance(target[key],list):
                return _numeric_series(target[key])
    return []


def fetch_coinmetrics_network(days=10):
    out={"source":"Coin Metrics Community","ok":False,"btc":None,"eth":None,"error":None}
    try:
        now=datetime.now(timezone.utc)
        r=requests.get(
            f"{COINMETRICS}/timeseries/asset-metrics",
            params={
                "assets":"btc,eth","metrics":"AdrActCnt,TxCnt","frequency":"1d",
                "start_time":(now-timedelta(days=days)).date().isoformat(),
                "end_time":now.date().isoformat(),"page_size":1000,
            },headers=UA,timeout=18,
        )
        r.raise_for_status(); rows=r.json().get("data") or []
        for asset in ("btc","eth"):
            arr=sorted([x for x in rows if x.get("asset")==asset],key=lambda x:x.get("time",''))
            if not arr:continue
            last=arr[-1]; old=arr[max(0,len(arr)-8)]
            active=_f(last.get("AdrActCnt")); active_old=_f(old.get("AdrActCnt"))
            tx=_f(last.get("TxCnt")); tx_old=_f(old.get("TxCnt"))
            out[asset]={
                "date":(last.get("time") or "")[:10],
                "active_addresses":active,"active_addresses_7d_change_pct":_pct_change(active,active_old),
                "transactions":tx,"transactions_7d_change_pct":_pct_change(tx,tx_old),
            }
        out["ok"]=bool(out["btc"] or out["eth"])
    except Exception as e:out["error"]=str(e)[:220]
    return out


def fetch_defillama_snapshot():
    out={"source":"DefiLlama","ok":False,"total_tvl_usd":None,"chains":{},"stablecoin_market_cap_usd":None,"stablecoin_7d_change_pct":None,"errors":[]}
    try:
        r=requests.get(f"{DEFILLAMA}/v2/chains",headers=UA,timeout=18)
        if r.status_code>=400:
            r=requests.get(f"{DEFILLAMA}/chains",headers=UA,timeout=18)
        r.raise_for_status(); rows=r.json()
        if isinstance(rows,list):
            tvls=[_f(x.get("tvl")) for x in rows]; tvls=[x for x in tvls if x is not None and x>=0]
            out["total_tvl_usd"]=sum(tvls) if tvls else None
            names={"Ethereum","Solana","Arbitrum","Base","BSC","Bitcoin"}
            for x in rows:
                n=x.get("name")
                if n in names:out["chains"][n]=_f(x.get("tvl"))
    except Exception as e:out["errors"].append("TVL: "+str(e)[:160])
    try:
        r=requests.get(f"{DEFILLAMA_STABLES}/stablecoins",params={"includePrices":"true"},headers=UA,timeout=18)
        r.raise_for_status(); rows=(r.json().get("peggedAssets") or [])
        cur=old=0.0; ncur=nold=0
        for x in rows:
            c=x.get("circulating") or {}; p=x.get("circulatingPrevWeek") or {}
            cv=_f(c.get("peggedUSD")); pv=_f(p.get("peggedUSD"))
            if cv is not None:cur+=cv;ncur+=1
            if pv is not None:old+=pv;nold+=1
        if ncur:out["stablecoin_market_cap_usd"]=cur
        if nold and old:out["stablecoin_7d_change_pct"]=_pct_change(cur,old)
    except Exception as e:out["errors"].append("Stablecoin: "+str(e)[:160])
    out["ok"]=out["total_tvl_usd"] is not None or out["stablecoin_market_cap_usd"] is not None
    return out


def _hl_post(body):
    r=requests.post(HYPERLIQUID,json=body,headers={**UA,"Content-Type":"application/json"},timeout=18)
    r.raise_for_status();return r.json()


def fetch_hyperliquid_btc():
    out={"source":"Hyperliquid public API","ok":False,"error":None}
    try:
        payload=_hl_post({"type":"metaAndAssetCtxs"})
        if not isinstance(payload,list) or len(payload)<2:raise ValueError("metaAndAssetCtxs beklenen formatta değil")
        meta,ctxs=payload[0],payload[1]
        universe=(meta or {}).get("universe") or []
        idx=next((i for i,x in enumerate(universe) if x.get("name")=="BTC"),None)
        if idx is None or idx>=len(ctxs):raise ValueError("BTC perp bulunamadı")
        c=ctxs[idx]; mark=_f(c.get("markPx")); oi=_f(c.get("openInterest")); funding=_f(c.get("funding")); vol=_f(c.get("dayNtlVlm")); premium=_f(c.get("premium"))
        out.update({
            "ok":True,"mark_price":mark,"open_interest_btc":oi,
            "open_interest_usd":oi*mark if oi is not None and mark is not None else None,
            "funding_pct":funding*100 if funding is not None else None,
            "volume_24h_usd":vol,"premium_pct":premium*100 if premium is not None else None,
        })
        try:
            now=int(datetime.now(timezone.utc).timestamp()*1000)
            rows=_hl_post({"type":"fundingHistory","coin":"BTC","startTime":now-24*3600*1000,"endTime":now})
            rates=[_f(x.get("fundingRate")) for x in rows if isinstance(x,dict)];rates=[x for x in rates if x is not None]
            if rates:
                out["funding_24h_avg_pct"]=statistics.mean(rates)*100
                out["funding_positive_pct"]=sum(x>0 for x in rates)/len(rates)*100
                out["funding_samples"]=len(rates)
        except Exception:pass
    except Exception as e:out["error"]=str(e)[:220]
    return out


def _kraken_raw(symbol,kind,hours=48,interval=3600):
    since=int((datetime.now(timezone.utc)-timedelta(hours=hours)).timestamp())
    r=requests.get(f"{KRAKEN_CHARTS}/{symbol}/{kind}",params={"since":since,"interval":interval},headers=UA,timeout=18)
    r.raise_for_status(); payload=r.json(); result=payload.get("result") or {}
    if result.get("errors"):
        severe=[x for x in result.get("errors") if isinstance(x,dict) and x.get("severity") not in (None,"info")]
        if severe:raise ValueError(str(severe[:2]))
    return result


def fetch_kraken_btc_analytics():
    out={"source":"Kraken Futures public analytics","ok":False,"symbol":None,"errors":[]}
    symbol=None; oi_result=None
    for candidate in ("PI_XBTUSD","PF_XBTUSD"):
        try:
            oi_result=_kraken_raw(candidate,"open-interest");symbol=candidate;break
        except Exception as e:out["errors"].append(f"{candidate} OI: {str(e)[:100]}")
    if not symbol:return out
    out["symbol"]=symbol
    try:
        series=_numeric_series(oi_result.get("data"),("openInterest","value"))
        if series:
            out["open_interest_latest"]=series[-1]
            if len(series)>=2:out["open_interest_change_1h_pct"]=_pct_change(series[-1],series[-2])
            if len(series)>=25:out["open_interest_change_24h_pct"]=_pct_change(series[-1],series[-25])
            if len(series)>=8:
                m=statistics.mean(series); sd=statistics.pstdev(series)
                out["open_interest_zscore_48h"]=(series[-1]-m)/sd if sd else 0.0
    except Exception as e:out["errors"].append("OI parse: "+str(e)[:100])

    specs={
        "cvd":("cvd",("cvd",)),
        "long_short":("long-short-ratio",("ratio",)),
        "funding":("funding",("rate","funding")),
        "basis":("future-basis",("basis",)),
        "aggressor":("aggressor-differential",("value","differential")),
        "liquidations":("liquidation-volume",("value","volume")),
    }
    for name,(kind,keys) in specs.items():
        try:
            result=_kraken_raw(symbol,kind); series=_numeric_series(result.get("data"),keys)
            if not series:continue
            out[name+"_latest"]=series[-1]
            if name=="cvd" and len(series)>=2:
                out["cvd_change_24h"]=series[-1]-series[max(0,len(series)-25)]
            elif name=="long_short":out["long_short_ratio"]=series[-1]
            elif name=="funding":out["funding_latest"]=series[-1]
            elif name=="basis":out["basis_latest"]=series[-1]
            elif name=="aggressor":out["aggressor_diff_latest"]=series[-1]
            elif name=="liquidations":out["liquidation_volume_24h"]=sum(abs(x) for x in series[-24:])
        except Exception as e:out["errors"].append(f"{name}: {str(e)[:100]}")
    out["ok"]=any(k in out for k in ("open_interest_latest","cvd_latest","long_short_ratio","funding_latest","basis_latest"))
    return out


def fetch_coinalyze_status():
    """Ücretsiz API key varsa bağlantıyı doğrular. Key olmaması hata sayılmaz."""
    key=os.getenv("COINALYZE_API_KEY")
    out={"source":"Coinalyze","configured":bool(key),"ok":False,"note":None,"error":None}
    if not key:
        out["note"]="Ücretsiz API key henüz GitHub Secret olarak tanımlı değil; public kaynaklar kullanılmaya devam ediyor."
        return out
    try:
        r=requests.get(f"{COINALYZE}/exchanges",headers={**UA,"api_key":key},timeout=15)
        r.raise_for_status(); rows=r.json()
        out["ok"]=isinstance(rows,list) and len(rows)>0
        out["exchange_count"]=len(rows) if isinstance(rows,list) else None
    except Exception as e:out["error"]=str(e)[:220]
    return out


def fetch_free_crypto_stack():
    """Tek çağrıda tüm ücretsiz kaynakların durumunu ve verisini döndürür."""
    cm=fetch_coinmetrics_network(); dl=fetch_defillama_snapshot(); hl=fetch_hyperliquid_btc(); kr=fetch_kraken_btc_analytics(); ca=fetch_coinalyze_status()
    public=[cm,dl,hl,kr]
    ok_count=sum(1 for x in public if x.get("ok"))
    return {
        "coinmetrics":cm,"defillama":dl,"hyperliquid":hl,"kraken":kr,"coinalyze":ca,
        "public_sources_ok":ok_count,"public_sources_total":len(public),
        "quality_grade":"A" if ok_count>=4 else "B" if ok_count>=3 else "C" if ok_count>=2 else "D",
    }
