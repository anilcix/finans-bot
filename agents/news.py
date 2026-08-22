"""AJAN 9: Güvenilir ve okunabilir piyasa haber akışı.

Politika:
- Bitcoin: Reuters + CoinDesk.
- Makro: Federal Reserve, U.S. Treasury, BLS, BEA + Reuters.
- Bir haber yalnız gerçek yayıncı sayfası açılıp içerik çıkarılabildiyse Harmanlayıcıya girer.
- Şant Manukyan: yalnız resmî İş Yatırım YouTube kanalındaki Şant Manukyan yayınları;
  transcript/caption okunabiliyorsa özetlenir.
- Trump / Elon Musk / Michael Saylor: yalnız X API erişimi varsa kendi resmî/public
  hesaplarından finans/kripto ile ilgili postlar alınır. X API yoksa izleniyor gibi davranılmaz.
"""
import html
import os
import re
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
    gnewsdecoder = None
try:
    from youtube_transcript_api import YouTubeTranscriptApi
except Exception:
    YouTubeTranscriptApi = None

UA={"User-Agent":"Mozilla/5.0 (compatible; finans-bot/1.0; +market-research)","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
RECENCY_HOURS=72
MAX_ITEMS_PER_TOPIC=5
FETCH_LIMIT=30
_TRANSLATE_CACHE={}

TRUSTED_TOPICS=[
    {
        "label":"Bitcoin",
        "query":"(Bitcoin OR BTC) (site:reuters.com OR site:coindesk.com)",
        "allowed_domains":("reuters.com","coindesk.com"),
    },
    {
        "label":"Makro / Fed / Hazine",
        "query":"(Federal Reserve OR inflation OR CPI OR payrolls OR jobs OR GDP OR Treasury yields OR Treasury buyback) (site:reuters.com OR site:federalreserve.gov OR site:bls.gov OR site:bea.gov OR site:home.treasury.gov)",
        "allowed_domains":("reuters.com","federalreserve.gov","bls.gov","bea.gov","home.treasury.gov","treasury.gov"),
    },
]
SOURCE_POLICY={
    "Bitcoin":["Reuters","CoinDesk"],
    "Makro":["Federal Reserve","U.S. Treasury","BLS","BEA","Reuters"],
    "Şant Manukyan":["İş Yatırım resmî YouTube kanalı + okunabilir transcript"],
    "X":["@realDonaldTrump","@elonmusk","@saylor — yalnız X API erişimi varsa"],
}
IS_YATIRIM_CHANNEL_ID="UCIju0kyYHAqQePXdGFjhLdA"
X_USERS=("realDonaldTrump","elonmusk","saylor")
FINANCE_TERMS=("bitcoin","btc","crypto","cryptocurrency","market","markets","finance","financial","dollar","usd","inflation","treasury","bond","bonds","rate","rates","stock","stocks","economy","economic")
BAD_TEXT=("sign up for","subscribe","newsletter","cookie","privacy policy","terms of use","advertisement","all rights reserved")
GOOGLE_BAD=("comprehensive up-to-date news coverage","aggregated from sources all over the world by google news")


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.description="";self.paragraphs=[];self.links=[];self.canonical="";self._in_p=False;self._parts=[]
    def handle_starttag(self,tag,attrs):
        a={str(k).lower():(v or "") for k,v in attrs};t=tag.lower()
        if t=="meta":
            key=(a.get("property") or a.get("name") or "").lower()
            if key in ("og:description","twitter:description","description") and not self.description:self.description=a.get("content","").strip()
        elif t=="link" and "canonical" in (a.get("rel") or "").lower():self.canonical=a.get("href","").strip()
        elif t=="a" and a.get("href"):self.links.append(a["href"].strip())
        elif t=="p":self._in_p=True;self._parts=[]
    def handle_data(self,data):
        if self._in_p:self._parts.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="p" and self._in_p:
            text=" ".join("".join(self._parts).split())
            if len(text)>=70 and not any(x in text.lower() for x in BAD_TEXT) and len(self.paragraphs)<10:self.paragraphs.append(text)
            self._in_p=False;self._parts=[]


def _translate_tr(text):
    text=" ".join((text or "").split()).strip()
    if not text:return None
    if text in _TRANSLATE_CACHE:return _TRANSLATE_CACHE[text]
    try:
        r=requests.get("https://translate.googleapis.com/translate_a/single",params={"client":"gtx","sl":"auto","tl":"tr","dt":"t","q":text},headers=UA,timeout=12);r.raise_for_status();d=r.json();out="".join(x[0] for x in (d[0] or []) if x and x[0]).strip()
        if out:_TRANSLATE_CACHE[text]=out;return out
    except Exception:pass
    _TRANSLATE_CACHE[text]=None;return None


def _parse_date(text):
    if not text:return None
    try:
        dt=parsedate_to_datetime(text)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        try:return datetime.fromisoformat(text.replace("Z","+00:00")).astimezone(timezone.utc)
        except Exception:return None


def _is_google(host):
    host=(host or "").lower();return host.endswith("google.com") or ".google." in host or host.startswith("news.google.")


def _resolve_google_url(link):
    if not link:return None
    if not _is_google(urlparse(link).netloc):return link
    if gnewsdecoder is not None:
        try:
            d=gnewsdecoder(link)
            u=d.get("decoded_url") if isinstance(d,dict) and d.get("status") else None
            if u and not _is_google(urlparse(u).netloc):return u
        except Exception:pass
    try:
        r=requests.get(link,headers=UA,timeout=10,allow_redirects=True);r.raise_for_status()
        if not _is_google(urlparse(r.url).netloc):return r.url
        p=ArticleParser();p.feed(r.text[:1_500_000])
        for href in ([p.canonical] if p.canonical else [])+p.links:
            u=urljoin(r.url,href);host=urlparse(u).netloc
            if u.startswith("http") and host and not _is_google(host):return u
    except Exception:pass
    return None


def _domain_allowed(url,allowed):
    host=urlparse(url).netloc.lower().split(":")[0]
    return any(host==d or host.endswith("."+d) for d in allowed)


def _summary_from_text(description,paragraphs,title):
    text=[]
    if description and len(description)>=80 and not any(x in description.lower() for x in GOOGLE_BAD+BAD_TEXT):text.append(description)
    text.extend(paragraphs[:5])
    joined=" ".join(text);sentences=[s.strip() for s in re.split(r"(?<=[.!?])\s+",joined) if len(s.strip())>=45]
    if not sentences:return None,None
    picked=[];seen=set()
    for s in sentences:
        key=re.sub(r"\W+","",s.lower())[:120]
        if key in seen or any(x in s.lower() for x in BAD_TEXT):continue
        seen.add(key);picked.append(s)
        if len(picked)>=3:break
    if not picked:return None,None
    short=" ".join(picked[:2])[:900].rstrip();full=" ".join(picked+sentences[3:8])[:2400].rstrip()
    return short,full


def _read_publisher(google_link,title,allowed_domains):
    u=_resolve_google_url(google_link)
    if not u or not _domain_allowed(u,allowed_domains):return None
    try:
        r=requests.get(u,headers=UA,timeout=12,allow_redirects=True);r.raise_for_status()
        if not _domain_allowed(r.url,allowed_domains) or "html" not in (r.headers.get("content-type") or "").lower():return None
        p=ArticleParser();p.feed(r.text[:2_000_000]);short,full=_summary_from_text(" ".join(p.description.split()),p.paragraphs,title)
        if not short:return None
        short_tr=_translate_tr(short);full_tr=_translate_tr(full)
        if not short_tr:return None
        return {"summary":short_tr,"context":full_tr or short_tr,"summary_original":short,"context_original":full,"resolved_url":r.url}
    except Exception:return None


def _google_topic(spec):
    r=requests.get("https://news.google.com/rss/search",params={"q":spec["query"],"hl":"en-US","gl":"US","ceid":"US:en"},headers=UA,timeout=15);r.raise_for_status();root=ET.fromstring(r.content)
    cutoff=datetime.now(timezone.utc)-timedelta(hours=RECENCY_HOURS);raw=[]
    for item in root.findall(".//item")[:FETCH_LIMIT]:
        pub=_parse_date(item.findtext("pubDate",default=""));title=" ".join((item.findtext("title",default="") or "").split());source=(item.findtext("source",default="") or "").strip();link=(item.findtext("link",default="") or "").strip()
        if title and link and pub and pub>=cutoff:raw.append((title,source,link,pub))
    out=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(_read_publisher,link,title,spec["allowed_domains"]):(title,source,link,pub) for title,source,link,pub in raw[:12]}
        for fut in as_completed(futures):
            title,source,link,pub=futures[fut]
            try:ctx=fut.result()
            except Exception:ctx=None
            if not ctx:continue
            out.append({"title":title,"source":source,"link":ctx["resolved_url"],"resolved_url":ctx["resolved_url"],"published_at":pub.isoformat(),"article_summary":ctx["summary"],"article_context":ctx["context"],"article_summary_original":ctx["summary_original"],"article_context_original":ctx["context_original"],"context":ctx["summary"],"context_mode":"publisher_article","translation_ok":True,"trusted":True})
    out.sort(key=lambda x:x["published_at"],reverse=True);return out[:MAX_ITEMS_PER_TOPIC]


