"""AJAN 9: Piyasa haber akışı — son 72 saat.

Google News RSS ile güncel başlıkları toplar. Ulaşılabilen haberlerde sayfanın meta
açıklaması / ilk anlamlı paragraflarından kısa bağlam çıkarır. Haber içeriği
engellenirse başlık + RSS açıklamasıyla devam eder; içerik uydurmaz.
"""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import requests
import xml.etree.ElementTree as ET

NEWS_TOPICS = [
    ("Federal Reserve Treasury yields inflation US economy", "Makro / Fed"),
    ("US Treasury buyback bond market liquidity long term yields", "Tahvil / Likidite"),
    ("high yield credit spreads corporate debt default US", "Kredi"),
    ("S&P 500 Nasdaq AI semiconductors earnings stock market", "Hisseler / AI"),
    ("Bitcoin Ethereum ETF crypto regulation market", "Kripto"),
    ("oil gold commodities geopolitics tariffs", "Emtia / Jeopolitik"),
]
MAX_HEADLINES_PER_TOPIC = 4
ARTICLE_READS_PER_TOPIC = 2
FETCH_LIMIT = 35
RECENCY_HOURS = 72
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0; +market-research)"}


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.description = ""
        self.paragraphs = []
        self._in_p = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        a = {str(k).lower(): (v or "") for k, v in attrs}
        if tag.lower() == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:description", "twitter:description", "description") and not self.description:
                self.description = a.get("content", "").strip()
        elif tag.lower() == "p":
            self._in_p = True
            self._parts = []

    def handle_data(self, data):
        if self._in_p:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "p" and self._in_p:
            text = " ".join("".join(self._parts).split())
            if len(text) >= 70 and len(self.paragraphs) < 3:
                self.paragraphs.append(text)
            self._in_p = False
            self._parts = []


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


def _clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _clean_title(title, source):
    title = " ".join((title or "").split())
    suffix = f" - {source}" if source else ""
    if suffix and title.lower().endswith(suffix.lower()):
        title = title[:-len(suffix)].strip()
    return title


def _fetch_article_context(link):
    """Ulaşılabilen sayfadan kısa bağlam alır; tam makale saklamaz."""
    try:
        r = requests.get(link, timeout=8, headers=UA, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return None
        parser = _ArticleParser()
        parser.feed(r.text[:1_500_000])
        bits = []
        if parser.description:
            bits.append(parser.description)
        bits.extend(parser.paragraphs[:2])
        text = " ".join(" ".join(bits).split())
        if len(text) < 80:
            return None
        return {"text": text[:900], "final_url": r.url, "mode": "article_context"}
    except Exception:
        return None


def _fetch_topic_headlines(query, max_items=MAX_HEADLINES_PER_TOPIC):
    r = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
        timeout=15,
        headers=UA,
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENCY_HOURS)
    out = []

    for item in root.findall(".//item")[:FETCH_LIMIT]:
        source = item.findtext("source", default="").strip()
        title = _clean_title(item.findtext("title", default="").strip(), source)
        link = item.findtext("link", default="").strip()
        rss_desc = _clean_html(item.findtext("description", default=""))
        published = _parse_pub_date(item.findtext("pubDate", default=""))
        if not title or published is None or published < cutoff:
            continue
        out.append({
            "title": title,
            "source": source,
            "link": link,
            "published_at": published.isoformat(),
            "context": rss_desc[:500] if rss_desc else None,
            "context_mode": "rss" if rss_desc else "title_only",
        })

    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:max_items]


def _enrich_topic(items):
    """En yeni iki haberi paralel olarak okuyup kısa bağlam ekler."""
    targets = [(i, x) for i, x in enumerate(items[:ARTICLE_READS_PER_TOPIC]) if x.get("link")]
    if not targets:
        return items
    with ThreadPoolExecutor(max_workers=min(ARTICLE_READS_PER_TOPIC, 2)) as pool:
        future_map = {pool.submit(_fetch_article_context, x["link"]): i for i, x in targets}
        for fut in as_completed(future_map):
            i = future_map[fut]
            try:
                ctx = fut.result()
            except Exception:
                ctx = None
            if ctx:
                items[i]["context"] = ctx["text"]
                items[i]["context_mode"] = ctx["mode"]
                items[i]["resolved_url"] = ctx["final_url"]
    return items


def build_report():
    lines = ["📰 *PİYASA HABER AKIŞI — SON 72 SAAT*"]
    for query, label in NEWS_TOPICS:
        lines.append(f"\n_{label}_")
        try:
            items = _enrich_topic(_fetch_topic_headlines(query))
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
            items = _enrich_topic(_fetch_topic_headlines(query))
            topics.append({"label": label, "query": query, "items": items})
        except Exception as e:
            topics.append({"label": label, "query": query, "items": [], "error": str(e)})

    read_count = sum(
        1 for t in topics for x in t.get("items", [])
        if x.get("context_mode") == "article_context"
    )
    headline_count = sum(len(t.get("items", [])) for t in topics)
    return {
        "topics": topics,
        "recency_hours": RECENCY_HOURS,
        "headline_count": headline_count,
        "article_context_count": read_count,
        "method": "Google News RSS + erişilebilen sayfalarda meta açıklama/ilk paragraf bağlamı; engellenen içerikte başlık/RSS ile fallback.",
    }
