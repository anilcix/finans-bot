"""AJAN 9: Google News RSS başlık takibi — son 72 saat."""
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

NEWS_TOPICS = [
    ("Federal Reserve faiz kararı", "Fed"),
    ("Bitcoin ETF", "Kripto"),
    ("stock market today", "Piyasalar"),
]
MAX_HEADLINES_PER_TOPIC = 5
FETCH_LIMIT = 30
RECENCY_HOURS = 72


def _parse_pub_date(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _fetch_topic_headlines(query, max_items=MAX_HEADLINES_PER_TOPIC):
    r = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENCY_HOURS)
    out = []

    for item in root.findall(".//item")[:FETCH_LIMIT]:
        title = item.findtext("title", default="").strip()
        link = item.findtext("link", default="").strip()
        source = item.findtext("source", default="").strip()
        published = _parse_pub_date(item.findtext("pubDate", default=""))

        if not title or published is None or published < cutoff:
            continue

        out.append(
            {
                "title": title,
                "source": source,
                "link": link,
                "published_at": published.isoformat(),
            }
        )

    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:max_items]


def build_report():
    lines = ["📰 *HABER BAŞLIKLARI — SON 72 SAAT*"]
    for query, label in NEWS_TOPICS:
        lines.append(f"\n_{label}_")
        try:
            items = _fetch_topic_headlines(query)
            if items:
                lines += [f"• {x['title']} ({x['source']})" for x in items]
            else:
                lines.append("• Son 72 saatte uygun başlık yok.")
        except Exception as e:
            lines.append(f"⚠️ Haberler alınamadı: {e}")
    return "\n".join(lines)


def get_analysis_data():
    topics = []
    for query, label in NEWS_TOPICS:
        try:
            items = _fetch_topic_headlines(query)
        except Exception as e:
            items = []
            topics.append(
                {"label": label, "query": query, "items": items, "error": str(e)}
            )
            continue
        topics.append({"label": label, "query": query, "items": items})

    return {"topics": topics, "recency_hours": RECENCY_HOURS}
