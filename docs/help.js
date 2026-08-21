function tip(text){const s=String(text??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');return `<span class="help-tip" tabindex="0" aria-label="${s}" data-tip="${s}">?</span>`}

(function(){
  if(!location.pathname.includes('crypto_derivatives.html')) return;

  const validNumber=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
  const moneyCompact=v=>{if(!validNumber(v))return'—';v=Number(v);const a=Math.abs(v),sign=v<0?'-':'';if(a>=1e9)return sign+'$'+(a/1e9).toFixed(2)+'B';if(a>=1e6)return sign+'$'+(a/1e6).toFixed(1)+'M';if(a>=1e3)return sign+'$'+(a/1e3).toFixed(1)+'K';return sign+'$'+a.toFixed(0)};
  const css=`
    .flow15-card{border-left:3px solid #f3ba2f}
    .flow15-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}
    .flow15-badge{font-size:9px;border:1px solid var(--green-dim);border-radius:999px;padding:4px 8px;color:var(--muted)}
    .flow15-grid{display:grid;grid-template-columns:1fr;gap:14px;margin-top:12px}
    .flow15-panel{border:1px solid var(--green-dim);border-radius:10px;padding:10px;overflow:hidden}
    .flow15-title{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
    .flow15-value{font-size:20px;font-weight:800;margin-bottom:8px}
    .flow15-canvas{width:100%;height:220px;display:block}
    .flow15-note{font-size:9px;line-height:1.55;color:var(--muted);margin-top:8px}
    .flow15-wait{height:220px;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);font-size:10px;border:1px dashed rgba(92,138,114,.25);border-radius:8px;padding:18px;box-sizing:border-box}
    @media(max-width:700px){.flow15-canvas,.flow15-wait{height:190px}}
  `;
  const style=document.createElement('style');style.textContent=css;document.head.appendChild(style);

  function fmtTime(v){try{return new Intl.DateTimeFormat('tr-TR',{timeZone:'Europe/Istanbul',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}catch(e){return''}}
  function lineChart(canvas, rows, key, valueFormatter, zeroLine=false){
    if(!canvas)return;const series=rows.filter(r=>validNumber(r[key]));if(series.length<2)return;
    const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1,W=Math.max(300,rect.width),H=Math.max(180,rect.height);
    canvas.width=W*dpr;canvas.height=H*dpr;const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,W,H);
    const pad={l:58,r:12,t:12,b:28},pw=W-pad.l-pad.r,ph=H-pad.t-pad.b,vals=series.map(r=>Number(r[key]));
    let min=Math.min(...vals),max=Math.max(...vals);if(zeroLine){min=Math.min(min,0);max=Math.max(max,0)}if(min===max){const b=Math.abs(min||1)*.01;min-=b;max+=b}else if(!zeroLine){const b=(max-min)*.12;min-=b;max+=b}
    const x=i=>pad.l+(series.length===1?pw/2:pw*i/(series.length-1)),y=v=>pad.t+ph*(1-(v-min)/(max-min));c.font='9px IBM Plex Mono, monospace';
    for(let i=0;i<=4;i++){const yy=pad.t+ph*i/4,val=max-(max-min)*i/4;c.strokeStyle='rgba(92,138,114,.14)';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke();c.fillStyle='#5c8a72';c.textAlign='right';c.fillText(valueFormatter(val),pad.l-6,yy+3)}
    if(zeroLine&&min<0&&max>0){const yy=y(0);c.strokeStyle='rgba(255,207,92,.35)';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke()}
    c.strokeStyle='#39ff88';c.lineWidth=2;c.beginPath();series.forEach((r,i)=>{const xx=x(i),yy=y(Number(r[key]));i?c.lineTo(xx,yy):c.moveTo(xx,yy)});c.stroke();
    c.fillStyle='#5c8a72';c.textAlign='center';[0,.25,.5,.75,1].forEach(q=>{const i=Math.min(series.length-1,Math.round((series.length-1)*q));c.fillText(fmtTime(series[i].ts),x(i),H-8)});
  }

  async function inject(){
    const content=document.getElementById('content');if(!content||document.getElementById('flow15Card'))return;
    let data;try{data=await(await fetch('../data/crypto_flow_history.json?t='+Date.now())).json()}catch(e){return}
    if(data.venue!=='Binance')return;
    const raw=(data.points||[]).slice(-96);if(!raw.length)return;
    let cum=0;const rows=raw.map(p=>{const d=validNumber(p.spot_cvd_delta_usd)?Number(p.spot_cvd_delta_usd):null;if(d!==null)cum+=d;return {...p,spot_cvd_cumulative_usd:d!==null?cum:null}});
    const spotSeries=rows.filter(r=>validNumber(r.spot_cvd_cumulative_usd)),oiSeries=rows.filter(r=>validNumber(r.binance_oi_usd));
    const lastSpot=spotSeries[spotSeries.length-1]||{},lastOi=oiSeries[oiSeries.length-1]||{};let oiChange=null;if(oiSeries.length>=2&&Number(oiSeries[0].binance_oi_usd)!==0)oiChange=(Number(lastOi.binance_oi_usd)/Number(oiSeries[0].binance_oi_usd)-1)*100;
    const spotCoverage=raw.filter(r=>r.spot_ok&&validNumber(r.spot_cvd_delta_usd)).length;
    const spotUnavailable=spotSeries.length===0&&raw.some(r=>r.spot_error);
    const lastErr=[...raw].reverse().find(r=>r.spot_error)?.spot_error||'';
    const card=document.createElement('div');card.id='flow15Card';card.className='card flow15-card';card.innerHTML=`
      <div class="flow15-head"><div><h2>Binance · 15dk Spot CVD + Perp OI</h2><div class="note">Son 24 saat · 96 × 15dk bucket</div></div><div class="flow15-badge">CVD ${spotSeries.length} · OI ${oiSeries.length} nokta</div></div>
      <div class="flow15-grid">
        <div class="flow15-panel"><div class="flow15-title">Binance Spot BTCUSDT CVD · Kümülatif USDT</div><div class="flow15-value">${moneyCompact(lastSpot.spot_cvd_cumulative_usd)}</div>${spotSeries.length>=2?'<canvas id="spotCvd15Canvas" class="flow15-canvas"></canvas>':`<div class="flow15-wait">${spotUnavailable?'Binance Spot API bu çalışma ortamından erişilemiyor. CVD için sahte/fallback veri çizilmiyor.':'Binance Spot CVD grafiği için en az 2 gerçek 15dk bucket bekleniyor.'}</div>`}<div class="flow15-note">Binance BTCUSDT spot aggTrades: agresif alış notionalı − agresif satış notionalı. Pozitif eğim spot alıcı baskısını, negatif eğim spot satıcı baskısını gösterir. Geçerli bucket: ${spotCoverage}/${rows.length}.${lastErr?` Son hata: ${lastErr}`:''}</div></div>
        <div class="flow15-panel"><div class="flow15-title">Binance BTC Perp OI · Coinalyze</div><div class="flow15-value">${moneyCompact(lastOi.binance_oi_usd)} ${oiChange==null?'':`<span style="font-size:11px;color:${oiChange>=0?'#39ff88':'#ff5c5c'}">${oiChange>=0?'+':''}${oiChange.toFixed(2)}%</span>`}</div>${oiSeries.length>=2?'<canvas id="oi15Canvas" class="flow15-canvas"></canvas>':'<div class="flow15-wait">Binance OI grafiği için en az 2 gerçek Coinalyze snapshot noktası bekleniyor.</div>'}<div class="flow15-note">Bu OI yalnızca Binance BTC perpetual verisidir ve Coinalyze üzerinden alınır. Spot CVD ile aynı zaman ekseninde izlenerek fiyat hareketinin spot talep mi yoksa kaldıraç birikimi mi olduğu değerlendirilir.</div></div>
      </div>`;
    content.insertBefore(card,content.firstChild);
    const draw=()=>{if(spotSeries.length>=2)lineChart(document.getElementById('spotCvd15Canvas'),rows,'spot_cvd_cumulative_usd',moneyCompact,true);if(oiSeries.length>=2)lineChart(document.getElementById('oi15Canvas'),rows,'binance_oi_usd',moneyCompact,false)};requestAnimationFrame(draw);window.addEventListener('resize',draw,{passive:true});
  }
  const obs=new MutationObserver(()=>{const c=document.getElementById('content');if(c&&c.children.length){inject();obs.disconnect()}});obs.observe(document.documentElement,{childList:true,subtree:true});if(document.readyState!=='loading')setTimeout(inject,300);else document.addEventListener('DOMContentLoaded',()=>setTimeout(inject,300));
})();
