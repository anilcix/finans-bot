"""İstatistiksel yardımcılar: yüzdelik dilim ve kompozit skor."""


def percentile_rank(historical_values, current_value):
    if not historical_values: raise ValueError("Tarihsel veri yok")
    return sum(1 for v in historical_values if v <= current_value) / len(historical_values) * 100


def risk_score(percentile, invert):
    return (100 - percentile) if invert else percentile


def score_label(score):
    if score >= 80: return "Güçlü Risk-On", "🟢"
    if score >= 60: return "Kırılgan Risk-On", "🟢"
    if score >= 40: return "Nötr / Karışık", "🟡"
    if score >= 20: return "Kırılgan / Savunmacı", "🟠"
    return "Risk-Off", "🔴"


def composite_score(components):
    total_weight=sum(w for _,w,_ in components)
    if total_weight==0: raise ValueError("Toplam ağırlık sıfır")
    return sum(risk_score(pct,inv)*w for pct,w,inv in components)/total_weight


def barometer_bar(label, value, percentile, unit="%", invert=False, width=20):
    filled=int(round(percentile/100*width)); bar="█"*filled+"░"*(width-filled)
    _,emoji=score_label(risk_score(percentile,invert))
    return f"{emoji} {label}: {value:+.2f}{unit}  [{bar}] %{percentile:.0f}"
