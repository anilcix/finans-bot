"""AJAN 2: KREDİ — FRED kredi spreadleri ve tüketici/banka stresi."""
from common.fred import latest_value, fetch_fred_history
from common.report import safe_line, val_line, unavailable_note


def _line_history(series_id, limit=520):
    try:
        dates, vals = fetch_fred_history(series_id, limit=limit)
        pts = [{"date": d, "value": v} for d, v in zip(dates, vals)]
        return list(reversed(pts))
    except Exception:
        return []


def _trend(series_id, lag_short=21, lag_long=63):
    try:
        _, vals = fetch_fred_history(series_id, limit=max(lag_long + 5, 80))
        out = {"change_1m": None, "change_3m": None}
        if len(vals) > lag_short:
            out["change_1m"] = vals[0] - vals[lag_short]
        if len(vals) > lag_long:
            out["change_3m"] = vals[0] - vals[lag_long]
        return out
    except Exception:
        return {"change_1m": None, "change_3m": None}


def _hy_oas():
    _, val = latest_value("BAMLH0A0HYM2")
    return val_line("HY OAS (Yüksek Getirili Kredi Spreadi)", val, suffix="%", emoji="🏦", decimals=2)


def _ig_oas():
    _, val = latest_value("BAMLC0A0CM")
    return val_line("IG OAS (Yatırım Yapılabilir Kredi Spreadi)", val, suffix="%", emoji="🏦", decimals=2)


def _ccc_oas():
    _, val = latest_value("BAMLH0A3HYC")
    return val_line("CCC OAS (En Riskli Kredi Spreadi)", val, suffix="%", emoji="🏦", decimals=2)


def _sloos():
    _, val = latest_value("DRTSCLCC")
    trend = "sıkılaştırıyor" if val > 0 else "gevşetiyor"
    return f"🏦 SLOOS — Kredi Kartı Standartları: %{val:+.1f} net ({trend})"


def _delinquency():
    _, val = latest_value("DRCCLACBS")
    return val_line("Kredi Kartı Temerrüt Oranı", val, suffix="%", emoji="💳", decimals=2)


def _charge_off():
    _, val = latest_value("CORCACBS")
    return val_line("Kredi Kartı Charge-Off Oranı", val, suffix="%", emoji="💳", decimals=2)


def build_report():
    lines = ["💳 *KREDİ PİYASALARI*"]
    lines.append(safe_line("HY OAS", _hy_oas))
    lines.append(safe_line("IG OAS", _ig_oas))
    lines.append(safe_line("CCC OAS", _ccc_oas))
    lines.append(safe_line("SLOOS", _sloos))
    lines.append(safe_line("Delinquency Rate", _delinquency))
    lines.append(safe_line("Charge-Off Rate", _charge_off))
    lines.append("")
    lines.append(unavailable_note(["CDS spreadleri (Bloomberg/Markit ücretli)"]))
    return "\n".join(lines)


def get_analysis_data():
    def one(series_id):
        try:
            date, value = latest_value(series_id)
            return {"date": date, "value": value}
        except Exception:
            return None

    return {
        "hy_oas": one("BAMLH0A0HYM2"),
        "ig_oas": one("BAMLC0A0CM"),
        "ccc_oas": one("BAMLH0A3HYC"),
        "sloos": one("DRTSCLCC"),
        "delinquency": one("DRCCLACBS"),
        "charge_off": one("CORCACBS"),
        "spread_trends": {
            "hy": _trend("BAMLH0A0HYM2"),
            "ig": _trend("BAMLC0A0CM"),
            "ccc": _trend("BAMLH0A3HYC"),
        },
        "history": {
            "hy": _line_history("BAMLH0A0HYM2"),
            "ig": _line_history("BAMLC0A0CM"),
            "ccc": _line_history("BAMLH0A3HYC"),
            "sloos_credit_card": _line_history("DRTSCLCC", 60),
        },
        "sloos_definition": "Net Percentage of Domestic Banks Tightening Standards for Credit Card Loans",
        "unavailable": ["CDS spreadleri (Bloomberg/Markit ücretli)"],
    }
