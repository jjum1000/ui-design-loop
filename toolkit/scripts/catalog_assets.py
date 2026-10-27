"""카탈로그 공용 에셋(catalog/assets/): 스타일·스크립트·폰트. build_catalog.py 가 빌드 때마다 쓴다.
디자인: '라이트 테이블' — 어두운 작업대 위에 게임 화면 렌더를 올려 보는 탐색기(노랑·검정, 하프톤, 기울어진 탭).
외부 CDN·웹폰트 없음 — 표시 폰트는 project.json `catalog.fonts`(family · files[{name, src, weight}])의 Unity 프로젝트
OTF 를 vendor/ 로 복사해 쓴다(file:// 동작). 설정이 없으면 시스템 폰트만 쓴다.
"""
import os
import shutil

import common as C

_FONT = (C.project() or {}).get("catalog", {}).get("fonts") or {}
FONTS = {f["name"]: f["src"] for f in _FONT.get("files", [])}

CSS = r"""
@@FONT_FACES@@
:root{--bg:#12110e;--bg2:#191813;--panel:#1e1d18;--panel2:#26241e;--line:#35332b;--fg:#eeeadf;--mut:#9b978a;
--acc:#ffd21f;--ink:#12110e;--cyan:#35d0f0;--ok:#6fd38a;--bad:#ff7a6e;--warn:#e9b44c;--dot:rgba(255,255,255,.045);
--chk1:#2a2924;--chk2:#22211c;--shadow:0 10px 30px rgba(0,0,0,.45);
--disp:@@DISP_FAMILY@@"Malgun Gothic","Apple SD Gothic Neo",sans-serif;--body:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
--mono:Consolas,"D2Coding",ui-monospace,monospace;color-scheme:dark}
@media (prefers-color-scheme:light){:root:not([data-theme=dark]){--bg:#ece8dc;--bg2:#e3dfd2;--panel:#faf8f2;--panel2:#f1eee5;--line:#d2cdbd;
--fg:#17160f;--mut:#6b675a;--acc:#f4c400;--dot:rgba(0,0,0,.06);--chk1:#dcd8cc;--chk2:#e9e6dc;--shadow:0 8px 24px rgba(40,30,0,.14);color-scheme:light}}
:root[data-theme=light]{--bg:#ece8dc;--bg2:#e3dfd2;--panel:#faf8f2;--panel2:#f1eee5;--line:#d2cdbd;--fg:#17160f;--mut:#6b675a;--acc:#f4c400;
--dot:rgba(0,0,0,.06);--chk1:#dcd8cc;--chk2:#e9e6dc;--shadow:0 8px 24px rgba(40,30,0,.14);color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 var(--body);
background-image:radial-gradient(var(--dot) 1.1px,transparent 1.5px);background-size:13px 13px;min-height:100vh}
a{color:inherit;text-decoration-color:var(--acc);text-underline-offset:3px}a:hover{color:var(--acc)}
.mut{color:var(--mut)}.warn{color:var(--warn)}.mono{font-family:var(--mono);font-size:12px}
/* ---------- 상단 셸 */
.top{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:18px;padding:0 18px;height:54px;
background:var(--ink);border-bottom:3px solid var(--acc);color:#eeeadf}
.brand{display:flex;align-items:center;gap:8px;text-decoration:none;font:700 24px/1 var(--disp);letter-spacing:.5px;color:#eeeadf}
.brand b{display:inline-block;background:var(--acc);color:var(--ink);padding:4px 10px 2px;transform:skewX(-14deg)}
.brand b span{display:inline-block;transform:skewX(14deg)}
.nav{display:flex;gap:2px;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;flex:1}
.nav a{position:relative;padding:6px 14px 4px;font:700 15px/1 var(--disp);letter-spacing:.6px;text-transform:uppercase;text-decoration:none;
color:#bdb8a8;transform:skewX(-14deg);border:1px solid transparent;white-space:nowrap}
.nav a>span{display:inline-block;transform:skewX(14deg)}.nav a:hover{color:#fff;border-color:#4a473c}
.nav a.on{background:#eeeadf;color:var(--ink)}.nav .sep{width:10px}
.nav .sub{font-size:13px;color:#8d8878}
.themebtn{background:none;border:1px solid #4a473c;color:#eeeadf;border-radius:20px;padding:4px 10px;cursor:pointer;font:12px var(--body)}
.crumbs{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:10px 22px 0;font:12px var(--mono);color:var(--mut)}
.crumbs a{text-decoration:none;color:var(--fg);padding:2px 8px;background:var(--panel2);border:1px solid var(--line)}
.crumbs a:hover{border-color:var(--acc)}.crumbs i{font-style:normal;color:var(--acc)}
main{max-width:1500px;margin:0 auto;padding:14px 22px 60px}
main.wide{max-width:none}
h1{font:700 44px/1 var(--disp);letter-spacing:.5px;margin:14px 0 6px;text-transform:uppercase;overflow-wrap:anywhere}
h1 small{font:13px var(--body);color:var(--mut);text-transform:none;letter-spacing:0;margin-left:10px}
h2{font:700 22px/1.1 var(--disp);letter-spacing:.6px;text-transform:uppercase;margin:34px 0 12px;display:flex;align-items:center;gap:10px}
h2::before{content:"";width:14px;height:14px;background:var(--acc);transform:skewX(-14deg)}
h2 .n{font:12px var(--mono);color:var(--mut);text-transform:none}
h3{font-size:14px;margin:18px 0 6px}
/* ---------- 공통 조각 */
.kpis{display:flex;flex-wrap:wrap;gap:0;margin:14px 0 6px;border:1px solid var(--line);background:var(--panel);width:fit-content;max-width:100%}
.kpi{padding:10px 18px;border-right:1px solid var(--line)}.kpi:last-child{border-right:0}
.kpi b{display:block;font:700 30px/1 var(--disp);color:var(--fg)}.kpi span{font-size:11px;color:var(--mut);letter-spacing:.3px}
.kpi.hot b{color:var(--acc)}
.tag{display:inline-block;padding:1px 7px;font:11px/1.5 var(--mono);border:1px solid var(--line);color:var(--mut);background:var(--panel2);white-space:nowrap}
.tag.y{background:var(--acc);color:var(--ink);border-color:var(--acc)}.tag.c{color:var(--cyan);border-color:var(--cyan)}
.tag.r{color:var(--bad);border-color:var(--bad)}.tag.g{color:var(--ok);border-color:var(--ok)}
.chk{background-color:var(--chk2);background-image:linear-gradient(45deg,var(--chk1) 25%,transparent 25%,transparent 75%,var(--chk1) 75%),
linear-gradient(45deg,var(--chk1) 25%,transparent 25%,transparent 75%,var(--chk1) 75%);background-size:16px 16px;background-position:0 0,8px 8px}
.note{border-left:3px solid var(--acc);background:var(--panel);padding:8px 12px;margin:10px 0;color:var(--mut);font-size:13px}
/* ---------- 카드 그리드 */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.cards.sm{grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.tc{position:relative;display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--line);text-decoration:none;color:var(--fg);
transition:transform .16s ease,border-color .16s,box-shadow .16s;animation:rise .45s both;animation-delay:calc(var(--i,0)*12ms)}
.tc:hover{transform:translateY(-3px);border-color:var(--acc);box-shadow:var(--shadow);color:var(--fg)}
.tc .ph{aspect-ratio:16/10;display:flex;align-items:center;justify-content:center;overflow:hidden;border-bottom:1px solid var(--line)}
.tc .ph.wide{aspect-ratio:16/9}
.tc .ph img{max-width:92%;max-height:88%;object-fit:contain;filter:drop-shadow(0 2px 4px rgba(0,0,0,.35))}
.tc .ph.full img{max-width:100%;max-height:100%;width:100%;height:100%;object-fit:cover;filter:none}
.tc .ph .none{font:11px var(--mono);color:var(--mut);padding:10px;text-align:center}
.tc .meta{padding:8px 10px 10px;display:flex;flex-direction:column;gap:4px;min-width:0}
.tc .nm{font-weight:700;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tc .sub{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--mut)}
.tc .big{position:absolute;top:6px;right:8px;font:700 26px/1 var(--disp);color:var(--acc);text-shadow:0 1px 0 var(--ink),0 0 8px rgba(0,0,0,.5)}
.tc .corner{position:absolute;top:0;left:0;padding:2px 8px;font:700 12px/1.3 var(--disp);letter-spacing:.5px;background:var(--ink);color:var(--acc);text-transform:uppercase}
.bar{height:5px;background:var(--panel2);border:1px solid var(--line);position:relative;overflow:hidden}
.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--acc)}.bar i+i{background:var(--cyan)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.tc{animation:none}}
/* ---------- 필터 바 */
.filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:14px 0;padding:10px;background:var(--panel);border:1px solid var(--line)}
.filters select,.filters input{font:13px var(--body);padding:6px 8px;background:var(--bg2);color:var(--fg);border:1px solid var(--line)}
.filters input[type=search]{min-width:220px}.filters .grow{flex:1}
.seg{display:inline-flex;border:1px solid var(--line)}
.seg button{font:700 13px/1 var(--disp);letter-spacing:.6px;text-transform:uppercase;padding:7px 12px;background:var(--bg2);color:var(--mut);border:0;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}.seg button.on{background:var(--acc);color:var(--ink)}
.hidden{display:none!important}
/* ---------- 표(레거시 페이지 포함) */
table{border-collapse:collapse;width:100%;margin:8px 0;display:block;overflow-x:auto;background:var(--panel);border:1px solid var(--line)}
th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top;white-space:nowrap}
th{font:700 13px var(--disp);letter-spacing:.5px;text-transform:uppercase;color:var(--mut);background:var(--panel2);position:sticky;top:0}
td.wrap{white-space:normal;word-break:break-all}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);padding:12px;overflow:hidden}
.card img{max-width:100%;max-height:120px;display:block;margin:6px 0}
.sw{display:inline-block;width:14px;height:14px;border:1px solid var(--line);vertical-align:middle;margin-right:4px}
.표준{color:var(--ok);border-color:var(--ok)}.폐기{color:var(--bad);border-color:var(--bad)}.예외{color:var(--warn);border-color:var(--warn)}.후보{color:var(--cyan);border-color:var(--cyan)}
button.cp{font:12px var(--mono);border:1px solid var(--line);background:transparent;color:var(--fg);cursor:pointer;padding:1px 6px}
.shots img{max-width:32%;min-width:200px;margin:4px;border:1px solid var(--line)}
.tree{font:12px/1.45 var(--mono);white-space:pre;overflow-x:auto;background:var(--panel);border:1px solid var(--line);padding:8px}
details{margin:2px 0}summary{cursor:pointer;padding:3px 0}.kids{margin-left:22px;border-left:1px solid var(--line);padding-left:10px}.leaf{padding:3px 0}
.banner{display:flex;align-items:center;gap:16px;padding:16px 20px;margin:10px 0 4px;background:var(--ink);color:#eeeadf;border-left:6px solid var(--acc);text-decoration:none}
.banner b{font:700 26px/1 var(--disp);text-transform:uppercase;color:var(--acc)}.banner:hover{color:#fff}
/* ---------- 앱 흐름 홈 */
.home{display:grid;grid-template-columns:minmax(300px,380px) 1fr;gap:26px;align-items:start}
@media (max-width:980px){.home{grid-template-columns:1fr}}
.phone{position:sticky;top:76px;padding:22px 18px 26px;border-radius:34px;background:linear-gradient(160deg,#25231d,#121110 70%);
border:2px solid #3b392f;box-shadow:var(--shadow),inset 0 0 0 6px #0c0b09;color:#eeeadf}
.phone .bar0{display:flex;justify-content:space-between;font:700 14px var(--disp);letter-spacing:.6px;color:#8d8878;margin:0 8px 16px}
.apps{display:grid;grid-template-columns:repeat(4,1fr);gap:14px 8px}
.app{display:flex;flex-direction:column;align-items:center;gap:6px;background:none;border:0;padding:0;cursor:pointer;color:#eeeadf;font:11px/1.2 var(--body);text-align:center}
.app .ic{width:62px;height:62px;border-radius:16px;display:flex;align-items:center;justify-content:center;background:#2b2922;
border:2px solid #3b392f;transition:transform .15s,border-color .15s;position:relative}
.app .ic img{width:48px;height:48px;object-fit:contain}
.app .ic em{font:700 22px var(--disp);font-style:normal;color:var(--acc)}
.app:hover .ic{transform:scale(1.07);border-color:#777}.app.on .ic{border-color:var(--acc);box-shadow:0 0 0 3px rgba(255,210,31,.25),0 0 18px rgba(255,210,31,.35)}
.app.off{opacity:.42}.app.off .ic::after{content:"";position:absolute;inset:0;border-radius:14px;
background:repeating-linear-gradient(-45deg,transparent 0 6px,rgba(0,0,0,.45) 6px 9px)}
.app .lb{max-width:78px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.app .st{font:10px var(--mono);color:var(--warn)}
.flow{min-width:0}
.flowhead{display:flex;align-items:flex-end;gap:14px;flex-wrap:wrap}
.flowhead h2{margin:0}.flowhead .tag{margin-bottom:3px}
.lane{display:flex;gap:0;overflow-x:auto;padding:14px 2px 18px;align-items:flex-start}
.col{display:flex;flex-direction:column;gap:12px;flex:0 0 232px}
.col .step{font:700 13px var(--disp);letter-spacing:1px;color:var(--mut);text-transform:uppercase}
.arrow{flex:0 0 44px;align-self:stretch;display:flex;align-items:center;justify-content:center;position:relative}
.arrow::before{content:"";position:absolute;left:8px;right:12px;top:92px;height:3px;background:var(--acc)}
.arrow::after{content:"";position:absolute;right:6px;top:85px;border:8px solid transparent;border-left:10px solid var(--acc);border-right:0}
.fcard .ph{aspect-ratio:16/9}
.fcard .nx{font:11px var(--mono);color:var(--mut)}
.fcard.rep{opacity:.55}
.fcard .via{font:10px var(--mono);color:var(--cyan)}
.empty{padding:40px;text-align:center;color:var(--mut);border:1px dashed var(--line)}
/* ---------- 배치 맵 뷰어 */
.viewer{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:0;border:1px solid var(--line);background:var(--panel);margin-top:10px}
@media (max-width:1100px){.viewer{grid-template-columns:1fr}.side{max-height:420px}}
.vtool{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:8px 10px;border-bottom:1px solid var(--line);background:var(--panel2)}
.vtool .z{font:12px var(--mono);min-width:46px;text-align:center}
.vtool button.ib{font:700 16px/1 var(--disp);width:30px;height:28px;background:var(--bg2);color:var(--fg);border:1px solid var(--line);cursor:pointer}
.vtool button.ib:hover{border-color:var(--acc)}
.vtool label{font-size:12px;color:var(--mut);display:flex;gap:4px;align-items:center;cursor:pointer}
.vtool .legend{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto;font:11px var(--mono);color:var(--mut)}
.vtool .legend i{display:inline-block;width:10px;height:10px;border:2px solid var(--c);margin-right:3px;vertical-align:-1px}
.stagewrap{overflow:auto;height:calc(100vh - 240px);min-height:380px;display:flex;align-items:flex-start;justify-content:center;padding:18px}
.stagewrap.small{height:auto;max-height:calc(100vh - 240px)}
.stage{position:relative;flex:0 0 auto;box-shadow:var(--shadow);outline:1px solid var(--line)}
.stage img{display:block;width:100%;height:auto;user-select:none;-webkit-user-drag:none}
.boxes{position:absolute;inset:0}
.box{position:absolute;border:1px solid rgba(190,190,190,.45);cursor:crosshair}
.box.t{border:2px solid var(--c);cursor:pointer}
.box.s{border-style:dashed}
.box:hover,.box.hl{background:color-mix(in srgb,var(--c,#bbb) 22%,transparent);outline:2px solid var(--c,#fff);outline-offset:1px;z-index:5}
.box.sel{outline:3px solid #fff;box-shadow:0 0 0 5px var(--c,#fff),0 0 24px var(--c,#fff);z-index:6}
.mode-off .box{display:none}.mode-tpl .box:not(.t){display:none}.nosample .box.s{display:none}.noloader .box.l{display:none}
[data-k=button]{--c:#ffd21f}[data-k=tab]{--c:#ff8a3d}[data-k=toggle]{--c:#c39bff}[data-k=popup]{--c:#ff5d73}[data-k=slot]{--c:#4fe3a7}
[data-k=gauge]{--c:#8de05a}[data-k=currency]{--c:#f7e36b}[data-k=reddot]{--c:#ff3b3b}[data-k=icon]{--c:#5ea8ff}[data-k=listcell]{--c:#3dd6c4}
[data-k=textstyle]{--c:#e7a6ff}[data-k=decor]{--c:#b8ae94}[data-k=atom]{--c:#ff4fb8}[data-k=composite]{--c:#35d0f0}
.side{display:flex;flex-direction:column;border-left:1px solid var(--line);min-height:0;max-height:calc(100vh - 202px)}
.side .info{padding:12px;border-bottom:1px solid var(--line);min-height:96px}
.side .info .nm{font-weight:700;font-size:15px;overflow-wrap:anywhere}.side .info .p{font:11px var(--mono);color:var(--mut);overflow-wrap:anywhere;margin-top:4px}
.side .info .go{display:inline-block;margin-top:8px;padding:5px 12px;background:var(--acc);color:var(--ink);font:700 14px var(--disp);text-decoration:none;letter-spacing:.5px;text-transform:uppercase}
.side .tf{padding:8px;border-bottom:1px solid var(--line);display:flex;gap:6px}
.side .tf input{flex:1;font:12px var(--body);padding:5px 7px;background:var(--bg2);color:var(--fg);border:1px solid var(--line)}
.vtree{overflow:auto;flex:1;padding:4px 0;font:12px/1.15 var(--body)}
.vtree div{padding:3px 8px 3px calc(8px + var(--d)*12px);white-space:nowrap;cursor:pointer;border-left:3px solid transparent;overflow:hidden;text-overflow:ellipsis}
.vtree div:hover,.vtree div.hl{background:var(--panel2);border-left-color:var(--c,var(--mut))}
.vtree div.sel{background:color-mix(in srgb,var(--acc) 22%,transparent);border-left-color:var(--acc)}
.vtree div.t{font-weight:700}.vtree div.t::before{content:"";display:inline-block;width:8px;height:8px;margin-right:6px;border:2px solid var(--c);vertical-align:0}
.vtree div.s{color:var(--mut);font-style:italic}.vtree div.z{color:var(--mut)}
.tip{position:fixed;z-index:100;pointer-events:none;background:var(--ink);color:#eeeadf;border:1px solid var(--c,var(--acc));padding:6px 9px;
font:12px/1.4 var(--body);max-width:360px;box-shadow:var(--shadow);display:none}
.tip b{color:var(--c,var(--acc));font:700 15px var(--disp);letter-spacing:.4px}.tip .k{font:10px var(--mono);color:#9b978a}
/* ---------- 템플릿 상세 */
.hero{display:grid;grid-template-columns:1fr auto;gap:16px;align-items:end}
.facts{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.ovr{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.ovr .mono{overflow-wrap:anywhere}.ovr .card h3{margin:0 0 6px;font:700 16px var(--disp);letter-spacing:.5px;text-transform:uppercase}
.stack{display:flex;height:18px;border:1px solid var(--line);overflow:hidden;margin:6px 0}
.stack i{display:block;height:100%}
.legend2{display:flex;flex-wrap:wrap;gap:8px;font:11px var(--mono);color:var(--mut)}.legend2 i{display:inline-block;width:9px;height:9px;margin-right:4px}
.badges{display:flex;gap:10px;flex-wrap:wrap}.badges .b{padding:8px 14px;background:var(--panel);border:1px solid var(--line)}
.badges .b b{display:block;font:700 26px/1 var(--disp)}.badges .b span{font-size:11px;color:var(--mut)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chips a{padding:3px 9px;background:var(--panel);border:1px solid var(--line);text-decoration:none;font-size:12px}.chips a:hover{border-color:var(--acc)}
"""

