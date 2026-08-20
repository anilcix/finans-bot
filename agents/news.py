"""AJAN 9: Piyasa haber akışı — son 72 saat.

Google News RSS ile güncel başlıkları toplar. Ulaşılabilen gerçek yayıncı
sayfalarında meta açıklama / ilk anlamlı paragraflardan kısa bağlam çıkarır.
Google News'in genel tanıtım metni gerçek haber bağlamı sayılmaz. Haber içeriği
engellenirse temiz başlık/RSS ile devam eder; içerik uydurmaz.
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

_GOOGLE_BOILERPLATE = (
    "comprehensive up-to-date news coverage",
    "aggregated from sources all over the world by google news",
    "google news",
)


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


def _usable_context(text, title=""):
    text = " ".join((text or "").split()).strip()
    if len(text) < 80:
        return False
    low = text.lower()
    if any(x in low for x in _GOOGLE_BOILERPLATE):
        return False
    # RSS bazen sadece başlık + kaynak döndürür; bunu makale bağlamı sayma.
    clean_title = " ".join((title or "").lower().split()).strip()
    if clean_title and low.startswith(clean_title[: min(60, len(clean_title))]):
        return False
    return True


def _fetch_article_context(link, title=""):
    """Yalnızca gerçek yayıncı içeriği görünüyorsa kısa bağlam döndürür."""
    try:
        r = requests.get(link, timeout=8, headers=UA, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return None
        # Google News yönlendirme sayfasında kaldıysak içerik sayma.
        final_host = requests.utils.urlparse(r.url).netloc.lower()
        if "news.google." in final_host or final_host.endswith("google.com"):
            return None
        parser = _ArticleParser()
        parser.feed(r.text[:1_500_000])
        bits = []
        if parser.description:
            bits.append(parser.description)
        bits.extend(parser.paragraphs[:2])
        text = " ".join(" ".join(bits).split())
        if not _usable_context(text, title):
            return None
        return {"text": text[:900], "final_url": r.url, "mode": "article_context"}
    except Exception:
        return None


def _rss_context(raw_desc, title, source):
    text = _clean_html(raw_desc)
    if not text:
        return None
    low = text.lower()
    if any(x in low for x in _GOOGLE_BOILERPLATE):
        return None
    # Google RSS açıklaması çoğu zaman yalnızca başlık+kaynak; özet olarak kabul etme.
    normalized_title = _clean_title(title, source).lower()
    stripped = low.replace((source or "").lower(), "").strip(" -|—")
    if normalized_title and normalized_title[:60] in stripped:
        return None
    return text[:500] if len(text) >= 80 else None


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
        raw_title = item.findtext("title", default="").strip()
        title = _clean_title(raw_title, source)
        link = item.findtext("link", default="").strip()
        rss_ctx = _rss_context(item.findtext("description", default=""), raw_title, source)
        published = _parse_pub_date(item.findtext("pubDate", default=""))
        if not title or published is None or published < cutoff:
            continue
        out.append({
            "title": title,
            "source": source,
            "link": link,
            "published_at": published.isoformat(),
            "context": rss_ctx,
            "context_mode": "rss_context" if rss_ctx else "title_only",
        })

    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:max_items]


def _enrich_topic(items):
    targets = [(i, x) for i, x in enumerate(items[:ARTICLE_READS_PER_TOPIC]) if x.get("link")]
    if not targets:
        return items
    with ThreadPoolExecutor(max_workers=min(ARTICLE_READS_PER_TOPIC, 2)) as pool:
        future_map = {pool.submit(_fetch_article_context, x["link"], x.get("title", "")): i for i, x in targets}
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
        "method": "Google News RSS başlıkları + yalnızca gerçek yayıncı sayfası erişilebildiğinde makale bağlamı; Google boilerplate ve başlık-kopyası açıklamalar özet sayılmaz.",
    }