def _youtube_text(video_id):
    if YouTubeTranscriptApi is None:return None
    try:
        transcript=YouTubeTranscriptApi().fetch(video_id,languages=["tr","en"])
        text=" ".join(getattr(x,"text","") for x in transcript if getattr(x,"text",None));text=" ".join(text.split())
        return text[:12000] if len(text)>=180 else None
    except Exception:return None


def _shant_topic():
    url=f"https://www.youtube.com/feeds/videos.xml?channel_id={IS_YATIRIM_CHANNEL_ID}";r=requests.get(url,headers=UA,timeout=15);r.raise_for_status();root=ET.fromstring(r.content)
    ns={"a":"http://www.w3.org/2005/Atom","yt":"http://www.youtube.com/xml/schemas/2015"};cutoff=datetime.now(timezone.utc)-timedelta(days=14);out=[]
    for e in root.findall("a:entry",ns):
        title=(e.findtext("a:title",default="",namespaces=ns) or "").strip();low=title.lower()
        if "şant manukyan" not in low and "sant manukyan" not in low:continue
        pub=_parse_date(e.findtext("a:published",default="",namespaces=ns));vid=e.findtext("yt:videoId",default="",namespaces=ns)
        if not pub or pub<cutoff or not vid:continue
        transcript=_youtube_text(vid)
        if not transcript:continue
        # Transcript primary-source commentary; extract first coherent chunk then translate only if needed.
        sentences=[s.strip() for s in re.split(r"(?<=[.!?])\s+",transcript) if len(s.strip())>=35]
        short=" ".join(sentences[:5])[:1100] if sentences else transcript[:1100];full=" ".join(sentences[:18])[:3500] if sentences else transcript[:3500]
        out.append({"title":title,"source":"İş Yatırım · Şant Manukyan","link":f"https://www.youtube.com/watch?v={vid}","resolved_url":f"https://www.youtube.com/watch?v={vid}","published_at":pub.isoformat(),"article_summary":short,"article_context":full,"context":short,"context_mode":"official_video_transcript","translation_ok":True,"trusted":True,"primary_source":True})
    out.sort(key=lambda x:x["published_at"],reverse=True);return out[:3]


