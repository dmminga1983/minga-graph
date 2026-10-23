"""Self-contained interactive graph.html (no CDN, no network, works offline)."""

from __future__ import annotations

import json

from .model import Graph

DEFAULT_NODE_LIMIT = 4000


def _payload(g: Graph, node_limit: int):
    nodes = list(g.nodes.values())
    truncated = False
    if node_limit and len(nodes) > node_limit:
        truncated = True
        nodes.sort(key=lambda n: (n.kind in ("note", "heading"), -g.degree(n.id, skip_contains=False), n.id))
        nodes = nodes[:node_limit]
    idx = {n.id: i for i, n in enumerate(nodes)}
    N = [[n.name, n.kind, n.community, n.file, n.line, n.doc, g.degree(n.id), n.id] for n in nodes]
    E = [[idx[e.src], idx[e.dst], e.rel, 1 if e.conf == "EXTRACTED" else 0, e.why, e.at]
         for e in g.edges.values() if e.src in idx and e.dst in idx]
    C = {str(k): v["label"] for k, v in g.communities.items()}
    return {"n": N, "e": E, "c": C, "meta": g.meta, "truncated": truncated, "total": len(g.nodes)}


def build_html(g: Graph, node_limit: int = DEFAULT_NODE_LIMIT) -> str:
    data = json.dumps(_payload(g, node_limit), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    title = f"{g.meta.get('root_name', 'graph')} · minga-graph"
    return TEMPLATE.replace("__TITLE__", _esc(title)).replace("__DATA__", data)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#ffffff;--ink:#1d1f21;--muted:#6b6f76;--line:#d9dad7;--accent:#2f6fde;--edge:rgba(40,44,52,.16);--edgeHi:rgba(47,111,222,.85)}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--panel:#1b1e23;--ink:#e6e7e9;--muted:#9097a1;--line:#2d3138;--accent:#7aa7ff;--edge:rgba(220,225,235,.12);--edgeHi:rgba(122,167,255,.9)}}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
#app{display:grid;grid-template-columns:300px 1fr 360px;height:100vh}
aside{background:var(--panel);border-right:1px solid var(--line);overflow:auto;padding:14px}
#side{border-right:0;border-left:1px solid var(--line)}
h1{font-size:15px;margin:0 0 2px}h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:16px 0 6px}
.muted{color:var(--muted);font-size:12px}
input[type=search]{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
#results div,.comm,.nb{padding:4px 6px;border-radius:6px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#results div:hover,.comm:hover,.nb:hover{background:var(--bg)}
.comm{display:flex;gap:8px;align-items:center}.sw{width:10px;height:10px;border-radius:3px;flex:none}
.comm.off{opacity:.35}
label.k{display:inline-flex;gap:4px;align-items:center;margin:0 10px 4px 0;font-size:13px}
canvas{display:block;width:100%;height:100%;cursor:grab}
main{position:relative;overflow:hidden}
#hint{position:absolute;left:12px;bottom:10px;font-size:12px;color:var(--muted);background:var(--panel);padding:4px 8px;border-radius:6px;border:1px solid var(--line)}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:10px;border:1px solid var(--line);color:var(--muted);margin-left:4px}
.tag.ex{border-color:#3b9c5a;color:#3b9c5a}.tag.in{border-color:#c98a1b;color:#c98a1b}
.ev{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--muted)}
code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:4px 8px;cursor:pointer}
@media (max-width:900px){#app{grid-template-columns:1fr;grid-template-rows:auto 60vh auto}aside{border:0}}
</style>
</head>
<body>
<div id="app">
<aside>
  <h1 id="ttl"></h1><div class="muted" id="stats"></div>
  <h2>Search</h2>
  <input type="search" id="q" placeholder="name, file, doc…" autocomplete="off">
  <div id="results"></div>
  <h2>Kinds</h2><div id="kinds"></div>
  <h2>Edges</h2>
  <label class="k"><input type="checkbox" id="showContains"> contains</label>
  <label class="k"><input type="checkbox" id="onlyEx"> only EXTRACTED</label>
  <h2>Communities</h2>
  <div style="margin-bottom:6px"><button id="allOn">all</button> <button id="allOff">none</button></div>
  <div id="comms"></div>
</aside>
<main><canvas id="cv"></canvas><div id="hint">drag to pan · wheel to zoom · click a node</div></main>
<aside id="side"><div class="muted">Click a node to see its connections and the evidence for each edge.</div></aside>
</div>
<script>
"use strict";
const D = __DATA__;
const $ = s => document.querySelector(s);
const N = D.n.map((a,i)=>({i,name:a[0],kind:a[1],c:a[2],file:a[3],line:a[4],doc:a[5],deg:a[6],id:a[7],x:0,y:0,vx:0,vy:0}));
const E = D.e.map(a=>({s:a[0],t:a[1],rel:a[2],ex:a[3]===1,why:a[4],at:a[5]}));
const adj = N.map(()=>[]);
E.forEach((e,k)=>{adj[e.s].push(k);adj[e.t].push(k)});
const hue = c => (c*137.508)%360;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const col = c => c<0?'#888':`hsl(${hue(c)},${dark?62:58}%,${dark?62:46}%)`;
$('#ttl').textContent = (D.meta.root_name||'graph');
$('#stats').textContent = `${D.total} nodes, ${E.length} edges` + (D.truncated?` (showing ${N.length} most connected)`:'');
document.title = (D.meta.root_name||'graph')+' · minga-graph';

// ---- filters
const kinds = [...new Set(N.map(n=>n.kind))].sort();
const kindOn = Object.fromEntries(kinds.map(k=>[k, !['note','heading','package'].includes(k) || N.length<400]));
$('#kinds').innerHTML = kinds.map(k=>`<label class="k"><input type="checkbox" data-k="${k}" ${kindOn[k]?'checked':''}> ${k} <span class="muted">${N.filter(n=>n.kind===k).length}</span></label>`).join('');
$('#kinds').addEventListener('change',e=>{kindOn[e.target.dataset.k]=e.target.checked;dirty=true});
const comms = Object.entries(D.c).map(([c,l])=>({c:+c,label:l,size:N.filter(n=>n.c===+c).length})).filter(x=>x.size>0).sort((a,b)=>b.size-a.size);
const commOn = Object.fromEntries(comms.map(x=>[x.c,true]));
function drawComms(){ $('#comms').innerHTML = comms.slice(0,60).map(x=>`<div class="comm ${commOn[x.c]?'':'off'}" data-c="${x.c}"><span class="sw" style="background:${col(x.c)}"></span><span>${esc(x.label)}</span><span class="muted">${x.size}</span></div>`).join(''); }
drawComms();
$('#comms').addEventListener('click',e=>{const d=e.target.closest('.comm');if(!d)return;const c=+d.dataset.c;commOn[c]=!commOn[c];drawComms();dirty=true});
$('#allOn').onclick=()=>{comms.forEach(x=>commOn[x.c]=true);drawComms();dirty=true};
$('#allOff').onclick=()=>{comms.forEach(x=>commOn[x.c]=false);drawComms();dirty=true};
$('#showContains').onchange=()=>dirty=true; $('#onlyEx').onchange=()=>dirty=true;
const visible = n => kindOn[n.kind] && (commOn[n.c]!==false);
const edgeVisible = e => (e.rel!=='contains'||$('#showContains').checked) && (e.ex||!$('#onlyEx').checked) && visible(N[e.s]) && visible(N[e.t]);
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

// ---- layout: communities seeded on a spiral, then a cooled force simulation with grid repulsion
const cv = $('#cv'), ctx = cv.getContext('2d');
let W=0,H=0,dpr=1;
function resize(){const r=cv.getBoundingClientRect();dpr=devicePixelRatio||1;W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;dirty=true}
addEventListener('resize',resize);
const cpos={};
comms.forEach((x,k)=>{const a=k*2.4,r=40*Math.sqrt(k)*Math.sqrt(N.length/50+1);cpos[x.c]=[Math.cos(a)*r,Math.sin(a)*r]});
let seed=1; const rnd=()=>{seed=(seed*16807)%2147483647;return seed/2147483647};
N.forEach(n=>{const p=cpos[n.c]||[0,0];n.x=p[0]+(rnd()-.5)*60;n.y=p[1]+(rnd()-.5)*60});
let alpha=1;
function step(){
  const k=30, cell=90, grid=new Map();
  for(const n of N){const key=Math.floor(n.x/cell)+','+Math.floor(n.y/cell);let b=grid.get(key);if(!b)grid.set(key,b=[]);b.push(n)}
  for(const n of N){const gx=Math.floor(n.x/cell), gy=Math.floor(n.y/cell);
    for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){const b=grid.get((gx+dx)+','+(gy+dy));if(!b)continue;
      for(const m of b){if(m.i<=n.i)continue;let x=n.x-m.x,y=n.y-m.y,d2=x*x+y*y+.01;if(d2>cell*cell)continue;const f=k*k/d2*alpha*.6;x*=f;y*=f;n.vx+=x;n.vy+=y;m.vx-=x;m.vy-=y}}}
  for(const e of E){const a=N[e.s],b=N[e.t];let x=b.x-a.x,y=b.y-a.y;const d=Math.sqrt(x*x+y*y)+.01;const L=e.rel==='contains'?25:45;const f=(d-L)/d*.04*alpha*(e.rel==='depends_on'?.2:1);x*=f;y*=f;a.vx+=x;a.vy+=y;b.vx-=x;b.vy-=y}
  for(const n of N){const p=cpos[n.c]||[0,0];n.vx+=(p[0]-n.x)*.004*alpha;n.vy+=(p[1]-n.y)*.004*alpha;n.vx-=n.x*.0008*alpha;n.vy-=n.y*.0008*alpha;
    if(n!==dragN){n.x+=Math.max(-20,Math.min(20,n.vx));n.y+=Math.max(-20,Math.min(20,n.vy))} n.vx*=.55;n.vy*=.55}
  alpha*=.985;
}
// ---- view
let tx=0,ty=0,sc=1,dirty=true,sel=-1,hover=-1,dragN=null;
function fit(){let a=1e9,b=1e9,c=-1e9,d=-1e9;N.forEach(n=>{if(!visible(n))return;a=Math.min(a,n.x);b=Math.min(b,n.y);c=Math.max(c,n.x);d=Math.max(d,n.y)});if(a>c)return;sc=Math.min(W/(c-a+80),H/(d-b+80),2.5);tx=W/2-(a+c)/2*sc;ty=H/2-(b+d)/2*sc;dirty=true}
const rad = n => 2.5+Math.sqrt(n.deg)*1.4;
function draw(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
  ctx.translate(tx,ty);ctx.scale(sc,sc);
  const hi=new Set(); if(sel>=0){hi.add(sel);adj[sel].forEach(k=>{hi.add(E[k].s);hi.add(E[k].t)})}
  const cs=getComputedStyle(document.documentElement);
  ctx.lineWidth=1/sc;
  ctx.strokeStyle=cs.getPropertyValue('--edge');ctx.beginPath();
  for(const e of E){if(!edgeVisible(e))continue;if(sel>=0&&(e.s===sel||e.t===sel))continue;const a=N[e.s],b=N[e.t];ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y)}
  ctx.stroke();
  if(sel>=0){ctx.strokeStyle=cs.getPropertyValue('--edgeHi');ctx.lineWidth=1.6/sc;
    for(const k of adj[sel]){const e=E[k];if(!edgeVisible(e)&&!(e.rel==='contains'))continue;const a=N[e.s],b=N[e.t];ctx.setLineDash(e.ex?[]:[4/sc,3/sc]);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}ctx.setLineDash([])}
  for(const n of N){if(!visible(n))continue;ctx.globalAlpha=(sel<0||hi.has(n.i))?1:.18;ctx.fillStyle=col(n.c);ctx.beginPath();
    const r=rad(n); if(n.kind==='file'){ctx.rect(n.x-r,n.y-r,2*r,2*r)}else if(n.kind==='package'){ctx.moveTo(n.x,n.y-r);ctx.lineTo(n.x+r,n.y+r);ctx.lineTo(n.x-r,n.y+r);ctx.closePath()}else{ctx.arc(n.x,n.y,r,0,7)} ctx.fill();
    if(n.i===sel||n.i===hover){ctx.lineWidth=2/sc;ctx.strokeStyle=cs.getPropertyValue('--ink');ctx.stroke()}}
  ctx.globalAlpha=1;ctx.fillStyle=cs.getPropertyValue('--ink');ctx.font=`${12/sc}px system-ui,sans-serif`;
  const minDeg = sc>1.6?0:sc>.8?4:10;
  for(const n of N){if(!visible(n))continue;if(!(n.deg>=minDeg||hi.has(n.i)||n.i===hover))continue;if(sel>=0&&!hi.has(n.i))continue;ctx.fillText(n.name.length>40?n.name.slice(0,39)+'…':n.name,n.x+rad(n)+2/sc,n.y+4/sc)}
}
function loop(){ if(alpha>0.02){for(let i=0;i<2;i++)step();dirty=true} if(dirty){draw();dirty=false} requestAnimationFrame(loop) }
// ---- interaction
function toWorld(px,py){return[(px-tx)/sc,(py-ty)/sc]}
function pick(px,py){const[x,y]=toWorld(px,py);let best=-1,bd=1e9;for(const n of N){if(!visible(n))continue;const d=(n.x-x)**2+(n.y-y)**2,r=rad(n)+4/sc;if(d<r*r&&d<bd){bd=d;best=n.i}}return best}
let down=null,moved=false;
cv.addEventListener('mousedown',e=>{const r=cv.getBoundingClientRect();const p=pick(e.clientX-r.left,e.clientY-r.top);down=[e.clientX,e.clientY,tx,ty];moved=false;if(p>=0){dragN=N[p]}});
addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();if(down){const dx=e.clientX-down[0],dy=e.clientY-down[1];if(Math.abs(dx)+Math.abs(dy)>3)moved=true;
  if(dragN){const[x,y]=toWorld(e.clientX-r.left,e.clientY-r.top);dragN.x=x;dragN.y=y}else{tx=down[2]+dx;ty=down[3]+dy}dirty=true}
  else if(e.target===cv){const h=pick(e.clientX-r.left,e.clientY-r.top);if(h!==hover){hover=h;dirty=true;cv.style.cursor=h>=0?'pointer':'grab'}}});
