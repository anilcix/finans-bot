"""Rapor satırı oluşturma yardımcıları - her ajan bunları kullanır."""


def safe_line(label, fn, emoji="📊"):
    try:
        result = fn()
        if result is None:
            return f"⏭️ {label}: (bu göstergenin ücretsiz kaynağı yok)"
        return result
    except Exception:
        return f"⚠️ {label}: veri alınamadı"


def pct_line(label, value, emoji="📈"):
    return f"{emoji} {label}: %{value:+.2f}"


def val_line(label, value, suffix="", emoji="📊", decimals=2):
    return f"{emoji} {label}: {value:,.{decimals}f}{suffix}"


def price_change_line(label, price, change_pct, emoji_pos="🟢", emoji_neg="🔴", prefix="$", decimals=2):
    arrow = emoji_pos if (change_pct is not None and change_pct >= 0) else emoji_neg
    change_str = f"  ({change_pct:+.2f}%)" if change_pct is not None else ""
    return f"{arrow} {label}: {prefix}{price:,.{decimals}f}{change_str}"


def unavailable_note(items):
    return "⏭️ Ücretsiz kaynağı olmayan göstergeler: " + ", ".join(items)