def _x_get(path,token):
    headers={"Authorization":f"Bearer {token}","User-Agent":UA["User-Agent"]}
    for base in ("https://api.x.com/2","https://api.twitter.com/2"):
        try:
            r=requests.get(base+path,headers=headers,timeout=12)
            if r.status_code==200:return r.json()
        except Exception:pass
    return None


def _x_topic():
    token=(os.getenv("X_BEARER_TOKEN") or "").strip();out=[]
    if not token:return out,{"configured":False,"status":"X_BEARER_TOKEN yok; gerçek zamanlı X izleme yapılmıyor."}
    cutoff=datetime.now(timezone.utc)-timedelta(hours=RECENCY_HOURS)
    for username in X_USERS:
        u=_x_get(f"/users/by/username/{username}",token);uid=((u or {}).get("data") or {}).get("id")
        if not uid:continue
        t=_x_get(f"/users/{uid}/tweets?max_results=10&exclude=retweets,replies&tweet.fields=created_at,text",token)
        for row in (t or {}).get("data") or []:
            text=" ".join((row.get("text") or "").split());low=text.lower();pub=_parse_date(row.get("created_at"))
            if not text or not pub or pub<cutoff or not any(k in low for k in FINANCE_TERMS):continue
            tr=_translate_tr(text) or text
            out.append({"title":f"@{username}: {tr[:150]}"+("…" if len(tr)>150 else ""),"source":f"X · @{username}","link":f"https://x.com/{username}/status/{row.get('id')}","resolved_url":f"https://x.com/{username}/status/{row.get('id')}","published_at":pub.isoformat(),"article_summary":tr,"article_context":tr,"context":tr,"context_mode":"x_api_post","translation_ok":True,"trusted":True,"primary_source":True})
    out.sort(key=lambda x:x["published_at"],reverse=True);return out[:8],{"configured":True,"status":"X API aktif","accounts":list(X_USERS)}


