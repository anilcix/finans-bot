"""GitHub Pages için tüm uzman ajanları, Treasury buyback verisini ve Harmanlayıcıyı üretir."""
import json,os
from datetime import datetime,timezone
from agents import macro,credit,crypto,crypto_derivatives,options,equities,hidden_pressure,screener,news,harmonizer
from common.treasury_buyback import fetch_treasury_buybacks

OUTPUT_DIR=os.path.join(os.path.dirname(__file__),"docs","data")
AGENTS={"macro":macro,"credit":credit,"crypto":crypto,"crypto_derivatives":crypto_derivatives,"options":options,"equities":equities,"hidden_pressure":hidden_pressure,"screener":screener,"news":news}


def _write(name,data):
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(os.path.join(OUTPUT_DIR,name+".json"),"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)


def main():
    now=datetime.now(timezone.utc).isoformat(); payloads={}
    for name,module in AGENTS.items():
        try:data=module.get_analysis_data(); data["generated_at"]=now
        except Exception as e:data={"generated_at":now,"error":str(e)}
        payloads[name]=data; _write(name,data); print("Yazıldı:",name)

    try: buyback=fetch_treasury_buybacks()
    except Exception as e: buyback={"generated_at":now,"error":str(e),"schedule":[],"recent_results":[]}
    _write("treasury_buybacks",buyback); print("Yazıldı: treasury_buybacks")

    try:
        center=harmonizer.synthesize(payloads,buyback); center["generated_at"]=now
    except Exception as e:
        center={"generated_at":now,"error":str(e)}
    _write("harmonizer",center); print("Yazıldı: harmonizer")

if __name__=="__main__":main()
