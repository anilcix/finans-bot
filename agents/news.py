"""AJAN 9: Güvenilir ve okunabilir piyasa haber akışı.

Kaynak politikası:
- Bitcoin: CoinDesk doğrudan RSS + Reuters güvenilir keşif.
- Makro: Federal Reserve, BLS, BEA doğrudan resmi feed + Reuters güvenilir keşif.
- Doğrudan güvenilir feed yeterli açıklama sağlıyorsa içerik kabul edilir; yayıncı sayfası
  ayrıca okunabiliyorsa daha geniş bağlam alınır.
- Şant Manukyan: yalnız İş Yatırım resmi YouTube + okunabilir transcript.
- Trump / Elon Musk / Michael Saylor: yalnız X API token varsa resmi hesaplardan.
"""
import html, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import requests
import xml.etree.ElementTree as ET

try:
    from googlenewsdecoder import gnewsdecoder
except Exception:
    gnewsdecoder=None
try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:
    YouTubeTranscriptApi=None

UA={"User-Agent":"Mozilla/5.0 (compatible; finans-bot/1.0; +market-research)","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
RECENCY_HOURS=96
MAX_ITEMS_PER_TOPIC=6
_TRANSLATE_CACHE={}
BAD=("sign up for","subscribe","newsletter","cookie","privacy policy","terms of use","advertisement","all rights reserved")
GOOGLE_BAD=("comprehensive up-to-date news coverage","aggregated from sources all over the world by google news")
IS_YATIRIM_CHANNEL_ID="UCIju0kyYHAqQePXdGFjhLdA"
X_USERS=("realDonaldTrump","elonmusk","saylor")
FINANCE_TERMS=("bitcoin","btc","crypto","market","finance","financial","dollar","inflation","treasury","bond","rate","stock","economy")

DIRECT_FEEDS={
    "Bitcoin":[
        {"source":"CoinDesk","url":"https://www.coindesk.com/arc/outboundfeeds/rss/","domain":"coindesk.com","keywords":("bitcoin","btc","crypto","ether","ethereum","etf")},
    ],
    "Makro / Fed / Hazine":[
        {"source":"Federal Reserve","url":"https://www.federalreserve.gov/feeds/press_all.xml","domain":"federalreserve.gov","keywords":("fomc","monetary","rate","inflation","economy","economic","financial","bank")},
        {"source":"BLS","url":"https://www.bls.gov/feed/bls_latest.rss","domain":"bls.gov","keywords":("consumer price","cpi","employment","payroll","jobs","unemployment","ppi","producer price")},
        {"source":"BEA","url":"https://apps.bea.gov/rss/rss.xml","domain":"bea.gov","keywords":("gdp","personal income","pce","economic","gross domestic")},
    ],
}
GOOGLE_TRUSTED=[
    {"label":"Bitcoin","query":"Bitcoin Reuters OR CoinDesk","allowed":("reuters.com","coindesk.com")},
    {"label":"Makro / Fed / Hazine","query":"Federal Reserve inflation Treasury yields Reuters","allowed":("reuters.com","federalreserve.gov","bls.gov","bea.gov","home.treasury.gov")},
]
SOURCE_POLICY={
    "Bitcoin":["CoinDesk RSS","Reuters"],
    "Makro":["Federal Reserve","BLS","BEA","Reuters"],
    "Şant Manukyan":["İş Yatırım resmi YouTube + transcript"],
    "X":["@realDonaldTrump","@elonmusk","@saylor — yalnız X API ile"],
}

class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.description="";self.paragraphs=[];self.links=[];self.canonical="";self._in_p=False;self._parts=[]
    def handle_starttag(self,tag,attrs):
        a={str(k).lower():(v or "") for k,v in attrs};t=tag.lower()
        if t=="meta":
            k=(a.get("property") or a.get("name") or "").lower()
            if k in ("og:description","twitter:description","description") and not self.description:self.description=a.get("content","").strip()
        elif t=="link" and "canonical" in (a.get("rel") or "").lower():self.canonical=a.get("href","").strip()
        elif t=="a" and a.get("href"):self.links.append(a["href"].strip())
        elif t=="p":self._in_p=True;self._parts=[]
    def handle_data(self,data):
        if self._in_p:self._parts.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="p" and self._in_p:
            text=" ".join("".join(self._parts).split())
            if len(text)>=70 and not any(x in text.lower() for x in BAD) and len(self.paragraphs)<10:self.paragraphs.append(text)
            self._in_p=False;self._parts=[]

def _clean(s):return " ".join(re.sub(r"<[^>]+>"," ",html.unescape(s or "")).split())
def _parse_date(s):
    if not s:return None
    try:
        d=parsedate_to_datetime(s);return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:
        try:return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
        except Exception:return None

def _translate_tr(text):
    text=" ".join((text or "").split()).strip()
    if not text:return None
    if text in _TRANSLATE_CACHE:return _TRANSLATE_CACHE[text]
    try:
        r=requests.get("https://translate.googleapis.com/translate_a/single",params={"client":"gtx","sl":"auto","tl":"tr","dt":"t","q":text},headers=UA,timeout=12);r.raise_for_status();d=r.json();out="".join(x[0] for x in d[0] if x and x[0]).strip();_TRANSLATE_CACHE[text]=out or None;return out or None
    except Exception:_TRANSLATE_CACHE[text]=None;return None

def _summary(text):
    text=_clean(text)
    if len(text)<70 or any(x in text.lower() for x in GOOGLE_BAD):return None,None
    ss=[x.strip() for x in re.split(r"(?<=[.!?])\s+",text) if len(x.strip())>=40 and not any(b in x.lower() for b in BAD)]
    if not ss:return None,None
    short=" ".join(ss[:2])[:900];full=" ".join(ss[:8])[:2600];return short,full

def _domain_ok(url,allowed):
    h=urlparse(url).netloc.lower().split(":")[0];return any(h==d or h.endswith("."+d) for d in allowed)

def _read_url(url,allowed):
    if not url or not _domain_ok(url,allowed):return None
    try:
        r=requests.get(url,headers=UA,timeout=12,allow_redirects=True);r.raise_for_status()
        if not _domain_ok(r.url,allowed):return None
        p=ArticleParser();p.feed(r.text[:2_000_000]);short,full=_summary(" ".join(([p.description] if p.description else [])+p.paragraphs[:6]))
        if not short:return None
        return {"summary":_translate_tr(short) or short,"context":_translate_tr(full) or full,"resolved_url":r.url,"mode":"publisher_article"}
    except Exception:return None

def _trusted_feed(feed,label):
    out=[];cutoff=datetime.now(timezone.utc)-timedelta(hours=RECENCY_HOURS)
    try:
        r=requests.get(feed["url"],headers=UA,timeout=15);r.raise_for_status();root=ET.fromstring(r.content)
    except Exception:return out
    entries=root.findall(".//item")
    if not entries:
        ns={"a":"http://www.w3.org/2005/Atom"};entries=root.findall("a:entry",ns)
    for e in entries[:30]:
        title=_clean(e.findtext("title",default="") or e.findtext("{http://www.w3.org/2005/Atom}title",default=""))
        link=e.findtext("link",default="") or ""
        if not link:
            le=e.find("{http://www.w3.org/2005/Atom}link");link=(le.get("href") if le is not None else "") or ""
        pub=_parse_date(e.findtext("pubDate",default="") or e.findtext("published",default="") or e.findtext("{http://www.w3.org/2005/Atom}published",default="") or e.findtext("{http://www.w3.org/2005/Atom}updated",default=""))
        desc=_clean(e.findtext("description",default="") or e.findtext("summary",default="") or e.findtext("{http://www.w3.org/2005/Atom}summary",default="") or e.findtext("{http://purl.org/rss/1.0/modules/content/}encoded",default=""))
        if not title or not pub or pub<cutoff or not link:continue
        low=(title+" "+desc).lower()
        if feed.get("keywords") and not any(k in low for k in feed["keywords"]):continue
        article=_read_url(link,(feed["domain"],))
        if article:
            summary,context,mode=article["summary"],article["context"],article["mode"];link=article["resolved_url"]
        else:
            short,full=_summary(desc)
            if not short:continue
            summary=_translate_tr(short) or short;context=_translate_tr(full) or full;mode="trusted_feed_text"
        out.append({"title":title,"source":feed["source"],"link":link,"resolved_url":link,"published_at":pub.isoformat(),"article_summary":summary,"article_context":context,"context":summary,"context_mode":mode,"translation_ok":True,"trusted":True,"primary_source":feed["source"]!="CoinDesk"})
    return out

def _resolve_google(link):
    if not link:return None
    if "news.google." not in urlparse(link).netloc:return link
    if gnewsdecoder:
        try:
            d=gnewsdecoder(link);u=d.get("decoded_url") if isinstance(d,dict) and d.get("status") else None
            if u:return u
        except Exception:pass
    return None

def _google_trusted(spec):
    out=[];cutoff=datetime.now(timezone.utc)-timedelta(hours=RECENCY_HOURS)
    try:
        r=requests.get("https://news.google.com/rss/search",params={"q":spec["query"],"hl":"en-US","gl":"US","ceid":"US:en"},headers=UA,timeout=15);r.raise_for_status();root=ET.fromstring(r.content)
    except Exception:return out
    for e in root.findall(".//item")[:20]:
        title=_clean(e.findtext("title",default=""));pub=_parse_date(e.findtext("pubDate",default=""));link=_resolve_google(e.findtext("link",default=""))
        if not title or not pub or pub<cutoff or not link or not _domain_ok(link,spec["allowed"]):continue
        article=_read_url(link,spec["allowed"])
        if not article:continue
        source=(e.findtext("source",default="") or urlparse(link).netloc).strip()
        out.append({"title":title,"source":source,"link":article["resolved_url"],"resolved_url":article["resolved_url"],"published_at":pub.isoformat(),"article_summary":article["summary"],"article_context":article["context"],"context":article["summary"],"context_mode":"publisher_article","translation_ok":True,"trusted":True})
    return out

def _dedupe(items):
    seen=set();out=[]
    for x in sorted(items,key=lambda z:z.get("published_at","") ,reverse=True):
        k=re.sub(r"\W+","",x.get("title","").lower())[:100]
        if k in seen:continue
        seen.add(k);out.append(x)
    return out[:MAX_ITEMS_PER_TOPIC]

def _youtube_text(video_id):
    if YouTubeTranscriptApi is None:return None
    try:
        t=YouTubeTranscriptApi().fetch(video_id,languages=["tr","en"]);text=" ".join(getattr(x,"text","") for x in t if getattr(x,"text",None));return " ".join(text.split())[:12000] if len(text)>=180 else None
    except Exception:return None

def _shant_topic():
    out=[];url=f"https://www.youtube.com/feeds/videos.xml?channel_id={IS_YATIRIM_CHANNEL_ID}";cutoff=datetime.now(timezone.utc)-timedelta(days=21)
    try:r=requests.get(url,headers=UA,timeout=15);r.raise_for_status();root=ET.fromstring(r.content)
    except Exception:return out
    ns={"a":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"}
    for e in root.findall("a:entry",ns):
        title=(e.findtext("a:title",default="",namespaces=ns) or "").strip();pub=_parse_date(e.findtext("a:published",default="",namespaces=ns));vid=e.findtext("yt:videoId",default="",namespaces=ns)
        if ("şant manukyan" not in title.lower() and "sant manukyan" not in title.lower()) or not pub or pub<cutoff or not vid:continue
        text=_youtube_text(vid)
        if not text:continue
        short,full=_summary(text)
        if not short:continue
        out.append({"title":title,"source":"İş Yatırım · Şant Manukyan","link":f"https://www.youtube.com/watch?v={vid}","resolved_url":f"https://www.youtube.com/watch?v={vid}","published_at":pub.isoformat(),"article_summary":short,"article_context":full,"context":short,"context_mode":"official_video_transcript","translation_ok":True,"trusted":True,"primary_source":True})
    return out[:3]
def _x_get(path,token):
    for base in ("https://api.x.com/2","https://api.twitter.com/2"):
        try:
            r=requests.get(base+path,headers={"Authorization":f"Bearer {token}","User-Agent":UA["User-Agent"]},timeout=12)
            if r.status_code==200:return r.json()
        except Exception:pass
    return None

def _x_topic():
    token=(os.getenv("X_BEARER_TOKEN") or "").strip();out=[]
    if not token:return out,{"configured":False,"status":"X_BEARER_TOKEN yok; Trump/Musk/Saylor gerçek zamanlı izlenmiyor."}
    cutoff=datetime.now(timezone.utc)-timedelta(hours=RECENCY_HOURS)
    for username in X_USERS:
        u=_x_get(f"/users/by/username/{username}",token);uid=((u or {}).get("data") or {}).get("id")
        if not uid:continue
        d=_x_get(f"/users/{uid}/tweets?max_results=10&exclude=retweets,replies&tweet.fields=created_at,text",token)
        for row in (d or {}).get("data") or []:
            text=_clean(row.get("text"));pub=_parse_date(row.get("created_at"))
            if not text or not pub or pub<cutoff or not any(k in text.lower() for k in FINANCE_TERMS):continue
            tr=_translate_tr(text) or text;link=f"https://x.com/{username}/status/{row.get('id')}"
            out.append({"title":f"@{username}: {tr[:150]}","source":f"X · @{username}","link":link,"resolved_url":link,"published_at":pub.isoformat(),"article_summary":tr,"article_context":tr,"context":tr,"context_mode":"x_api_post","translation_ok":True,"trusted":True,"primary_source":True})
    return _dedupe(out),{"configured":True,"status":"X API aktif","accounts":list(X_USERS)}

def get_analysis_data():
    topics=[];errors=[]
    for label,feeds in DIRECT_FEEDS.items():
        items=[]
        for feed in feeds:
            try:items.extend(_trusted_feed(feed,label))
            except Exception as e:errors.append(f"{feed['source']}: {e}")
        spec=next((s for s in GOOGLE_TRUSTED if s["label"]==label),None)
        if spec:
            try:items.extend(_google_trusted(spec))
            except Exception as e:errors.append(f"{label} Google trusted: {e}")
        topics.append({"label":label,"items":_dedupe(items),"source_policy":"trusted first-party feed + readable trusted publisher"})
    shant=_shant_topic();topics.append({"label":"Şant Manukyan","items":shant,"source_policy":"official channel + transcript required"})
    x_items,x_status=_x_topic()
    if x_items:topics.append({"label":"X / Piyasa Kişileri","items":x_items,"source_policy":"official public account via X API"})
    all_items=[x for t in topics for x in t.get("items",[])]
    return {"topics":topics,"recency_hours":RECENCY_HOURS,"headline_count":len(all_items),"article_context_count":sum(1 for x in all_items if x.get("context_mode") in ("publisher_article","trusted_feed_text","official_video_transcript","x_api_post")),"translated_count":sum(1 for x in all_items if x.get("translation_ok")),"language":"tr","trusted_only":True,"source_policy":SOURCE_POLICY,"x_watch":x_status,"errors":errors,"method":"Trusted first-party feeds are primary. Publisher page is preferred; when blocked, only the trusted source's own RSS/press description may be summarized. Google News is trusted-domain discovery fallback only."}

def build_report():
    d=get_analysis_data();lines=["📰 *GÜVENİLİR PİYASA HABER AKIŞI*"]
    for t in d["topics"]:
        lines.append(f"\n_{t['label']}_");lines.extend(f"• {x['title']} ({x['source']})" for x in t.get("items",[]))
    if not d.get("x_watch",{}).get("configured"):lines.append("\nℹ️ X API key yok; Trump/Musk/Saylor gerçek zamanlı izlenmiyor.")
    return "\n".join(lines)
