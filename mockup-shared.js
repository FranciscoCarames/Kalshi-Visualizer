"use strict";
/* ===== Shared engine for the Terminal Pro variations (7A–7D) =====
   Each variant supplies its own CSS implementing a fixed class CONTRACT and element ids.
   Color utilities (variant defines, palette-specific): .green .amber .red .cyan .violet .dim .white
   Right align: th.r / td.r .  Status dots are coloured text bullets.
   Component classes: .s .discl .blink | .tile .k .v .s | .btb(.act/.rev/.blk/.res/.on) .ct |
     table th td, tr.sel tr.research tr.fl, .nm .sub .up .nw .rt, .ty .tn .tr2 |
     .bk .bk-act/.bk-rev/.bk-blk/.bk-res | .bc .ac .f .px(.t) .tg |
     .des .col .dt .t .basis(button.on) .sect .leg(.y/.n/.l2) .kv(.l/.v) .cf .gz .note |
     .wr .n3 | .ar .m
   Element ids: #stat #tiles #bt #bl #lh #lt #lf #de #wa #al #lens #cmd #go #sim (#fly optional),
     .fk span[data-f], .tab[data-v], .view#v-opp/#v-res/#v-ops .
   Call TP_BOOT({sparkVar:'--amber', onSelect:fn, defaultSel:1}). */

