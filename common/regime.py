"""Rejim sınıflandırma kuralları."""


def credit_cycle_phase(hy_now, hy_200dma, hy_6m_change):
    low_level = hy_now < hy_200dma
    improving = hy_6m_change < 0
    if low_level and improving:
        return "Expansion (Boğa)", "🟢", "Spreadler düşük ve düşmeye devam ediyor - hisseler için en olumlu evre"
    if low_level and not improving:
        return "Late Cycle (Dikkat)", "🟡", "Spreadler hâlâ düşük ama yükselmeye başladı - erken uyarı"
    if not low_level and improving:
        return "Recovery (Toparlanma)", "🔵", "Spreadler yüksek ama düşüyor - krizden çıkış sinyali"
    return "Contraction (Kriz)", "🔴", "Spreadler yüksek ve yükselmeye devam ediyor - risk-off evre"


def yield_curve_regime(spread_now, spread_3m_ago):
    inverted = spread_now < 0
    steepening = spread_now > spread_3m_ago
    if inverted and steepening:
        return "Ters Dönmüş - Toparlanıyor", "🟠", "Eğri hâlâ ters ama düzelmeye başladı"
    if inverted and not steepening:
        return "Ters Dönmüş - Derinleşiyor", "🔴", "Klasik resesyon sinyali derinleşiyor"
    if not inverted and steepening:
        return "Normal - Dikleşiyor", "🟢", "Sağlıklı büyüme beklentisi"
    return "Normal - Düzleşiyor", "🟡", "Büyüme beklentisi yavaşlıyor olabilir"


def hy_spread_warning(hy_oas_bps):
    if hy_oas_bps >= 600: return "🔴 KRİZ"
    if hy_oas_bps >= 400: return "🟠 UYARI"
    return "🟢 Güvenli"


def sloos_warning(sloos_pct):
    if sloos_pct >= 20: return "🔴 KRİZ"
    if sloos_pct >= 10: return "🟠 UYARI"
    return "🟢 Güvenli"


def ccc_hy_divergence_warning(ccc_percentile, hy_percentile):
    diff = ccc_percentile - hy_percentile
    if diff >= 50: status = "🔴 KRİZ"
    elif diff >= 30: status = "🟠 UYARI"
    else: status = "🟢 Güvenli"
    return diff, status
