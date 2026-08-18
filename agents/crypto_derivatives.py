"""AJAN 4: Kripto türev — Deribit opsiyon + Binance; OKX/Bybit fallback."""
import requests
from datetime import datetime, timezone
from common.deribit import get_book_summary, get_index_price, get_historical_volatility, parse_instrument_name
from common.blackscholes import bs_gamma
from common.stats import percentile_rank

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_DATA = "https://fapi.binance.com/futures/data"
OKX_BASE = "https://www.okx.com/api/v5"
BYBIT_BASE = "https://api.bybit.com/v5"
BINANCE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _binance_probe():
    try:
        r = requests.get(f"{BINANCE_FAPI}/fapi/v1/ping", timeout=6, headers=BINANCE_HEADERS)
        r.raise_for_status()
        return {"ok": True, "status": r.status_code, "message": "Binance Futures erişimi başarılı"}
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        message = "HTTP 451 — GitHub runner üzerinden Binance Futures erişimi reddedildi" if status == 451 else str(e)
        return {"ok": False, "status": status, "message": message}
    except Exception as e:
        return {"ok": False, "status": None, "message": str(e)[:180]}


def _okx(path, params):
    r = requests.get(f"{OKX_BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != "0" or not payload.get("data"):
        raise ValueError(payload.get("msg") or "OKX veri döndürmedi")
    return payload["data"]


def _bybit(path, params):
    r = requests.get(f"{BYBIT_BASE}{path}", params=params, timeout=10)
    r.raise_for_status()
    payload = r.json()
    if payload.get("retCode") != 0:
        raise ValueError(payload.get("retMsg") or "Bybit veri döndürmedi")
    return payload.get("result", {})


def _chain(currency="BTC"):
    expiries = {}
    for x in get_book_summary(currency):
        try:
            strike, is_call, expiry = parse_instrument_name(x["instrument_name"])
        except Exception:
            continue
        expiries.setdefault(expiry, []).append((strike, is_call, x.get("open_interest", 0) or 0, x.get("mark_iv", 0) or 0))
    if not expiries:
        raise ValueError("Opsiyon verisi yok")
    return expiries


def _funding_stats(currency="BTC"):
    symbol = f"{currency}USDT"
    try:
        r = requests.get(f"{BINANCE_FAPI}/fapi/v1/fundingRate", params={"symbol": symbol, "limit": 21}, timeout=6, headers=BINANCE_HEADERS)
        r.raise_for_status()
        rates = [float(x["fundingRate"]) for x in r.json()]
        source = "Binance"
    except Exception:
        rows = _okx("/public/funding-rate-history", {"instId": f"{currency}-USDT-SWAP", "limit": 21})
        rates = [float(x.get("realizedRate") or x.get("fundingRate")) for x in rows]
        source = "OKX"
    avg = sum(rates) / len(rates)
    return {"avg_pct": avg * 100, "annualized_pct": avg * 3 * 365 * 100, "positive_pct": sum(1 for x in rates if x > 0) / len(rates) * 100, "source": source, "samples": len(rates)}


def _positioning(currency="BTC"):
    symbol = f"{currency}USDT"
    try:
        def lp(endpoint):
            r = requests.get(f"{BINANCE_DATA}/{endpoint}", params={"symbol": symbol, "period": "1h", "limit": 1}, timeout=6, headers=BINANCE_HEADERS)
            r.raise_for_status()
            return float(r.json()[0]["longAccount"]) * 100
        top_accounts = lp("topLongShortAccountRatio")
        top_positions = lp("topLongShortPositionRatio")
        global_long = lp("globalLongShortAccountRatio")
        return {"top_account_long": top_accounts, "top_position_long": top_positions, "global_long": global_long, "whale_retail_gap": top_accounts - global_long, "money_vs_heads_gap": top_positions - top_accounts, "source": "Binance", "mode": "top_traders"}
    except Exception:
        result = _bybit("/market/account-ratio", {"category": "linear", "symbol": symbol, "period": "1h", "limit": 1})
        rows = result.get("list") or []
        if not rows:
            raise ValueError("Bybit long/short verisi yok")
        row = rows[0]
        return {"global_long": float(row["buyRatio"]) * 100, "global_short": float(row["sellRatio"]) * 100, "source": "Bybit", "mode": "market_account_ratio"}


def _oi_metrics(currency="BTC"):
    symbol = f"{currency}USDT"
    try:
        r = requests.get(f"{BINANCE_DATA}/openInterestHist", params={"symbol": symbol, "period": "1h", "limit": 30}, timeout=6, headers=BINANCE_HEADERS)
        r.raise_for_status()
        vals = [float(x["sumOpenInterest"]) for x in r.json()]
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        return {"zscore": (vals[-1] - mean) / std if std else 0, "open_interest_btc": vals[-1], "source": "Binance"}
    except Exception:
        pass
    try:
        result = _bybit("/market/open-interest", {"category": "linear", "symbol": symbol, "intervalTime": "1h", "limit": 30})
        rows = sorted(result.get("list") or [], key=lambda x: int(x["timestamp"]))
        vals = [float(x["openInterest"]) for x in rows]
        if len(vals) >= 5:
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            return {"zscore": (vals[-1] - mean) / std if std else 0, "open_interest_btc": vals[-1], "source": "Bybit"}
    except Exception:
        pass
    row = _okx("/public/open-interest", {"instType": "SWAP", "instId": f"{currency}-USDT-SWAP"})[0]
    return {"zscore": None, "open_interest_btc": float(row["oiCcy"]), "source": "OKX"}


def _basis(currency="BTC"):
    symbol = f"{currency}USDT"
    try:
        r = requests.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", params={"symbol": symbol}, timeout=6, headers=BINANCE_HEADERS)
        r.raise_for_status()
        x = r.json()
        mark, idx = float(x["markPrice"]), float(x["indexPrice"])
        return (mark - idx) / idx * 100, "Binance"
    except Exception:
        mark = float(_okx("/public/mark-price", {"instType": "SWAP", "instId": f"{currency}-USDT-SWAP"})[0]["markPx"])
        idx = float(_okx("/market/index-tickers", {"instId": f"{currency}-USDT"})[0]["idxPx"])
        return (mark - idx) / idx * 100, "OKX"


def get_analysis_data(currency="BTC"):
    data = {"fear_greed": None, "max_pain": None, "gex_musd": None, "iv_rank_pct": None, "current_iv": None, "funding": None, "positioning": None, "oi_zscore": None, "open_interest_btc": None, "open_interest_source": None, "spot_perp_basis_pct": None, "basis_source": None, "binance_status": _binance_probe()}
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=15)
        r.raise_for_status()
        row = r.json()["data"][0]
        data["fear_greed"] = {"value": int(row["value"]), "label": row["value_classification"]}
    except Exception:
        pass
    try:
        expiries = _chain(currency)
        spot = get_index_price(currency)
        expiry = min(expiries)
        chain = expiries[expiry]
        strikes = sorted(set(s for s, _, _, _ in chain))
        pains = {}
        for test in strikes:
            total = 0
            for strike, is_call, oi, _ in chain:
                if is_call and test > strike:
                    total += (test - strike) * oi
                elif not is_call and test < strike:
                    total += (strike - test) * oi
            pains[test] = total
        mp = min(pains, key=pains.get)
        calls = sum(oi for _, c, oi, _ in chain if c)
        puts = sum(oi for _, c, oi, _ in chain if not c)
        data["max_pain"] = {"strike": mp, "spot": spot, "expiry": expiry.isoformat(), "days_left": max(0, (expiry - datetime.now(timezone.utc)).days), "put_call_ratio": puts / calls if calls else 0}
    except Exception:
        pass
    try:
        summary = get_book_summary(currency)
        spot = get_index_price(currency)
        now = datetime.now(timezone.utc)
        gex = 0.0
        for x in summary:
            try:
                strike, is_call, expiry = parse_instrument_name(x["instrument_name"])
            except Exception:
                continue
            oi = x.get("open_interest", 0) or 0
            iv = x.get("mark_iv", 0) or 0
            t = (expiry - now).total_seconds() / (365 * 24 * 3600)
            if oi and iv and t > 0:
                gex += (1 if is_call else -1) * bs_gamma(spot, strike, t, iv / 100) * oi * (spot ** 2) * 0.01
        data["gex_musd"] = gex / 1e6
    except Exception:
        pass
    try:
        hist = get_historical_volatility(currency)
        vals = [v for _, v in hist]
        data["current_iv"] = vals[-1]
        data["iv_rank_pct"] = percentile_rank(vals, vals[-1])
    except Exception:
        pass
    try:
        data["funding"] = _funding_stats(currency)
    except Exception:
        pass
    try:
        data["positioning"] = _positioning(currency)
    except Exception:
        pass
    try:
        oi = _oi_metrics(currency)
        data["oi_zscore"] = oi["zscore"]
        data["open_interest_btc"] = oi["open_interest_btc"]
        data["open_interest_source"] = oi["source"]
    except Exception:
        pass
    try:
        data["spot_perp_basis_pct"], data["basis_source"] = _basis(currency)
    except Exception:
        pass
    return data


def build_report():
    d = get_analysis_data()
    mp = d.get("max_pain")
    return f"₿📐 *KRİPTO TÜREV*\nMax Pain: ${mp['strike']:,.0f}" if mp else "₿📐 *KRİPTO TÜREV*\n⚠️ Veri alınamadı"
