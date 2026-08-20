"""AJAN 9: Piyasa haber akışı — son 72 saat.

Google News RSS ile güncel başlıkları toplar. Google News yönlendirme sayfasından
mümkünse gerçek yayıncı URL'sini çözer, yayıncı sayfasındaki meta açıklama ve
ilk anlamlı paragrafları okur. Kısa özet yorum içermez; daha uzun bağlam ayrı
alan olarak tutulur. Yayıncı sayfası erişilemiyorsa bunu açıkça işaretler ve
başlığı 'özet' diye tekrar etmez.
"""
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
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
ARTICLE_READS_PER_TOPIC = 3
FETCH_LIMIT = 35
RECENCY_HOURS = 72
UA = {"User-Agent": "Mozilla/5.0 (compatible; finans-bot/1.0; +market-research)"}

_GOOGLE_BOILERPLATE = (
    "comprehensive up-to-date news coverage",
    "aggregated from sources all over the world by google news",
    "google news",
)
_BAD_PARAGRAPH_PHRASES = (
    "sign up for", "subscribe", "newsletter", "cookie", "privacy policy",
    "terms of use", "advertisement", "all rights reserved", "read more",
)


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.description = ""
        self.paragraphs = []
        self.links = []
        self.canonical = ""
        self._in_p = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        a = {str(k).lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("og:description", "twitter:description", "description") and not self.description:
                self.description = a.get("content", "").strip()
        elif t == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href", "").strip()
        elif t == "a":
            href = a.get("href", "").strip()
            if href:
                self.links.append(href)
        elif t == "p":
            self._in_p = True
            self._parts = []

    def handle_data(self, data):
        if self._in_p:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "p" and self._in_p:
            text = " ".join("".join(self._parts).split())
            if _meaningful_paragraph(text) and len(self.paragraphs) < 8:
                self.paragraphs.append(text)
            self._in_p = False
            self._parts = []


def _meaningful_paragraph(text):
    text = " ".join((text or "").split()).strip()
    if len(text) < 70:
        return False
    low = text.lower()
    if any(x in low for x in _BAD_PARAGRAPH_PHRASES):
        return False
    return True


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


def _is_google_host(host):
    host = (host or "").lower()
    return host.endswith("google.com") or ".google." in host or host.startswith("news.google.")


def _external_http_links(parser, base_url):
    out = []
    seen = set()
    for href in ([parser.canonical] if parser.canonical else []) + parser.links:
        try:
            u = urljoin(base_url, href)
            p = urlparse(u)
            if p.scheme not in ("http", "https") or not p.netloc or _is_google_host(p.netloc):
                continue
            if u not in seen:
                seen.add(u)
                out.append(u)
        except Exception:
            continue
    return out


def _resolve_publisher_url(google_link):
    """Google News sayfasındaki dış bağlantılardan gerçek yayıncı URL'sini bulmaya çalışır."""
    try:
        r = requests.get(google_link, timeout=10, headers=UA, allow_redirects=True)
        r.raise_for_status()
        final_host = urlparse(r.url).netloc.lower()
        if not _is_google_host(final_host):
            return r.url
        parser = _ArticleParser()
        parser.feed(r.text[:1_500_000])
        links = _external_http_links(parser, r.url)
        # Google sayfasındaki ilk gerçek dış haber bağlantısı çoğunlukla yayıncıdır.
        for u in links:
            low = u.lower()
            if not any(x in low for x in ("support.google", "accounts.google", "policies.google")):
                return u
    except Exception:
        return None
    return None


def _usable_context(text, title=""):
    text = " ".join((text or "").split()).strip()
    if len(text) < 80:
        return False
    low = text.lower()
    if any(x in low for x in _GOOGLE_BOILERPLATE):
        return False
    clean_title = " ".join((title or "").lower().split()).strip()
    if clean_title and low == clean_title:
        return False
    return True


def _sentence_candidates(text):
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?])\s+", clean)
    out = []
    seen = set()
    for s in parts:
        s = s.strip()
        if len(s) < 40:
            continue
        key = re.sub(r"\W+", "", s.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _extractive_summary(description, paragraphs, title):
    """Yorum katmadan metinden 2-3 anlamlı cümle seçer."""
    candidates = []
    if description and _usable_context(description, title):
        candidates.extend(_sentence_candidates(description))
    for p in paragraphs[:5]:
        candidates.extend(_sentence_candidates(p))
    picked = []
    title_words = {w for w in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(w) > 3}
    for s in candidates:
        low = s.lower()
        if any(x in low for x in _BAD_PARAGRAPH_PHRASES):
            continue
        words = set(re.findall(r"[a-z0-9]+", low))
        # Başlıkla alakalı veya ilk güçlü cümle olsun; reklam/menü cümlesi seçilmesin.
        if not picked or len(title_words & words) >= 1:
            picked.append(s)
        if len(picked) >= 3:
            break
    if not picked:
        return None
    text = " ".join(picked)
    return text[:850].rstrip()


def _fetch_article_context(link, title=""):
    """Google News URL'sini yayıncıya çözüp gerçek içerikten kısa + geniş özet üretir."""
    publisher_url = _resolve_publisher_url(link) or link
    try:
        r = requests.get(publisher_url, timeout=10, headers=UA, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return None
        final_host = urlparse(r.url).netloc.lower()
        if _is_google_host(final_host):
            return None
        parser = _ArticleParser()
        parser.feed(r.text[:2_000_000])
        desc = " ".join((parser.description or "").split()).strip()
        paras = [p for p in parser.paragraphs if _usable_context(p, title)]
        summary = _extractive_summary(desc, paras, title)
        full_context = " ".join(([desc] if _usable_context(desc, title) else []) + paras[:5])
        full_context = " ".join(full_context.split())
        if not summary or len(summary) < 80:
            return None
        return {
            "summary": summary,
            "text": full_context[:2200] if full_context else summary,
            "final_url": r.url,
            "mode": "publisher_article",
        }
    except Exception:
        return None


def _rss_context(raw_desc, title, source):
    text = _clean_html(raw_desc)
    if not text:
        return None
    low = text.lower()
    if any(x in low for x in _GOOGLE_BOILERPLATE):
        return None
    normalized_title = _clean_title(title, source).lower()
    stripped = low.replace((source or "").lower(), "").strip(" -|—")
    if normalized_title and normalized_title[:60] in stripped:
        return None
    return text[:800] if len(text) >= 80 else None


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
            "article_summary": rss_ctx,
            "article_context": rss_ctx,
            "context": rss_ctx,
            "context_mode": "rss_context" if rss_ctx else "title_only",
        })

    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out[:max_items]


def _enrich_topic(items):
    targets = [(i, x) for i, x in enumerate(items[:ARTICLE_READS_PER_TOPIC]) if x.get("link")]
    if not targets:
        return items
    with ThreadPoolExecutor(max_workers=min(ARTICLE_READS_PER_TOPIC, 3)) as pool:
        future_map = {pool.submit(_fetch_article_context, x["link"], x.get("title", "")): i for i, x in targets}
        for fut in as_completed(future_map):
            i = future_map[fut]
            try:
                ctx = fut.result()
            except Exception:
                ctx = None
            if ctx:
                items[i]["article_summary"] = ctx["summary"]
                items[i]["article_context"] = ctx["text"]
                items[i]["context"] = ctx["summary"]
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
        if x.get("context_mode") == "publisher_article"
    )
    headline_count = sum(len(t.get("items", [])) for t in topics)
    return {
        "topics": topics,
        "recency_hours": RECENCY_HOURS,
        "headline_count": headline_count,
        "article_context_count": read_count,
        "method": "Google News RSS -> gerçek yayıncı URL çözümleme -> yayıncı meta/ilk paragraflardan yorumsuz extractive özet; erişilemeyen haberde başlık özet diye tekrar edilmez.",
    }
