"""
AJAN 2: KREDİ
--------------
Kaynak: FRED API (ücretsiz, key gerekir)

NOT: CDS (Credit Default Swap) spreadleri için ücretsiz/gerçek zamanlı bir
kaynak yok (Bloomberg/Markit ücretli) - atlanmıştır.
"""

from common.fred import latest_value, mom_change
from common.report import safe_line, val_line, pct_line, unavailable_note


def _hy_oas():
    date, val = latest_value("BAMLH0A0HYM2")
    return val_line("HY OAS (Yüksek Getirili Kredi Spreadi)", val, suffix="%", emoji="🏦", decimals=2)


def _ig_oas():
    date, val = latest_value("BAMLC0A0CM")
    return val_line("IG OAS (Yatırım Yapılabilir Kredi Spreadi)", val, suffix="%", emoji="🏦", decimals=2)


def _ccc_oas():
    date, val = latest_value("BAMLH0A3HYC")
    return val_line("CCC OAS (En Riskli Kredi Spreadi)", val, suffix="%", emoji="🏦", decimals=2)


def _sloos():
    date, val = latest_value("DRTSCLCC")
    trend = "sıkılaştırıyor" if val > 0 else "gevşetiyor"
    return f"🏦 SLOOS (Bankaların Kredi Sıkılaştırması): %{val:+.1f} net ({trend})"


def _delinquency():
    date, val = latest_value("DRCCLACBS")
    return val_line("Kredi Kartı Temerrüt Oranı", val, suffix="%", emoji="💳", decimals=2)


def _charge_off():
    date, val = latest_value("CORCACBS")
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
    return {"hy_oas":one("BAMLH0A0HYM2"),"ig_oas":one("BAMLC0A0CM"),"ccc_oas":one("BAMLH0A3HYC"),"sloos":one("DRTSCLCC"),"delinquency":one("DRCCLACBS"),"charge_off":one("CORCACBS"),"unavailable":["CDS spreadleri (Bloomberg/Markit ücretli)"]}