def get_analysis_data():
    topics=[];errors=[]
    for spec in TRUSTED_TOPICS:
        try:items=_google_topic(spec)
        except Exception as e:items=[];errors.append(f"{spec['label']}: {e}")
        topics.append({"label":spec["label"],"query":spec["query"],"items":items,"source_policy":"trusted_domain + publisher_article required"})
    try:
        shant=_shant_topic();topics.append({"label":"Şant Manukyan","query":"İş Yatırım resmî YouTube","items":shant,"source_policy":"official channel + transcript required"})
    except Exception as e:errors.append(f"Şant Manukyan: {e}")
    x_items,x_status=_x_topic()
    if x_items:topics.append({"label":"X / Piyasa Kişileri","query":"Trump + Elon Musk + Michael Saylor","items":x_items,"source_policy":"official public account via X API"})
    items=[x for t in topics for x in t.get("items",[])];read=sum(1 for x in items if x.get("context_mode") in ("publisher_article","official_video_transcript","x_api_post"))
    return {"topics":topics,"recency_hours":RECENCY_HOURS,"headline_count":len(items),"article_context_count":read,"translated_count":sum(1 for x in items if x.get("translation_ok")),"language":"tr","trusted_only":True,"source_policy":SOURCE_POLICY,"x_watch":x_status,"errors":errors,"method":"Trusted-source whitelist. Haber yalnız yayıncı sayfası okunabildiyse; Şant yalnız resmî İş Yatırım transcript'i okunabildiyse; X yalnız resmî API üzerinden eklenir."}


def build_report():
    d=get_analysis_data();lines=["📰 *GÜVENİLİR PİYASA HABER AKIŞI*"]
    for t in d.get("topics",[]):
        lines.append(f"\n_{t.get('label')}_")
        lines.extend(f"• {x['title']} ({x['source']})" for x in t.get("items",[]))
    if not d.get("x_watch",{}).get("configured"):lines.append("\nℹ️ X API key yok; Trump/Musk/Saylor gerçek zamanlı izlenmiyor.")
    return "\n".join(lines)