const OPPS=[
 {id:1,b:"act",chg:"new",fl:true,tk:"SINNER",sport:"Tennis",name:"J. Sinner",sub:"Reach Final ⊇ Win Tournament",setup:"Containment",edge:7,roi:14.0,units:140,profit:9.80,trad:"Yes",cav:"—",sev:"",q:"Tight",spark:[34,35,33,36,38,37,38],cost:93,floor:100,worst:-7,best:7,be:93,fill:140,touch:38,legs:[["YES","Reach Final · KXATPADVANCE","38¢",140],["NO","Win · KXFOMEN","55¢",140]],why:"Firm child bid (Reach Final) exceeds the parent ask (Win) by 7¢ — a deeper outcome priced above the broader one that contains it.",rank:"Top under Blended: high ROI, tight quotes, size 140.",improve:"Already executable; more size as the Win ask deepens.",wrong:"A walkover advances without a match win — light rules check.",conf:{Data:95,Quote:92,Liquidity:78,Execution:80,Settlement:88,Strategy:96,Model:60,Comparability:84,Complexity:90}},
 {id:2,b:"act",chg:"up",fl:false,tk:"BRAZIL",sport:"Soccer",name:"Brazil v Serbia",sub:"Home / Away / Tie 3-way",setup:"Dutch overround",edge:11,roi:5.5,units:90,profit:9.90,trad:"Yes",cav:"Game postpone",sev:"adv",q:"OK",spark:[5,6,8,7,9,10,11],cost:211,floor:200,worst:-11,best:11,be:106,fill:90,touch:61,legs:[["NO","Home · KXWCGAME","61¢",90],["NO","Away · KXWCGAME","78¢",90],["NO","Tie · KXWCGAME","72¢",90]],why:"Σ no-ask across the 3 outcomes is 11¢ below the (n−1)×100¢ floor.",rank:"Edge up +6¢ since last scan.",improve:"Tighter Away quote adds size.",wrong:"Postponement caveat advisory; does not change tradable.",conf:{Data:94,Quote:80,Liquidity:70,Execution:74,Settlement:82,Strategy:95,Model:55,Comparability:80,Complexity:78}},
 {id:3,b:"act",chg:"",fl:false,tk:"OILERS",sport:"NHL",name:"Oilers @ Panthers",sub:"Head-to-head game book",setup:"Game dutch",edge:4,roi:4.0,units:200,profit:8.00,trad:"Yes",cav:"—",sev:"",q:"Tight",spark:[2,3,3,4,4,3,4],cost:96,floor:100,worst:-4,best:4,be:96,fill:200,touch:47,legs:[["YES","Oilers · KXNHLGAME","47¢",200],["YES","Panthers · KXNHLGAME","49¢",200]],why:"Underround: Σ yes-ask 96¢ < 100¢ on a draw-free 2-way game.",rank:"Strong on liquidity-first: size 200, tight.",improve:"Executable now.",wrong:"None material; draw-free.",conf:{Data:96,Quote:94,Liquidity:88,Execution:86,Settlement:90,Strategy:96,Model:62,Comparability:85,Complexity:92}},
 {id:4,b:"act",chg:"ret",fl:false,tk:"FAZE",sport:"Esports",name:"FaZe v Vitality",sub:"Map-1 (draw-free)",setup:"Map dutch",edge:3,roi:3.0,units:60,profit:1.80,trad:"Yes",cav:"—",sev:"",q:"OK",spark:[3,2,0,1,2,3,3],cost:97,floor:100,worst:-3,best:3,be:97,fill:60,touch:52,legs:[["YES","FaZe · KXCS2MAP","52¢",60],["YES","Vitality · KXCS2MAP","45¢",60]],why:"Underround on a 2-way draw-free map (97¢ < 100¢).",rank:"Returned to Actionable this scan.",improve:"Thin size — more depth helps.",wrong:"Allow-list maintained; esports churn.",conf:{Data:90,Quote:78,Liquidity:60,Execution:66,Settlement:86,Strategy:94,Model:50,Comparability:70,Complexity:88}},
 {id:5,b:"rev",chg:"new",fl:true,tk:"CELTICS",sport:"NBA",name:"Boston Celtics",sub:"Reach SF ≡ Win Conference",setup:"Equivalence",edge:4,roi:6.0,units:50,profit:2.00,trad:"Rule-dependent",cav:"RULE_CHECK_REQ",sev:"rev",q:"OK",spark:[1,2,3,3,4,4,4],cost:104,floor:100,worst:-4,best:4,be:104,fill:50,touch:71,legs:[["YES","Reach SF · KXNBA","71¢",50],["NO","Win Conf · KXNBA","33¢",50]],why:"Equivalence (round maps to a rung) implies a cross, but settlement wording differs by a token.",rank:"Review: rule-dependent, never auto-tradable.",improve:"Confirm settlement rules align → could promote.",wrong:"RULE_MISMATCH on a light token diff.",conf:{Data:88,Quote:76,Liquidity:64,Execution:60,Settlement:55,Strategy:80,Model:48,Comparability:72,Complexity:70}},
 {id:6,b:"rev",chg:"",fl:false,tk:"ALCARAZ",sport:"Tennis",name:"C. Alcaraz",sub:"Exact-score bundle ≡ Win",setup:"Synthetic",edge:5,roi:5.0,units:40,profit:2.00,trad:"Review rules",cav:"SETTLE_CHECK_REQ",sev:"rev",q:"Wide",spark:[4,5,5,4,5,5,5],cost:95,floor:100,worst:-5,best:5,be:95,fill:40,touch:54,legs:[["YES","3-0 · KXATPEXACT","12¢",40],["YES","3-1","18¢",40],["YES","3-2","21¢",40],["NO","Match winner","54¢",40]],why:"A bundle of MECE scorelines replicates 'they win' — priced 5¢ under the hedge.",rank:"Review-only by construction.",improve:"On a retirement the score legs settle to FMP — needs rule confirmation.",wrong:"Never Actionable; not a dutch book.",conf:{Data:84,Quote:58,Liquidity:50,Execution:48,Settlement:45,Strategy:78,Model:42,Comparability:60,Complexity:55}},
 {id:7,b:"blk",chg:"",fl:false,tk:"DODGERS",sport:"MLB",name:"LA Dodgers",sub:"Reach Playoffs ⊇ Win WS",setup:"Containment",edge:6,roi:0,units:0,profit:0,trad:"No",cav:"Blocked: no size",sev:"blk",q:"One-sided",spark:[6,6,5,6,6,6,6],cost:0,floor:100,worst:0,best:0,be:0,fill:0,touch:60,legs:[["YES","Reach Playoffs · KXMLB","—",0],["NO","Win WS · KXMLB","—",0]],why:"Display cross exists but the firm side has zero resting size — QUOTE_SIZE_MISSING.",rank:"Blocked: not executable now.",improve:"Resting size on the NO leg unblocks it.",wrong:"No fill possible at top-of-book.",conf:{Data:80,Quote:30,Liquidity:10,Execution:15,Settlement:78,Strategy:82,Model:40,Comparability:55,Complexity:75}},
 {id:8,b:"res",chg:"",fl:false,tk:"PAIRS",sport:"Tennis",name:"Alcaraz vs Sinner",sub:"Pairs divergence · z = −2.3",setup:"Research signal",edge:0,roi:0,units:0,profit:0,trad:"Research",cav:"not a trade",sev:"res",q:"—",spark:[0,-1,-1,-2,-2,-2,-2],cost:0,floor:0,worst:0,best:0,be:0,fill:0,touch:0,legs:[],why:"Co-movement baseline broke: Alcaraz Win richening vs Sinner — a relative-value hypothesis, not a trade.",rank:"Research surface only; may attach to a card as evidence (§5).",improve:"Needs calibration before any promotion (§0.4).",wrong:"Research only — never an actionability label.",conf:{Data:70,Quote:50,Liquidity:55,Execution:0,Settlement:0,Strategy:40,Model:62,Comparability:58,Complexity:50}},
];

