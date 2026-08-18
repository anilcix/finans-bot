"""AJAN 9: Google News RSS başlık takibi."""
import requests,xml.etree.ElementTree as ET
NEWS_TOPICS=[("Federal Reserve faiz kararı","Fed"),("Bitcoin ETF","Kripto"),("stock market today","Piyasalar")]; MAX_HEADLINES_PER_TOPIC=3

def _fetch_topic_headlines(query,max_items=MAX_HEADLINES_PER_TOPIC):
    r=requests.get("https://news.google.com/rss/search",params={"q":query,"hl":"en-US","gl":"US","ceid":"US:en"},timeout=15,headers={"User-Agent":"Mozilla/5.0"}); r.raise_for_status(); root=ET.fromstring(r.content); out=[]
    for item in root.findall(".//item")[:max_items]:
        title=item.findtext("title",default="").strip(); link=item.findtext("link",default="").strip(); source=item.findtext("source",default="").strip()
        if title:out.append((title,source,link))
    return out

def build_report():
    lines=["📰 *HABER BAŞLIKLARI*"]
    for q,l in NEWS_TOPICS:
        lines.append(f"\n_{l}_")
        try: lines += [f"• {t} ({s})" for t,s,_ in _fetch_topic_headlines(q)]
        except Exception as e: lines.append(f"⚠️ Haberler alınamadı: {e}")
    return "\n".join(lines)

def get_analysis_data():
    topics=[]
    for q,l in NEWS_TOPICS:
        try:items=[{"title":t,"source":s,"link":u} for t,s,u in _fetch_topic_headlines(q)]
        except Exception:items=[]
        topics.append({"label":l,"query":q,"items":items})
    return {"topics":topics}