JS = r"""
(function(){
'use strict';
var root=document.documentElement;
function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
function sstore(k,v){try{if(v===undefined)return sessionStorage.getItem(k);sessionStorage.setItem(k,v)}catch(e){return null}}
var th=store('uiaudit-theme');if(th)root.setAttribute('data-theme',th);
document.addEventListener('DOMContentLoaded',function(){
  var tb=document.querySelector('.themebtn');
  if(tb)tb.addEventListener('click',function(){
    var cur=root.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
    var nx=cur==='light'?'dark':'light';root.setAttribute('data-theme',nx);store('uiaudit-theme',nx)});
  crumbs();gallery();apps();viewers();
  document.addEventListener('click',function(e){var b=e.target.closest('button.cp');if(!b)return;
    var t=b.getAttribute('data-id');try{navigator.clipboard.writeText(t);b.textContent='복사됨';setTimeout(function(){b.textContent=t},900)}catch(x){}});
});

/* 탐색 경로: 정적 기본 경로 + 이 탭에서 박스·카드를 눌러 내려온 경로(sessionStorage) */
function crumbs(){
  var el=document.querySelector('.crumbs');if(!el)return;
  var base=JSON.parse(el.getAttribute('data-base')||'[]'),me={t:el.getAttribute('data-title'),h:location.pathname};
  var trail=[];try{trail=JSON.parse(sstore('uiaudit-trail')||'[]')}catch(e){}
  var ref=sstore('uiaudit-from')||'';  /* file:// 에서는 document.referrer 가 비므로 떠나는 페이지가 직접 남긴다 */
  addEventListener('pagehide',function(){sstore('uiaudit-from',location.pathname)});
  var at=trail.findIndex(function(x){return x.h===me.h});
  if(at>=0)trail=trail.slice(0,at+1);
  else if(trail.length&&trail[trail.length-1].h===ref&&ref)trail.push(me);
  else trail=[];
  if(trail.length<2)trail=[];
  sstore('uiaudit-trail',JSON.stringify(trail.length?trail:[me]));
  var html='';
  if(trail.length){trail.forEach(function(x,i){html+=(i?'<i>›</i>':'')+(i===trail.length-1?'<span>'+esc(x.t)+'</span>':'<a href="'+x.h+'">'+esc(x.t)+'</a>')})}
  else{base.forEach(function(x){html+='<a href="'+x[1]+'">'+esc(x[0])+'</a><i>›</i>'});html+='<span>'+esc(me.t)+'</span>'}
  el.innerHTML=html;
}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}

/* 갤러리: 필터·검색·정렬·카드/표 전환 */
function gallery(){
  var g=document.querySelector('[data-gallery]');if(!g)return;
  var cards=[].slice.call(g.querySelectorAll('[data-name]')),rows=[].slice.call(document.querySelectorAll('tr[data-name]'));
  var f=[].slice.call(document.querySelectorAll('[data-f]')),cnt=document.getElementById('cnt');
  function ok(el,v){return(!v.tier||el.dataset.tier===v.tier)&&(!v.folder||el.dataset.folder===v.folder)&&(!v.kind||el.dataset.kind===v.kind)
    &&(!v.q||el.dataset.name.indexOf(v.q)>=0)&&(!v.used||(v.used==='0'?+el.dataset.usage===0:+el.dataset.usage>=+v.used))}
  function go(){
    var v={};f.forEach(function(x){v[x.getAttribute('data-f')]=x.value.toLowerCase()});var n=0;
    var sort=v.sort||'usage';
    cards.sort(function(a,b){return sort==='name'?a.dataset.name.localeCompare(b.dataset.name):(+b.dataset[sort]-+a.dataset[sort])||a.dataset.name.localeCompare(b.dataset.name)});
    cards.forEach(function(c,i){var s=ok(c,v);c.classList.toggle('hidden',!s);g.appendChild(c);if(s){n++;c.style.setProperty('--i',Math.min(n,40))}});
    rows.forEach(function(r){r.classList.toggle('hidden',!ok(r,v))});
    if(cnt)cnt.textContent=n;
  }
  f.forEach(function(x){x.addEventListener('input',go)});
  document.querySelectorAll('[data-view]').forEach(function(b){b.addEventListener('click',function(){
    document.querySelectorAll('[data-view]').forEach(function(x){x.classList.toggle('on',x===b)});
    var t=b.getAttribute('data-view');g.classList.toggle('hidden',t!=='cards');document.getElementById('tview').classList.toggle('hidden',t!=='table');
    store('uiaudit-view',t)})});
  var v0=store('uiaudit-view');if(v0==='table'){var b=document.querySelector('[data-view=table]');if(b)b.click()}
  go();
}

/* 앱 화면: 아이콘을 누르면 그 앱의 흐름을 펼친다(#app-<이름>) */
function apps(){
  var btns=[].slice.call(document.querySelectorAll('.app[data-app]'));if(!btns.length)return;
  function show(id){
    var found=false;
    document.querySelectorAll('.flowpane').forEach(function(p){var s=p.id==='pane-'+id;p.classList.toggle('hidden',!s);found=found||s});
    btns.forEach(function(b){b.classList.toggle('on',b.dataset.app===id)});
    return found;
  }
  btns.forEach(function(b){b.addEventListener('click',function(){show(b.dataset.app);history.replaceState(null,'','#app-'+b.dataset.app)})});
  var h=location.hash.replace('#app-','');if(!h||!show(h))show(btns[0].dataset.app);
}

/* 배치 맵 뷰어: 렌더 이미지 + 박스 오버레이 + 계층 트리 */
function viewers(){document.querySelectorAll('.viewer[data-layout]').forEach(viewer)}
/* 컨테이너 안에서만 스크롤(scrollIntoView 는 페이지까지 움직인다) */
function reveal(box,el,both){var c=box.getBoundingClientRect(),r=el.getBoundingClientRect();
  if(r.top<c.top||r.bottom>c.bottom)box.scrollTop+=r.top-c.top-(both?c.height/2-r.height/2:8);
  if(both&&(r.left<c.left||r.right>c.right))box.scrollLeft+=r.left-c.left-c.width/2+r.width/2}
function viewer(v){
  var D=JSON.parse(document.getElementById(v.getAttribute('data-layout')).textContent);
  var stage=v.querySelector('.stage'),wrap=v.querySelector('.stagewrap'),bx=v.querySelector('.boxes'),tree=v.querySelector('.vtree');
  var info=v.querySelector('.info'),tip=document.querySelector('.tip')||document.body.appendChild(Object.assign(document.createElement('div'),{className:'tip'}));
  var zl=v.querySelector('.z'),zoom=1,sel=-1,fit=1;
  var boxes=[],rows=[];
  /* 큰 박스부터 그려 작은 박스가 위에 오게 */
  var order=D.b.map(function(b,i){return i}).sort(function(a,b){return D.b[b][2]*D.b[b][3]-D.b[a][2]*D.b[a][3]});
  var frag=document.createDocumentFragment();
  order.forEach(function(i){
    var b=D.b[i],t=b[7]>=0?D.t[b[7]]:null,el=document.createElement('div');
    if(b[2]<=0||b[3]<=0){boxes[i]=null;return}
    el.className='box'+(t?' t':'')+(b[5]&1?' s':'')+(b[5]&2?' l':'');
    if(t)el.setAttribute('data-k',t[2]);
    el.style.cssText='left:'+(100*b[0]/D.w)+'%;top:'+(100*b[1]/D.h)+'%;width:'+(100*b[2]/D.w)+'%;height:'+(100*b[3]/D.h)+'%';
    el.dataset.i=i;boxes[i]=el;frag.appendChild(el)});
  bx.appendChild(frag);
  var tf=document.createDocumentFragment();
  D.b.forEach(function(b,i){
    var t=b[7]>=0?D.t[b[7]]:null,r=document.createElement('div');
    r.className=(t?'t':'')+(b[5]&1?' s':'')+(b[2]<=0||b[3]<=0?' z':'');r.style.setProperty('--d',b[4]);
    if(t)r.setAttribute('data-k',t[2]);
    r.textContent=b[6]+(b[5]&1?'  · 예시':'')+(b[5]&2?'  · 로더':'');r.dataset.i=i;r.title=b[6];rows[i]=r;tf.appendChild(r)});
  tree.appendChild(tf);
  function desc(i){var b=D.b[i],t=b[7]>=0?D.t[b[7]]:null;
    return {b:b,t:t,html:'<b>'+esc(t?t[1]:b[6])+'</b>'+(t?' <span class="k">'+esc(t[2])+' · '+esc(t[3])+'</span>':'')+
      '<div class="k">'+esc(b[6])+' · '+Math.round(b[2]/D.s)+'×'+Math.round(b[3]/D.s)+'px'+(b[5]&1?' · 예시 아이템':'')+(b[5]&2?' · ResourcesLoader':'')+'</div>'}}
  function hl(i,on){if(boxes[i])boxes[i].classList.toggle('hl',on);if(rows[i])rows[i].classList.toggle('hl',on)}
  function pick(i,scrollStage){
    if(sel>=0){if(boxes[sel])boxes[sel].classList.remove('sel');if(rows[sel])rows[sel].classList.remove('sel')}
    sel=i;var d=desc(i);if(boxes[i])boxes[i].classList.add('sel');rows[i].classList.add('sel');
    reveal(tree,rows[i]);
    if(scrollStage&&boxes[i])reveal(wrap,boxes[i],true);
    var p=[],dep=D.b[i][4];for(var j=i;j>=0&&dep>=0;j--){if(D.b[j][4]===dep){p.unshift(D.b[j][6]);dep--}}
    info.innerHTML='<div class="nm">'+esc(d.t?d.t[1]:d.b[6])+'</div>'+(d.t?'<div class="facts"><span class="tag y">'+esc(d.t[2])+'</span><span class="tag">'+esc(d.t[3])+'</span></div>':'')+
      '<div class="p">'+esc(p.join(' / '))+'</div>'+(d.t?'<a class="go" href="'+D.base+esc(d.t[0])+'.html">템플릿 열기 ›</a>':'');
    info.style.setProperty('--c','');
  }
  bx.addEventListener('mouseover',function(e){var el=e.target.closest('.box');if(!el)return;var i=+el.dataset.i,d=desc(i);
    hl(i,true);tip.innerHTML=d.html;tip.style.display='block';tip.style.setProperty('--c',getComputedStyle(el).getPropertyValue('--c')||'');
    if(rows[i])reveal(tree,rows[i])});
  bx.addEventListener('mouseout',function(e){var el=e.target.closest('.box');if(!el)return;hl(+el.dataset.i,false);tip.style.display='none'});
  bx.addEventListener('mousemove',function(e){tip.style.left=Math.min(e.clientX+14,innerWidth-370)+'px';tip.style.top=(e.clientY+16)+'px'});
  bx.addEventListener('click',function(e){var el=e.target.closest('.box');if(!el)return;var i=+el.dataset.i,b=D.b[i];
    if(b[7]>=0&&!(e.shiftKey||e.altKey)){location.href=D.base+D.t[b[7]][0]+'.html';return}
    pick(i,false)});
  tree.addEventListener('mouseover',function(e){var r=e.target.closest('[data-i]');if(r)hl(+r.dataset.i,true)});
  tree.addEventListener('mouseout',function(e){var r=e.target.closest('[data-i]');if(r)hl(+r.dataset.i,false)});
  tree.addEventListener('click',function(e){var r=e.target.closest('[data-i]');if(r)pick(+r.dataset.i,true)});
  var q=v.querySelector('.tf input');
  if(q)q.addEventListener('input',function(){var s=q.value.toLowerCase();rows.forEach(function(r,i){
    var t=D.b[i][7]>=0?D.t[D.b[i][7]][1]:'';r.classList.toggle('hidden',!!s&&(D.b[i][6]+' '+t).toLowerCase().indexOf(s)<0)})});
  function setZoom(z){zoom=Math.max(.25,Math.min(6,z));stage.style.width=(D.w*fit*zoom)+'px';zl.textContent=Math.round(zoom*100)+'%'}
  function refit(){var cw=wrap.clientWidth-36,ch=wrap.clientHeight-36;fit=Math.min(cw/D.w,(ch>100?ch:9999)/D.h,D.kind==='template'?2.2:9);setZoom(1)}
  v.querySelectorAll('[data-z]').forEach(function(b){b.addEventListener('click',function(){var z=b.getAttribute('data-z');
    if(z==='fit')setZoom(1);else setZoom(zoom*(+z))})});
  wrap.addEventListener('wheel',function(e){if(!e.ctrlKey)return;e.preventDefault();setZoom(zoom*(e.deltaY<0?1.15:1/1.15))},{passive:false});
  v.querySelectorAll('[data-mode]').forEach(function(b){b.addEventListener('click',function(){
    v.querySelectorAll('[data-mode]').forEach(function(x){x.classList.toggle('on',x===b)});
    bx.classList.remove('mode-tpl','mode-off','mode-all');bx.classList.add('mode-'+b.getAttribute('data-mode'));store('uiaudit-mode',b.getAttribute('data-mode'))})});
  var m0=store('uiaudit-mode');var mb=v.querySelector('[data-mode='+(m0||'tpl')+']');if(mb)mb.click();
  v.querySelectorAll('[data-opt]').forEach(function(c){c.addEventListener('change',function(){bx.classList.toggle(c.getAttribute('data-opt'),!c.checked)})});
  var img=stage.querySelector('img');if(img.complete)refit();else img.addEventListener('load',refit);refit();
  addEventListener('resize',function(){var z=zoom;refit();setZoom(z)});
}
})();
"""


def css():
    """CSS 에 설정 폰트(@font-face · --disp 맨 앞 family)를 채운다."""
    fam = _FONT.get("family")
    faces = "".join('@font-face{font-family:"%s";src:url(vendor/%s) format("opentype");font-weight:%d}\n'
                    % (fam, f["name"], f["weight"]) for f in _FONT.get("files", []))
    return CSS.replace("@@FONT_FACES@@\n", faces).replace("@@DISP_FAMILY@@", '"%s",' % fam if fam else "")


def write_assets(out):
    """catalog/assets/ 에 스타일·스크립트를 쓰고 폰트를 복사한다(최종 이름으로 바로 — 스키마 검증 대상이 아님)."""
    d = os.path.join(out, "assets")
    os.makedirs(os.path.join(d, "vendor"), exist_ok=True)
    for name, text in (("explorer.css", css()), ("explorer.js", JS)):
        with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text.lstrip())
    for name, src in FONTS.items():
        full = os.path.join(C.unity_root(), src)
        if os.path.exists(full):
            shutil.copyfile(full, os.path.join(d, "vendor", name))