function TP_BOOT(opts){
opts=opts||{};
const SPARK=opts.sparkVar||'--amber';
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const el=(id)=>document.getElementById(id);
const cssv=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const S={lens:"blended",tab:"act",sel:null,basis:1};
const lv=o=>S.lens==="edge"?o.edge:S.lens==="spread"?o.best-o.worst:S.lens==="ratio"?(o.cost?(o.best-o.worst)/o.cost*100:0):S.lens==="ev"?o.roi*.6+o.edge*.4:o.edge*.35+o.roi*.45+(o.best-o.worst)*.2;
function spark(pts){const c=cssv(SPARK)||'#ffb000';const w=52,h=13,mn=Math.min(...pts),mx=Math.max(...pts),rg=(mx-mn)||1,st=w/(pts.length-1);
  const d=pts.map((p,i)=>`${i?'L':'M'}${(i*st).toFixed(1)},${(h-2-((p-mn)/rg)*(h-4)).toFixed(1)}`).join(' ');
  return `<svg width="${w}" height="${h}" style="vertical-align:middle"><path d="${d}" fill="none" stroke="${c}" stroke-width="1.3"/></svg>`;}

function stat(){const e=el('stat');if(!e)return;e.innerHTML=
 '<span class="s" id="scanS"><b class="green">●</b> SCAN IDLE · last 12s</span><span class="s">Contracts <b>1,204</b></span><span class="s">Checks <b>747</b></span><span class="s">Req <b>49</b></span>'+
 '<span class="s"><b class="green">●</b> Exchange Open</span><span class="s">Auto-scan <b>on · 30s</b></span><span class="s"><b class="amber">●</b> Failed <b>1</b></span><span class="s">DB <b>42 MB</b></span>'+
 '<span class="s blink"><b class="red">●</b> ALRT 4</span><span class="s discl">Trading-paused ≠ data-stale · GROSS · TOP-OF-BOOK · $1 BASIS · READ-ONLY · NO ORDER ENTRY · NOT RISKLESS</span>';}

function tiles(){const e=el('tiles');if(!e)return;
 const act=OPPS.filter(o=>o.b==="act").length,rev=OPPS.filter(o=>o.b==="rev").length,nw=OPPS.filter(o=>o.chg==="new").length;
 const T=[["ACT-NOW",act,"green","executable","act"],["REVIEW",rev,"amber","settlement-dep","rev"],["NEW",nw,"","this scan","new"],["MOVERS",3,"","edge changed","mov"],["STALE",1,"red","one-sided","stale"],["FAILED",1,"amber","KXMOTOGP","fail"],["TOP LENS","+7¢","green","Sinner","top"]];
 e.innerHTML=T.map(t=>`<button class="tile" data-tile="${t[4]}"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></button>`).join("");
 $$('.tile',e).forEach(b=>b.onclick=()=>{const id=b.dataset.tile;if(id==="act"||id==="rev"){S.tab=id;btabs();blotter();}else if(id==="fail")setView('ops');});}

const TABS=[["act","ACTIONABLE","act"],["rev","REVIEW","rev"],["blk","BLOCKED","blk"],["res","RESEARCH","res"]];
function btabs(){const e=el('bt');if(!e)return;
 e.innerHTML=TABS.map(t=>{const c=OPPS.filter(o=>o.b===t[0]).length;return `<div class="btb ${t[2]} ${S.tab===t[0]?'on':''}" data-tab="${t[0]}">${t[1]}<span class="ct">${c}</span></div>`;}).join("");
 $$('.btb',e).forEach(t=>t.onclick=()=>{S.tab=t.dataset.tab;btabs();blotter();});}
function chg(o){return o.chg==="new"?'<span class="nw">NEW</span>':o.chg==="up"?'<span class="up"></span>':o.chg==="ret"?'<span class="rt">↺</span>':'';}
function blotter(){const e=el('bl');if(!e)return;
 const rows=OPPS.filter(o=>o.b===S.tab).sort((a,b)=>lv(b)-lv(a));const isRes=S.tab==="res";
 let h='<table><thead><tr><th></th><th>SPT</th><th>Participant / match</th><th>Setup</th>';
 h+=isRes?'<th>Signal</th><th>Note</th>':'<th class="r">Edge¢</th><th class="r">ROI%</th><th class="r">Units</th><th class="r">Profit$</th><th>Tradable</th><th>Caveat</th>';
 h+='</tr></thead><tbody>';
 rows.forEach(o=>{h+=`<tr data-id="${o.id}" class="${o.b==='res'?'research':''} ${S.sel===o.id?'sel':''} ${o.fl?'fl':''}"><td style="width:24px">${chg(o)}</td><td class="dim">${o.sport}</td>`+
  `<td><span class="nm">${o.name}</span> <span class="sub">${o.sub}</span> ${spark(o.spark)}</td><td style="font-family:var(--sans);color:var(--tx2)">${o.setup}</td>`;
  if(isRes)h+=`<td class="violet">z −2.3</td><td style="color:var(--violet);font-style:italic;font-size:9px">research — not a trade</td>`;
  else h+=`<td class="r ${o.chg==='up'?'green':''}">${o.edge||'—'}</td><td class="r">${o.roi?o.roi.toFixed(1):'—'}</td><td class="r">${o.units||'—'}</td><td class="r">${o.profit?o.profit.toFixed(2):'—'}</td>`+
   `<td class="${o.trad==='Yes'?'ty':o.trad==='No'?'tn':'tr2'}">${o.trad==='Yes'?'● ':o.trad==='No'?'○ ':'◐ '}${o.trad}</td><td class="${o.sev==='blk'?'red':o.sev==='rev'?'amber':'dim'}">${o.cav}</td>`;
  h+='</tr>';});
 if(!rows.length)h+=`<tr><td colspan="10" class="dim" style="text-align:center;height:30px">No rows in this bucket.</td></tr>`;
 e.innerHTML=h+'</tbody></table>';
 $$('tr[data-id]',e).forEach(tr=>tr.onclick=()=>select(+tr.dataset.id));}

function ladder(o){const lh=el('lh'),lt=el('lt'),lf=el('lf');if(!lt)return;
 if(o.b==="res"||!o.touch){if(lh)lh.innerHTML=`<div class="t">${o.name}</div><div class="s">research — no executable book</div>`;lt.innerHTML="";if(lf)lf.innerHTML="<span>—</span><span>research</span>";return;}
 if(lh)lh.innerHTML=`<div class="t">${o.name} <span class="dim">· ${o.sport}</span></div><div class="s">${o.legs[0][1]}</div>`;
 const base=o.touch;let h='<thead><tr><th>Bid size</th><th>Px¢</th><th>Ask size</th></tr></thead><tbody>';const maxsz=(o.fill*3.2)||120;
 for(let p=base+5;p>=base-5;p--){const bid=p<=base?Math.round(o.fill*(1+(base-p)*0.7)):0;const ask=p>=base?Math.round(o.fill*(1+(p-base)*0.6)):0;const tg=p===base+2?'<span class="tg">◀ watch</span>':'';
  h+=`<tr><td class="bc">${bid?`<span class="f" style="width:${Math.min(100,bid/maxsz*100)}%"></span><span>${bid}</span>`:''}</td><td class="px ${p===base?'t':''}">${p}${tg}</td><td class="ac">${ask?`<span class="f" style="width:${Math.min(100,ask/maxsz*100)}%"></span><span>${ask}</span>`:''}</td></tr>`;}
 lt.innerHTML=h+'</tbody>';if(lf)lf.innerHTML=`<span>Touch ${base}¢ · eff fill@50 ≈ ${o.cost+1}¢</span><span>max fill ${o.fill}</span>`;}

function confHTML(o){return Object.entries(o.conf).map(([k,v])=>`<div class="cf"><span class="dim">${k}</span><div class="gz"><i style="width:${v}%"></i></div><span class="r white">${v||'—'}</span></div>`).join("");}
function des(o){const e=el('de');if(!e)return;
 if(o.b==="res"){e.innerHTML=`<div class="des"><div class="col"><div class="dt"><span class="bk bk-res">RESEARCH</span><span class="t">${o.name}</span></div><div class="note"><b>${o.setup}.</b> ${o.why}</div><div class="sect">PROMOTION</div><div class="note">${o.rank}<br>${o.improve}</div></div><div class="col"><div class="sect">CONFIDENCE — 9 DIM</div>${confHTML(o)}<div class="sect">NOTE</div><div class="note">${o.wrong}</div></div></div>`;return;}
 const legs=o.legs.map(l=>`<div class="leg"><span class="${l[0]==='YES'?'y':'n'}">${l[0]}</span><span class="l2">${l[1]}</span><span class="white">${l[2]}</span><span class="dim">×${l[3]}</span></div>`).join("");
 const m=S.basis;const cv=c=>m===100?('$'+c.toFixed(2)):(c+'¢');
 e.innerHTML=`<div class="des"><div class="col"><div class="dt"><span class="bk bk-${o.b}">${o.b.toUpperCase()}</span><span class="t">${o.name}</span><div class="basis"><button class="${m===1?'on':''}" data-b="1">$1</button><button class="${m===100?'on':''}" data-b="100">$100</button></div></div>
  <div class="sub" style="margin-bottom:3px">${o.sub} · ${o.setup}</div><div class="sect">BUY-ONLY PLAN (LEGS)</div>${legs}
  <div class="kv" style="margin-top:4px"><span class="l">Cost / unit</span><span class="v">${cv(o.cost)}</span><span class="l">Payout floor</span><span class="v">${cv(o.floor)}</span><span class="l">Worst / best</span><span class="v">${o.worst}¢ / +${o.best}¢</span><span class="l">Break-even</span><span class="v">${o.be}%</span><span class="l">Fillable</span><span class="v">${o.fill}</span><span class="l">ROI</span><span class="v">${o.roi?o.roi.toFixed(1):'—'}%</span></div>
  <div class="sect">SCENARIO PAYOFF</div><div class="kv"><span class="l">Broader YES / deeper NO</span><span class="v green">+${o.best}¢</span><span class="l">Both settle same</span><span class="v red">${o.worst}¢</span><span class="l">Abnormal (retire/void)</span><span class="v amber">rule-dependent</span></div>
  <div class="sect">EVIDENCEPACK</div><div class="kv"><span class="l">Scan id</span><span class="v">scan_8841</span><span class="l">Quote ts</span><span class="v">12s</span><span class="l">Endpoints</span><span class="v">/markets /events</span><span class="l">Rules</span><span class="v">r3</span></div></div>
  <div class="col"><div class="sect">DECOMPOSED CONFIDENCE — 9 DIM</div>${confHTML(o)}<div class="sect">DEPTH (TOP-OF-BOOK → DERIVED)</div>
  <div class="kv"><span class="l green">YES bid ${o.legs[0][2]}</span><span class="v">${o.fill}</span><span class="l red">NO ask ${o.legs[o.legs.length-1][2]}</span><span class="v">${o.fill}</span></div>
  <div class="note">Eff fill @50 ≈ ${o.cost+1}¢ · asks derived from opposing bids (parity = data-quality only). Fees &amp; full depth NOT modeled.</div>
  <div class="sect">WHY FLAGGED · RANKED · IMPROVE · RISK</div><div class="note"><b>Flagged:</b> ${o.why}<br><b>Ranked:</b> ${o.rank}<br><b>Improve:</b> ${o.improve}<br><b>Risk:</b> ${o.wrong}</div></div></div>`;
 $$('.basis button',e).forEach(b=>b.onclick=()=>{S.basis=+b.dataset.b;des(o);});}

function watch(){const e=el('wa');if(!e)return;
 const W=[["Sinner — Reach Final ⊇ Win","Tennis · executable","live","green"],["Celtics — SF ≡ Win Conf","NBA · rule-check","+1¢","amber"],["CS2 Map 1 dutch","Esports · watching","+2¢","cyan"],["Dodgers — WS ladder","MLB · needs size","size 0","red"]];
 let h=W.map(w=>`<div class="wr"><span class="${w[3]}">●</span><div class="n3">${w[0]}<div class="sub">${w[1]}</div></div><span class="${w[3]}">${w[2]}</span></div>`).join("");
 h+='<div class="wr" style="border-top:1px solid var(--line2)"><span class="dim" style="font-size:8.5px;letter-spacing:.5px">MOVERS</span></div>';
 h+=OPPS.filter(o=>o.chg==="up"||o.chg==="ret").map(o=>`<div class="wr" data-id="${o.id}"><span class="${o.chg==='up'?'green':'amber'}">${o.chg==='up'?'▲':'↺'}</span><div class="n3">${o.name}<div class="sub">${o.sport} · ${o.setup}</div></div><span>${o.edge}¢</span></div>`).join("");
 e.innerHTML=h;$$('.wr[data-id]',e).forEach(r=>r.onclick=()=>select(+r.dataset.id));}
function alerts(){const e=el('al');if(!e)return;
 const A=[["became executable","Sinner Reach Final ⊇ Win","2m · firm both legs · size 140","green"],["bucket changed","Celtics ladder → Review","7m · rule-check required","amber"],["watched moved","CS2 Map 1 +3¢","9m","cyan"],["series failed","KXMOTOGP not fetched","12m · degraded","red"]];
 e.innerHTML=A.map(a=>`<div class="ar"><span class="${a[3]}" style="font-size:9px;line-height:1">●</span><div><div><b class="white">${a[0]}</b> — ${a[1]}</div><div class="m">${a[2]}</div></div></div>`).join("");}

function select(id){S.sel=id;const o=OPPS.find(x=>x.id===id);if(!o)return;if(o.b!==S.tab){S.tab=o.b;btabs();}blotter();ladder(o);des(o);if(opts.onSelect)opts.onSelect(o);}

function setView(v){$$('.tab').forEach(t=>t.classList.toggle('on',t.dataset.v===v));$$('.view').forEach(x=>x.classList.toggle('on',x.id==='v-'+v));}
function setLens(l){S.lens=l;$$('#lens button').forEach(b=>b.classList.toggle('on',b.dataset.l===l));blotter();}
function runCmd(raw){const c=(raw||"").trim().toUpperCase();if(!c)return;
 if(c==="OPP")return setView('opp');if(c==="RES")return setView('res');if(c==="OPS")return setView('ops');
 if(c==="ALRT"){const f=el('fly');if(f)f.classList.toggle('on');return;}
 const o=OPPS.find(x=>x.tk===c||x.name.toUpperCase().includes(c));if(o){setView('opp');select(o.id);}else{const i=el('cmd');if(i)i.placeholder="?? '"+c+"' not a function — try OPP/RES/OPS/ALRT/<ticker>";}}
function simulate(){document.body.classList.add('scanning');const s=el('scanS');if(s)s.innerHTML='<b class="amber">●</b> SCANNING · fetching…';
 setTimeout(()=>{if(s)s.innerHTML='<b class="amber">●</b> SCANNING · detecting (7)…';},800);
 setTimeout(()=>{document.body.classList.remove('scanning');if(s)s.innerHTML='<b class="green">●</b> SCAN IDLE · just now';OPPS.forEach(o=>o.fl=false);OPPS[0].fl=true;OPPS[4].fl=true;blotter();setTimeout(()=>{OPPS.forEach(o=>o.fl=false);},1900);},1700);}

// wire
stat();tiles();btabs();blotter();ladder(OPPS[0]);watch();alerts();
const goB=el('go');if(goB)goB.onclick=()=>{runCmd(el('cmd').value);el('cmd').value="";};
const ci=el('cmd');if(ci)ci.onkeydown=e=>{if(e.key==="Enter"){runCmd(ci.value);ci.value="";}};
$$('.fk span').forEach(f=>f.onclick=()=>runCmd(f.dataset.f));
$$('.tab').forEach(t=>t.onclick=()=>setView(t.dataset.v));
const lensEl=el('lens');if(lensEl)lensEl.onclick=e=>{if(e.target.dataset.l)setLens(e.target.dataset.l);};
const simB=el('sim');if(simB)simB.onclick=simulate;
let idx=0,g=false;
document.addEventListener('keydown',e=>{
 if(ci&&document.activeElement===ci){if(e.key==="Escape")ci.blur();return;}
 if(e.key==="/"){if(ci){e.preventDefault();ci.focus();}return;}
 if(e.key==="1")setLens("blended");if(e.key==="2")setLens("edge");if(e.key==="3")setLens("spread");
 if(g){g=false;if(e.key==="a"){S.tab="act";}if(e.key==="r"){S.tab="rev";}if(e.key==="b"){S.tab="blk";}btabs();blotter();return;}
 if(e.key==="g"){g=true;setTimeout(()=>g=false,800);return;}
 const rows=OPPS.filter(o=>o.b===S.tab).sort((a,b)=>lv(b)-lv(a));
 if(e.key==="j"){idx=Math.min(idx+1,rows.length-1);if(rows[idx])select(rows[idx].id);}
 if(e.key==="k"){idx=Math.max(idx-1,0);if(rows[idx])select(rows[idx].id);}
 if(e.key==="Enter"&&rows[idx])select(rows[idx].id);});
select(opts.defaultSel||1);
window.TP={select,setView,setLens,OPPS,state:S};
}
