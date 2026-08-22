function tip(text){const s=String(text??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');return `<span class="help-tip" tabindex="0" aria-label="${s}" data-tip="${s}">?</span>`}

(function(){
  if(!location.pathname.includes('crypto_derivatives.html')) return;

  const validNumber=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
  const moneyCompact=v=>{if(!validNumber(v))return'—';v=Number(v);const a=Math.abs(v),sign=v<0?'-':'';if(a>=1e9)return sign+'$'+(a/1e9).toFixed(2)+'B';if(a>=1e6)return sign+'$'+(a/1e6).toFixed(1)+'M';if(a>=1e3)return sign+'$'+(a/1e3).toFixed(1)+'K';return sign+'$'+a.toFixed(0)};
  const btcFmt=v=>{if(!validNumber(v))return'—';v=Number(v);const a=Math.abs(v),sign=v<0?'-':'';return sign+(a>=1000?(a/1000).toFixed(2)+'K':a>=100?a.toFixed(0):a>=10?a.toFixed(1):a.toFixed(2))+' BTC'};
  const fundingFmt=v=>!validNumber(v)?'—':(Number(v)>=0?'+':'')+Number(v).toFixed(4)+'%';
  const css=`
    .flow15-card{border-left:3px solid #f3ba2f}.flow15-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}.flow15-badge{font-size:9px;border:1px solid var(--green-dim);border-radius:999px;padding:4px 8px;color:var(--muted)}.flow15-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}.flow15-panel{border:1px solid var(--green-dim);border-radius:10px;padding:10px;overflow:hidden}.flow15-title{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}.flow15-value{font-size:20px;font-weight:800;margin-bottom:8px}.flow15-canvas{width:100%;height:220px;display:block}.flow15-note{font-size:9px;line-height:1.55;color:var(--muted);margin-top:8px}.flow15-wait{height:220px;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);font-size:10px;border:1px dashed rgba(92,138,114,.25);border-radius:8px;padding:18px;box-sizing:border-box}@media(max-width:900px){.flow15-grid{grid-template-columns:1fr}}@media(max-width:700px){.flow15-canvas,.flow15-wait{height:190px}}
  `;
  const style=document.createElement('style');style.textContent=css;document.head.appendChild(style);
  function fmtTime(v){try{return new Intl.DateTimeFormat('tr-TR',{timeZone:'Europe/Istanbul',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}catch(e){return''}}
  function lineChart(canvas, rows, key, valueFormatter, zeroLine=false){
    if(!canvas)return;const series=rows.filter(r=>validNumber(r[key]));if(series.length<2)return;
    const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1,W=Math.max(300,rect.width),H=Math.max(180,rect.height);canvas.width=W*dpr;canvas.height=H*dpr;const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,W,H);
    const pad={l:64,r:12,t:12,b:28},pw=W-pad.l-pad.r,ph=H-pad.t-pad.b,vals=series.map(r=>Number(r[key]));let min=Math.min(...vals),max=Math.max(...vals);if(zeroLine){min=Math.min(min,0);max=Math.max(max,0)}if(min===max){const b=Math.abs(min||1)*.01;min-=b;max+=b}else if(!zeroLine){const b=(max-min)*.12;min-=b;max+=b}
    const x=i=>pad.l+(series.length===1?pw/2:pw*i/(series.length-1)),y=v=>pad.t+ph*(1-(v-min)/(max-min));c.font='9px IBM Plex Mono, monospace';for(let i=0;i<=4;i++){const yy=pad.t+ph*i/4,val=max-(max-min)*i/4;c.strokeStyle='rgba(92,138,114,.14)';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke();c.fillStyle='#5c8a72';c.textAlign='right';c.fillText(valueFormatter(val),pad.l-6,yy+3)}if(zeroLine&&min<0&&max>0){const yy=y(0);c.strokeStyle='rgba(255,207,92,.35)';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke()}c.strokeStyle='#39ff88';c.lineWidth=2;c.beginPath();series.forEach((r,i)=>{const xx=x(i),yy=y(Number(r[key]));i?c.lineTo(xx,yy):c.moveTo(xx,yy)});c.stroke();c.fillStyle='#5c8a72';c.textAlign='center';[0,.25,.5,.75,1].forEach(q=>{const i=Math.min(series.length-1,Math.round((series.length-1)*q));c.fillText(fmtTime(series[i].ts),x(i),H-8)});
  }

  let flow15InjectStarted=false;
  async function inject(){
    const content=document.getElementById('content');
    if(!content||document.getElementById('flow15Card')||flow15InjectStarted)return;
    flow15InjectStarted=true;
    let data;
    try{data=await(await fetch('../data/crypto_flow_history.json?t='+Date.now())).json()}catch(e){flow15InjectStarted=false;return}
    if(data.venue!=='Binance'){flow15InjectStarted=false;return}
    const rows=(data.points||[]).slice(-144);if(!rows.length){flow15InjectStarted=false;return}if(document.getElementById('flow15Card'))return;

    const spotSeries=rows.filter(r=>validNumber(r.spot_cvd_cumulative_btc));
    const perpSeries=rows.filter(r=>validNumber(r.perp_cvd_cumulative_btc));
    const oiSeries=rows.filter(r=>validNumber(r.binance_oi_usd));
    const fundingSeries=rows.filter(r=>validNumber(r.binance_funding_pct));
    const lastSpot=spotSeries[spotSeries.length-1]||{},lastPerp=perpSeries[perpSeries.length-1]||{},lastOi=oiSeries[oiSeries.length-1]||{},lastFunding=fundingSeries[fundingSeries.length-1]||{};
    let oiChange=null;if(oiSeries.length>=2&&Number(oiSeries[0].binance_oi_usd)!==0)oiChange=(Number(lastOi.binance_oi_usd)/Number(oiSeries[0].binance_oi_usd)-1)*100;

    const panel=(title,value,canvasId,series,wait,note)=>`<div class="flow15-panel"><div class="flow15-title">${title}</div><div class="flow15-value">${value}</div>${series.length>=2?`<canvas id="${canvasId}" class="flow15-canvas"></canvas>`:`<div class="flow15-wait">${wait}</div>`}<div class="flow15-note">${note}</div></div>`;
    const card=document.createElement('div');card.id='flow15Card';card.className='card flow15-card';
    card.innerHTML=`<div class="flow15-head"><div><h2>Coinalyze · Binance 10dk Akış ve Kaldıraç</h2><div class="note">Son 24 saat · Spot CVD + Futures CVD + Perp OI + Funding</div></div><div class="flow15-badge">Spot ${spotSeries.length} · Fut CVD ${perpSeries.length} · OI ${oiSeries.length} · FR ${fundingSeries.length}</div></div><div class="flow15-grid">${panel('Binance Spot BTC CVD · Coinalyze',btcFmt(lastSpot.spot_cvd_cumulative_btc),'spotCvd15Canvas',spotSeries,'Coinalyze spot CVD verisi bekleniyor.','Spot buy volume − sell volume; BTC cinsinden kümülatif CVD.')}${panel('Binance Futures BTC CVD · Coinalyze',btcFmt(lastPerp.perp_cvd_cumulative_btc),'perpCvd15Canvas',perpSeries,'Coinalyze futures CVD verisi bekleniyor.','Binance BTC perpetual buy volume − sell volume; BTC cinsinden kümülatif Futures CVD.')}${panel('Binance BTC Perp OI · Coinalyze',`${moneyCompact(lastOi.binance_oi_usd)} ${oiChange==null?'':`<span style="font-size:11px;color:${oiChange>=0?'#39ff88':'#ff5c5c'}">${oiChange>=0?'+':''}${oiChange.toFixed(2)}%</span>`}`,'oi15Canvas',oiSeries,'Coinalyze Binance OI history verisi bekleniyor.','BTC perpetual Open Interest USD; her 10dk bucket içindeki son 5dk close snapshotı.')}${panel('Binance BTC Funding Rate · Coinalyze',fundingFmt(lastFunding.binance_funding_pct),'funding15Canvas',fundingSeries,'Coinalyze funding history verisi bekleniyor.','Binance BTC perpetual funding-rate-history; pozitif değer longların shortlara, negatif değer shortların longlara ödeme yönünü gösterir.')}</div>`;
    content.insertBefore(card,content.firstChild);
    const draw=()=>{
      if(spotSeries.length>=2)lineChart(document.getElementById('spotCvd15Canvas'),rows,'spot_cvd_cumulative_btc',btcFmt,true);
      if(perpSeries.length>=2)lineChart(document.getElementById('perpCvd15Canvas'),rows,'perp_cvd_cumulative_btc',btcFmt,true);
      if(oiSeries.length>=2)lineChart(document.getElementById('oi15Canvas'),rows,'binance_oi_usd',moneyCompact,false);
      if(fundingSeries.length>=2)lineChart(document.getElementById('funding15Canvas'),rows,'binance_funding_pct',fundingFmt,true);
    };
    requestAnimationFrame(draw);window.addEventListener('resize',draw,{passive:true});
  }
  const obs=new MutationObserver(()=>{const c=document.getElementById('content');if(c&&c.children.length){inject();obs.disconnect()}});obs.observe(document.documentElement,{childList:true,subtree:true});if(document.readyState!=='loading')setTimeout(inject,300);else document.addEventListener('DOMContentLoaded',()=>setTimeout(inject,300));
})();