addEventListener('mouseup',e=>{if(down&&!moved){const r=cv.getBoundingClientRect();select(pick(e.clientX-r.left,e.clientY-r.top))}down=null;dragN=null});
cv.addEventListener('wheel',e=>{e.preventDefault();const r=cv.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top;const f=Math.exp(-e.deltaY*.0015);tx=px-(px-tx)*f;ty=py-(py-ty)*f;sc*=f;dirty=true},{passive:false});
function select(i){sel=i;dirty=true;const s=$('#side');if(i<0){s.innerHTML='<div class="muted">Click a node to see its connections.</div>';return}
  const n=N[i];const out=[],inc=[];adj[i].forEach(k=>{const e=E[k];(e.s===i?out:inc).push(e)});
  const row=(e,o)=>`<div class="nb" data-i="${o}" title="${esc(e.why)}">${e.s===i?'→':'←'} <b>${esc(N[o].name)}</b> <span class="tag">${e.rel}</span><span class="tag ${e.ex?'ex':'in'}">${e.ex?'EXTRACTED':'INFERRED'}</span><div class="ev">${esc(e.why)}${e.at?' @ '+esc(e.at):''}</div></div>`;
  s.innerHTML=`<h1>${esc(n.name)}</h1><div class="muted">${n.kind} · community ${n.c}${D.c[n.c]?' ('+esc(D.c[n.c])+')':''}</div>`+
   (n.file?`<p><code>${esc(n.file)}${n.line?':'+n.line:''}</code></p>`:'')+(n.doc?`<p>${esc(n.doc)}</p>`:'')+
   `<h2>Outgoing (${out.length})</h2>`+out.map(e=>row(e,e.t)).join('')+`<h2>Incoming (${inc.length})</h2>`+inc.map(e=>row(e,e.s)).join('');
}
$('#side').addEventListener('click',e=>{const d=e.target.closest('.nb');if(!d)return;const i=+d.dataset.i;focusNode(i)});
function focusNode(i){const n=N[i];kindOn[n.kind]=true;commOn[n.c]=true;drawComms();document.querySelectorAll('#kinds input').forEach(x=>{if(x.dataset.k===n.kind)x.checked=true});sc=Math.max(sc,1.4);tx=W/2-n.x*sc;ty=H/2-n.y*sc;select(i)}
$('#q').addEventListener('input',()=>{const q=$('#q').value.trim().toLowerCase();const r=$('#results');if(!q){r.innerHTML='';return}
  const hits=N.filter(n=>n.name.toLowerCase().includes(q)||n.file.toLowerCase().includes(q)||(n.doc||'').toLowerCase().includes(q)).sort((a,b)=>(a.name.toLowerCase()===q?-1:0)-(b.name.toLowerCase()===q?-1:0)||b.deg-a.deg).slice(0,30);
  r.innerHTML=hits.map(n=>`<div data-i="${n.i}"><span class="sw" style="display:inline-block;background:${col(n.c)}"></span> ${esc(n.name)} <span class="muted">${n.kind}</span></div>`).join('')});
$('#results').addEventListener('click',e=>{const d=e.target.closest('[data-i]');if(d)focusNode(+d.dataset.i)});
addEventListener('keydown',e=>{if(e.key==='Escape')select(-1);if(e.key==='/'&&document.activeElement!==$('#q')){e.preventDefault();$('#q').focus()}});
resize(); for(let i=0;i<120;i++)step(); fit(); loop();
setTimeout(fit,1500);
</script>
</body>
</html>
"""
