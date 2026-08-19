"""ABD Hazine buyback verisini resmi Treasury kaynaklarından toplar.

Amaç: tentative schedule + erişilebilen operasyon XML'lerini yapılandırmak.
Veri bulunamazsa hata bilgisini döndürür; veri uydurmaz.
"""
from datetime import datetime, timezone
import re
import xml.etree.ElementTree as ET

import requests

UA={"User-Agent":"Mozilla/5.0 (compatible; finans-bot/1.0; +https://github.com/anilcix/finans-bot)"}
BUYBACK_PAGE="https://www.treasurydirect.gov/auctions/announcements-data-results/buy-backs/"
QUARTERLY_BASE="https://home.treasury.gov/system/files/221"


def _quarter(dt=None):
    dt=dt or datetime.now(timezone.utc)
    return (dt.month-1)//3+1, dt.year


def _schedule_url(dt=None):
    q,y=_quarter(dt)
    return f"{QUARTERLY_BASE}/Tentative-Buyback-ScheduleQ{q}{y}.xml"


def _tag(x):
    return x.split('}')[-1].strip()


def _flatten(el):
    out={}
    for c in el.iter():
        if c is el: continue
        if len(list(c))==0 and c.text and c.text.strip():
            out[_tag(c.tag)]=c.text.strip()
    return out


def _pick(row, words):
    for k,v in row.items():
        key=re.sub(r'[^a-z0-9]','',k.lower())
        if all(w in key for w in words): return v
    return None


def _money_number(x):
    if not x: return None
    s=str(x).replace('$','').replace(',','').strip()
    m=re.search(r'-?\d+(?:\.\d+)?',s)
    if not m: return None
    v=float(m.group())
    low=str(x).lower()
    if 'billion' in low or re.search(r'\bbn\b',low): v*=1_000_000_000
    elif 'million' in low or re.search(r'\bmm\b',low): v*=1_000_000
    return v


def _parse_schedule(xml_text):
    root=ET.fromstring(xml_text)
    candidates=[]
    for el in root.iter():
        row=_flatten(el)
        if len(row)<2: continue
        joined=' '.join(row.keys()).lower()
        if 'date' not in joined: continue
        if not any(x in joined for x in ('maturity','bucket','maximum','max','amount','operation')): continue
        date=_pick(row,['date'])
        bucket=_pick(row,['maturity','bucket']) or _pick(row,['bucket'])
        max_raw=_pick(row,['max','amount']) or _pick(row,['maximum']) or _pick(row,['amount'])
        op_type=_pick(row,['operation','type']) or _pick(row,['type'])
        security=_pick(row,['security','type'])
        if not date or not (bucket or max_raw): continue
        candidates.append({
            "operation_date":date,
            "operation_type":op_type,
            "security_type":security,
            "maturity_bucket":bucket,
            "max_amount_raw":max_raw,
            "max_amount":_money_number(max_raw),
        })
    # Nested XML elemanlarından gelen tekrarları kaldır.
    seen=set(); out=[]
    for r in candidates:
        key=(r.get('operation_date'),r.get('maturity_bucket'),r.get('max_amount_raw'),r.get('operation_type'))
        if key in seen: continue
        seen.add(key); out.append(r)
    return out


def _extract_xml_links(html):
    hrefs=re.findall(r'href=["\']([^"\']+\.xml(?:\?[^"\']*)?)["\']',html,re.I)
    out=[]
    for h in hrefs:
        if h.startswith('//'): h='https:'+h
        elif h.startswith('/'): h='https://www.treasurydirect.gov'+h
        elif not h.startswith('http'): h=BUYBACK_PAGE.rstrip('/')+'/'+h.lstrip('/')
        if h not in out: out.append(h)
    return out


def _result_summary(xml_text, url):
    try: root=ET.fromstring(xml_text)
    except Exception: return None
    flat=_flatten(root)
    date=_pick(flat,['operation','date']) or _pick(flat,['date'])
    accepted=_pick(flat,['total','par','accepted']) or _pick(flat,['par','accepted'])
    offered=_pick(flat,['total','par','offered']) or _pick(flat,['par','offered'])
    max_amt=_pick(flat,['max','par']) or _pick(flat,['max','amount'])
    bucket=_pick(flat,['maturity','bucket'])
    op_type=_pick(flat,['operation','type'])
    if not any((date,accepted,offered,bucket)): return None
    return {
        "operation_date":date,"operation_type":op_type,"maturity_bucket":bucket,
        "total_par_accepted_raw":accepted,"total_par_offered_raw":offered,"max_amount_raw":max_amt,
        "total_par_accepted":_money_number(accepted),"total_par_offered":_money_number(offered),"max_amount":_money_number(max_amt),
        "source_url":url,
    }


def fetch_treasury_buybacks():
    now=datetime.now(timezone.utc)
    out={
        "source":"U.S. Treasury / TreasuryDirect",
        "source_page":BUYBACK_PAGE,
        "tentative_schedule_url":_schedule_url(now),
        "schedule":[],"recent_results":[],"special_announcements":[],"errors":[],
        "note":"Tentative schedule planlamadır; preliminary/final announcement ve sonuçlar operasyon günü önceliklidir. Treasury buyback, Fed QE ile aynı mekanizma değildir.",
    }
    # Tentative quarterly schedule.
    try:
        r=requests.get(out["tentative_schedule_url"],headers=UA,timeout=20); r.raise_for_status()
        out["schedule"]=_parse_schedule(r.text)
        if not out["schedule"]: out["errors"].append("Tentative schedule XML indirildi fakat alanlar otomatik normalize edilemedi.")
    except Exception as e:
        out["errors"].append(f"Tentative schedule alınamadı: {e}")

    # TreasuryDirect sayfasında sunucu tarafında görünür XML linkleri varsa en yeni operasyonları yakala.
    try:
        p=requests.get(BUYBACK_PAGE,headers=UA,timeout=20); p.raise_for_status()
        links=_extract_xml_links(p.text)
        # schedule/schema linklerini dışarıda tut; sonuç/announcement XML'lerine odaklan.
        links=[u for u in links if 'schedule' not in u.lower() and 'schema' not in u.lower()]
        for u in links[-24:]:
            try:
                x=requests.get(u,headers=UA,timeout=12); x.raise_for_status()
                item=_result_summary(x.text,u)
                if item: out["recent_results"].append(item)
            except Exception: pass
        if not links:
            out["errors"].append("TreasuryDirect operasyon tablosu istemci tarafında yükleniyor; doğrudan sonuç XML linki HTML içinde bulunamadı.")
    except Exception as e:
        out["errors"].append(f"TreasuryDirect buyback sayfası alınamadı: {e}")

    out["schedule_count"]=len(out["schedule"])
    out["result_count"]=len(out["recent_results"])
    out["generated_at"]=now.isoformat()
    return out
