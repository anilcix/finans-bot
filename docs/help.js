function tip(text){const s=String(text??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');return `<span class="help-tip" tabindex="0" aria-label="${s}" data-tip="${s}">?</span>`}

(function(){
  if(!location.pathname.includes('crypto_derivatives.html')) return;

  const moneyCompact=v=>{if(v==null||!isFinite(v))return'—';const a=Math.abs(v);const sign=v<0?'-':'';if(a>=1e9)return sign+'$'+(a/1e9).toFixed(2)+'B';if(a>=1e6)return sign+'$'+(a/1e6).toFixed(1)+'M';if(a>=1e3)return sign+'$'+(a/1e3).toFixed(1)+'K';return sign+'$'+a.toFixed(0)};
  const css=`
    .flow15-card{border-left:3px solid #5aa9ff}
    .flow15-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap}
    .flow15-badge{font-size:9px;border:1px solid var(--green-dim);border-radius:999px;padding:4px 8px;color:var(--muted)}
    .flow15-grid{display:grid;grid-template-columns:1fr;gap:14px;margin-top:12px}
    .flow15-panel{border:1px solid var(--green-dim);border-radius:10px;padding:10px;overflow:hidden}
    .flow15-title{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
    .flow15-value{font-size:20px;font-weight:800;margin-bottom:8px}
    .flow15-canvas{width:100%;height:220px;display:block}
    .flow15-note{font-size:9px;line-height:1.55;color:var(--muted);margin-top:8px}
    @media(max-width:700px){.flow15-canvas{height:190px}}
  `;
  const style=document.createElement('style');style.textContent=css;document.head.appendChild(style);

  function fmtTime(v){try{return new Intl.DateTimeFormat('tr-TR',{timeZone:'Europe/Istanbul',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}catch(e){return''}}

  function lineChart(canvas, rows, key, valueFormatter, zeroLine=false){
    if(!canvas||!rows.length)return;
    const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1,W=Math.max(300,rect.width),H=Math.max(180,rect.height);
    canvas.width=W*dpr;canvas.height=H*dpr;const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,W,H);
    const pad={l:58,r:12,t:12,b:28},pw=W-pad.l-pad.r,ph=H-pad.t-pad.b;
    const vals=rows.map(r=>Number(r[key])).filter(Number.isFinite);if(!vals.length)return;
    let min=Math.min(...vals),max=Math.max(...vals);if(zeroLine){min=Math.min(min,0);max=Math.max(max,0)};if(min===max){const bump=Math.abs(min||1)*.05;min-=bump;max+=bump}
    const x=i=>pad.l+(rows.length===1?pw/2:pw*i/(rows.length-1));const y=v=>pad.t+ph*(1-(v-min)/(max-min));
    c.font='9px IBM Plex Mono, monospace';c.lineWidth=1;
    for(let i=0;i<=4;i++){const yy=pad.t+ph*i/4,val=max-(max-min)*i/4;c.strokeStyle='rgba(92,138,114,.14)';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke();c.fillStyle='#5c8a72';c.textAlign='right';c.fillText(valueFormatter(val),pad.l-6,yy+3)}
    if(zeroLine&&min<0&&max>0){const yy=y(0);c.strokeStyle='rgba(255,207,92,.35)';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke()}
    c.strokeStyle='#39ff88';c.lineWidth=2;c.beginPath();let started=false;rows.forEach((r,i)=>{const v=Number(r[key]);if(!Number.isFinite(v))return;const xx=x(i),yy=y(v);if(!started){c.moveTo(xx,yy);started=true}else c.lineTo(xx,yy)});c.stroke();
    c.fillStyle='#5c8a72';c.textAlign='center';const marks=[0,.25,.5,.75,1];marks.forEach(q=>{const i=Math.min(rows.length-1,Math.round((rows.length-1)*q));c.fillText(fmtTime(rows[i].ts),x(i),H-8)});
  }

  async function inject(){
    const content=document.getElementById('content');if(!content||document.getElementById('flow15Card'))return;
    let data;try{data=await(await fetch('../data/crypto_flow_history.json?t='+Date.now())).json()}catch(e){return}
    const raw=(data.points||[]).slice(-96);if(!raw.length)return;
    let cum=0;const rows=raw.map(p=>{const d=Number(p.spot_cvd_delta_usd);if(Number.isFinite(d))cum+=d;return {...p,spot_cvd_cumulative_usd:Number.isFinite(d)?cum:null}});
    const last=rows[rows.length-1]||{};const oiStart=rows.find(r=>Number.isFinite(Number(r.aggregate_oi_usd)));const oiEnd=[...rows].reverse().find(r=>Number.isFinite(Number(r.aggregate_oi_usd)));let oiChange=null;if(oiStart&&oiEnd&&Number(oiStart.aggregate_oi_usd)!==0)oiChange=(Number(oiEnd.aggregate_oi_usd)/Number(oiStart.aggregate_oi_usd)-1)*100;
    const spotCoverage=raw.filter(r=>r.spot_ok).length;
    const card=document.createElement('div');card.id='flow15Card';card.className='card flow15-card';card.innerHTML=`
      <div class="flow15-head"><div><h2>15dk Spot CVD + Perp OI</h2><div class="note">Son 24 saat · 96 × 15dk bucket</div></div><div class="flow15-badge">${rows.length}/96 nokta</div></div>
      <div class="flow15-grid">
        <div class="flow15-panel"><div class="flow15-title">Kraken Spot CVD · Kümülatif USD</div><div class="flow15-value">${moneyCompact(last.spot_cvd_cumulative_usd)}</div><canvas id="spotCvd15Canvas" class="flow15-canvas"></canvas><div class="flow15-note">Her 15 dakikada Kraken BTC/USD spot agresif alış notionalı eksi agresif satış notionalı hesaplanır; grafik 24 saat içindeki kümülatif akışı gösterir. Pozitif eğim spot alıcı baskısı, negatif eğim spot satıcı baskısıdır. Geçerli bucket: ${spotCoverage}/${rows.length}.</div></div>
        <div class="flow15-panel"><div class="flow15-title">Coinalyze Aggregate BTC Perp OI</div><div class="flow15-value">${moneyCompact(last.aggregate_oi_usd)} ${oiChange==null?'':`<span style="font-size:11px;color:${oiChange>=0?'#39ff88':'#ff5c5c'}">${oiChange>=0?'+':''}${oiChange.toFixed(2)}%</span>`}</div><canvas id="oi15Canvas" class="flow15-canvas"></canvas><div class="flow15-note">OI spot değildir; bu panel Coinalyze üzerinden seçili büyük BTC perpetual piyasalarının aggregate açık pozisyonunu her 15 dakikada snapshot olarak kaydeder. CVD ile birlikte okununca hareketin spot talep mi yoksa kaldıraç birikimi mi olduğunu ayırmaya yardımcı olur.</div></div>
      </div>`;
    content.insertBefore(card,content.firstChild);
    requestAnimationFrame(()=>{lineChart(document.getElementById('spotCvd15Canvas'),rows,'spot_cvd_cumulative_usd',moneyCompact,true);lineChart(document.getElementById('oi15Canvas'),rows,'aggregate_oi_usd',moneyCompact,false)});
    window.addEventListener('resize',()=>{lineChart(document.getElementById('spotCvd15Canvas'),rows,'spot_cvd_cumulative_usd',moneyCompact,true);lineChart(document.getElementById('oi15Canvas'),rows,'aggregate_oi_usd',moneyCompact,false)},{passive:true});
  }

  const obs=new MutationObserver(()=>{const c=document.getElementById('content');if(c&&c.children.length){inject();obs.disconnect()}});obs.observe(document.documentElement,{childList:true,subtree:true});
  if(document.readyState!=='loading')setTimeout(inject,300);else document.addEventListener('DOMContentLoaded',()=>setTimeout(inject,300));
})();
