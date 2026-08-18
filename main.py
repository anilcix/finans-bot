"""Tüm ajanları sırayla çalıştırıp Telegram'a gönderen orkestratör."""
from datetime import datetime
from agents import macro,credit,crypto,crypto_derivatives,options,equities,hidden_pressure,news,screener
from common.telegram import send_telegram_message
AGENTS=[("Makro",macro),("Kredi",credit),("Kripto",crypto),("Kripto Türev",crypto_derivatives),("Opsiyon",options),("Hisseler/Emtia",equities),("Gizli Baskı",hidden_pressure),("Tarayıcı",screener),("Haberler",news)]

def run_all_agents():
    sections=[f"📊 *PİYASA RAPORU* — {datetime.now().strftime('%d.%m.%Y %H:%M')}"]
    for name,module in AGENTS:
        try:sections.append(module.build_report())
        except Exception as e:sections.append(f"⚠️ *{name}*: {e}")
    return "\n\n".join(sections)
if __name__=="__main__":send_telegram_message(run_all_agents())
