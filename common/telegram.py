import os
import requests

TELEGRAM_BOT_TOKEN=os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID=os.environ.get("TELEGRAM_CHAT_ID")
MAX_LEN=3800


def _split_message(text,max_len=MAX_LEN):
    if len(text)<=max_len: return [text]
    chunks=[]; current=""
    for line in text.split("\n"):
        if len(current)+len(line)+1>max_len:
            chunks.append(current); current=line
        else: current=f"{current}\n{line}" if current else line
    if current: chunks.append(current)
    return chunks


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID ayarlanmamış")
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks=_split_message(text)
    for i,chunk in enumerate(chunks):
        r=requests.post(url,data={"chat_id":TELEGRAM_CHAT_ID,"text":chunk,"parse_mode":"Markdown"},timeout=15)
        if r.status_code!=200: raise RuntimeError(f"Telegram API hatası: {r.status_code}")
    print(f"Rapor başarıyla gönderildi ({len(chunks)} parça).")
