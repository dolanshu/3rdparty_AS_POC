# Copyright 2026 Dolan Shu <dolan.d.shu@gmail.com>.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Console process — telecom-operations UI as plain HTML/CSS/JS (ADR-0002, AGENT.md 4.4).

The console is a separate process that serves a dark operations console. The browser-side
JavaScript fetches data from the AS internal API and connects to its WebSocket for live
updates. No third-party front-end libraries; no build step.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

__all__ = ["CONSOLE_PAGE", "create_app", "main"]

DEFAULT_AS_API_URL = "http://127.0.0.1:8080"

# All CSS inline in <style>, all JS inline in <script> — no external refs (4.4, NF-010).
# The __AS_API_URL__ token is replaced at request time with the configured AS API URL.
CONSOLE_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>3rd-party AS Console</title><style>
:root{--bg:#0d1117;--panel:#161b22;--p2:#1c2330;--bd:#30363d;--tx:#c9d1d9;--mut:#8b949e;--acc:#58a6ff;--in:#3fb950;--out:#f0883e;--int:#8b949e;--rule:#d2a8ff;--err:#f85149;--warn:#d29922}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--tx);font-family:"SF Mono","Cascadia Code","Consolas",monospace;font-size:13px;overflow:hidden}
.sb{display:flex;align-items:center;gap:16px;padding:6px 14px;background:var(--panel);border-bottom:1px solid var(--bd);height:38px}
.si{display:flex;align-items:center;gap:5px}.sl{color:var(--mut);font-size:11px;text-transform:uppercase}.sv{font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mut)}.dot.ok{background:var(--in)}.dot.er{background:var(--err)}.sp{flex:1}
.lay{display:flex;height:calc(100vh - 38px)}
.nav{width:170px;background:var(--panel);border-right:1px solid var(--bd);padding:8px 0;flex-shrink:0}
.nav button{display:block;width:100%;text-align:left;padding:9px 14px;border:none;background:0;color:var(--mut);font:inherit;cursor:pointer;border-left:3px solid transparent}
.nav button:hover{color:var(--tx);background:var(--p2)}.nav button.act{color:var(--acc);border-left-color:var(--acc);background:var(--p2)}
.mp{flex:1;overflow:auto;padding:14px}.vw{display:none;height:100%}.vw.act{display:block}
.tl{display:flex;gap:10px;height:100%}.tlp{width:290px;border:1px solid var(--bd);border-radius:6px;background:var(--panel);display:flex;flex-direction:column}
.th{padding:7px 9px;border-bottom:1px solid var(--bd);display:flex;gap:6px}.tf{flex:1;background:var(--bg);border:1px solid var(--bd);border-radius:4px;padding:3px 6px;color:var(--tx);font:inherit;font-size:12px}
.tlist{flex:1;overflow-y:auto}.ti{padding:6px 9px;border-bottom:1px solid var(--bd);cursor:pointer}.ti:hover{background:var(--p2)}.ti.sel{background:var(--p2);border-left:3px solid var(--acc)}
.ti .cid{color:var(--acc);font-size:12px;word-break:break-all}.ti .ci{color:var(--mut);font-size:11px;margin-top:2px}
.tdp{flex:1;border:1px solid var(--bd);border-radius:6px;background:var(--panel);display:flex;flex-direction:column;min-width:0}
.tdh{padding:7px 11px;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}
.te{flex:1;overflow-y:auto;padding:7px 11px}
.er{display:flex;align-items:flex-start;gap:7px;padding:4px 0;border-bottom:1px solid var(--bd)}
.ed{width:20px;text-align:center;font-weight:700;flex-shrink:0}.ed.in{color:var(--in)}.ed.out{color:var(--out)}.ed.internal{color:var(--int)}
.eb{flex:1;min-width:0}.em{display:inline-block;background:var(--p2);border:1px solid var(--bd);border-radius:3px;padding:0 4px;font-weight:600}
.et{color:var(--mut);font-size:11px}.ep{color:var(--mut);font-size:11px}
.erl{display:inline-block;background:rgba(210,168,255,.12);border:1px solid var(--rule);border-radius:3px;padding:0 4px;color:var(--rule);font-size:11px;margin-left:3px}
.ea{margin-top:3px;background:var(--bg);border:1px solid var(--bd);border-radius:4px;padding:5px 7px;font-size:11px;display:none}.ea.vis{display:block}
.er.ck{cursor:pointer}.er.ck:hover{background:var(--p2)}
.st{font-size:14px;font-weight:600;margin-bottom:8px;color:var(--acc)}
table{width:100%;border-collapse:collapse}th,td{padding:5px 9px;text-align:left;border-bottom:1px solid var(--bd)}th{color:var(--mut);font-size:11px;text-transform:uppercase}td{font-size:12px;word-break:break-all}
.tag{display:inline-block;background:var(--p2);border:1px solid var(--bd);border-radius:3px;padding:0 4px;font-size:11px;margin:1px}.tag.en{color:var(--in);border-color:var(--in)}.tag.di{color:var(--err);border-color:var(--err)}.tag.rt{color:var(--acc)}.tag.rj{color:var(--warn)}
.card{border:1px solid var(--bd);border-radius:6px;background:var(--panel);padding:11px;margin-bottom:12px;overflow-x:auto}
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}.sc{border:1px solid var(--bd);border-radius:6px;background:var(--panel);padding:11px}.sc .n{font-size:22px;font-weight:700}.sc .l{color:var(--mut);font-size:11px;text-transform:uppercase}
.bc{margin-top:6px}.br{display:flex;align-items:center;gap:7px;margin:3px 0}.bl{width:80px;color:var(--mut);font-size:11px}.bt{flex:1;height:14px;background:var(--bg);border-radius:3px;overflow:hidden}.bf{height:100%;border-radius:3px}.bf.g{background:var(--in)}.bf.o{background:var(--out)}.bf.r{background:var(--err)}.bf.p{background:var(--rule)}.bf.gr{background:var(--int)}.bf.a{background:var(--acc)}.bv{width:28px;text-align:right;font-size:11px}
.cr{display:flex;gap:7px;padding:3px 0;border-bottom:1px solid var(--bd)}.ck{width:160px;color:var(--mut)}.cv{flex:1;word-break:break-all}
.empty{color:var(--mut);padding:18px;text-align:center}.ws{font-size:11px;color:var(--mut)}.ws.live{color:var(--in)}.ws.down{color:var(--err)}
</style></head><body>
<div class="sb" id="sb">
<div class="si"><span class="dot" id="aDot"></span><span class="sv" id="aSt">connecting</span></div>
<div class="si"><span class="sl">ver</span><span class="sv" id="aVer">-</span></div>
<div class="si"><span class="sl">uptime</span><span class="sv" id="aUp">-</span></div>
<div class="si"><span class="sl">calls</span><span class="sv" id="aCal">0</span></div>
<div class="si"><span class="sl">peers</span><span class="sv" id="aPeer">-</span></div>
<div class="sp"></div><div class="si ws" id="wsSt">offline</div>
</div>
<div class="lay">
<nav class="nav" id="nav">
<button data-v="call-trace" class="act">Call Trace</button>
<button data-v="rules">Rules</button>
<button data-v="screening">Screening</button>
<button data-v="configuration">Configuration</button>
<button data-v="statistics">Statistics</button>
<button data-v="about">About</button>
</nav>
<main class="mp">
<div class="vw act" id="vw-call-trace"><div class="tl">
<div class="tlp"><div class="th"><input class="tf" id="filt" placeholder="filter Call-ID..."></div><div class="tlist" id="tlist"><div class="empty">no calls yet</div></div></div>
<div class="tdp"><div class="tdh"><span id="dt">select a call</span><span id="topo"></span></div><div class="te" id="te"><div class="empty">select a call to view its message flow</div></div></div>
</div></div>
<div class="vw" id="vw-rules">
<div class="st">Next Hops</div><div class="card"><table id="nhT"><thead><tr><th>Name</th><th>Address</th><th>Port</th><th>Pri</th><th>Description</th></tr></thead><tbody></tbody></table></div>
<div class="st">Routing Rules</div><div class="card"><table id="rlT"><thead><tr><th>Rule ID</th><th>Pri</th><th>Enabled</th><th>Description</th><th>Match</th><th>Action</th></tr></thead><tbody></tbody></table></div>
</div>
<div class="vw" id="vw-screening">
<div class="st">Caller Screening (anti-fraud AS)</div><div class="card" id="scrC"><div class="empty">loading...</div></div>
<div class="st">Block List</div><div class="card"><table id="blT"><thead><tr><th>Entry</th><th>Number / prefix</th><th>Reason</th></tr></thead><tbody></tbody></table></div>
<div class="st">Allow List</div><div class="card"><table id="alT"><thead><tr><th>Entry</th><th>Number / prefix</th><th>Reason</th></tr></thead><tbody></tbody></table></div>
</div>
<div class="vw" id="vw-configuration"><div class="st">AS Configuration</div><div class="card" id="cfgC"><div class="empty">loading...</div></div></div>
<div class="vw" id="vw-statistics">
<div class="sg" id="sg"></div>
<div class="card" style="margin-top:12px"><div class="st">Calls by Disposition</div><div class="bc" id="dispC"></div></div>
<div class="card"><div class="st">Rule Hits</div><div class="bc" id="rhC"></div></div>
<div class="card"><div class="st">Verdicts and Screening Signals</div><div class="bc" id="vcC"></div></div>
<div class="card"><div class="st">Errors by Code</div><table id="errT"><thead><tr><th>Code</th><th>Count</th></tr></thead><tbody></tbody></table></div>
</div>
<div class="vw about" id="vw-about"><div class="st">3rd-party Application Server POC</div>
<p style="margin-bottom:8px">A PoC of a third-party SIP Application Server (B2BUA) reached over a SIP trunk from the Service-SBC.</p>
<p style="margin-bottom:8px">Console: <span style="color:var(--acc)">FastAPI + plain HTML/CSS/JS</span> — no third-party front-end libraries. The console runs as a separate process (ADR-0002) and reaches the AS at <span style="color:var(--acc)" id="apiUrl">-</span>.</p>
<p>See <span style="color:var(--acc)">docs/</span> for architecture, operations and acceptance docs.</p>
</div>
</main></div>
<script>
"use strict";var A="__AS_API_URL__",W=A.replace(/^http/,"ws")+"/ws/events",cv="call-trace",tc=[],sel=null,rd=null,sd=null,md=null,hd=null,ws=null,wr=null;
function E(i){return document.getElementById(i)}function C(n){n.innerHTML=""}function ft(s){try{return new Date(s).toLocaleTimeString()}catch(e){return s}}
function esc(s){if(s===null||s===undefined)return"";return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
async function fh(){try{var r=await fetch(A+"/healthz");hd=await r.json();E("aSt").textContent=hd.status;
E("aDot").className="dot "+(hd.status==="ok"?"ok":"er");E("aVer").textContent=hd.version||"-";
E("aUp").textContent=Math.round(hd.uptime_seconds||0)+"s"}catch(e){E("aSt").textContent="unreachable";E("aDot").className="dot er"}}
async function fm(){try{var r=await fetch(A+"/api/v1/metrics");md=await r.json();E("aCal").textContent=md.calls_total||0;
var p=Object.entries(md.peer_status||{}).map(function(x){return x[0]+":"+x[1]}).join(", ");E("aPeer").textContent=p||"-";
if(cv==="statistics")rs()}catch(e){}}
async function ftr(){try{var r=await fetch(A+"/api/v1/traces");var d=await r.json();tc=d.calls||[];rtl()}catch(e){}}
function rtl(){var f=(E("filt").value||"").toLowerCase(),l=E("tlist");C(l);
var q=tc.filter(function(t){return!f||t.call_id.toLowerCase().indexOf(f)>=0});
if(!q.length){l.innerHTML='<div class="empty">no calls</div>';return}
q.forEach(function(t){var d=document.createElement("div");d.className="ti"+(t.call_id===sel?" sel":"");
var n=t.events?t.events.length:0,r=t.events?t.events.find(function(e){return e.rule_id}):null;
d.innerHTML='<div class="cid">'+esc(t.call_id)+'</div><div class="ci">'+n+" events"+(r?' &middot; <span style="color:var(--rule)">'+esc(r.rule_id)+"</span>":"")+"</div>";
d.onclick=function(){sc(t.call_id)};l.appendChild(d)})}
function sc(id){sel=id;rtl();E("dt").textContent=id;var t=tc.find(function(x){return x.call_id===id});
if(!t){E("te").innerHTML='<div class="empty">trace not found</div>';return}rte(t.events||[]);utopo(t)}
function rte(ev){var c=E("te");C(c);if(!ev.length){c.innerHTML='<div class="empty">no events</div>';return}
ev.forEach(function(e){var dc=e.direction==="in"?"\u2190":e.direction==="out"?"\u2192":"\u2022";
var r=document.createElement("div");var ha=e.attributes&&Object.keys(e.attributes).length>0;
r.className="er"+(ha?" ck":"");r.innerHTML='<div class="ed '+esc(e.direction)+'">'+dc+'</div><div class="eb">'+
'<span class="em">'+esc(e.method)+"</span> "+'<span>'+esc(e.summary)+"</span>"+
(e.rule_id?'<span class="erl">'+esc(e.rule_id)+"</span>":"")+
' <span class="et">'+ft(e.timestamp)+'</span> <span class="ep">'+esc(e.peer)+"</span>"+
(ha?'<dl class="ea"></dl>':"")+"</div>";
if(ha){r.onclick=function(){var dl=r.querySelector(".ea");if(!dl.innerHTML){Object.entries(e.attributes).forEach(function(kv){
var dt=document.createElement("dt");dt.textContent=kv[0]+":";var dd=document.createElement("dd");
dd.textContent=typeof kv[1]==="object"?JSON.stringify(kv[1]):String(kv[1]);dl.appendChild(dt);dl.appendChild(dd)})}
dl.classList.toggle("vis")}}c.appendChild(r)})}
function utopo(t){var b=E("topo");var ho=t.events&&t.events.some(function(e){return e.direction==="out"});
var rv=t.events?t.events.find(function(e){return e.rule_id}):null;
var ac=ho?"var(--in)":"var(--mut)",lc=ho?"var(--acc)":"var(--bd)";
var la=ho?' stroke-dasharray="4 2"><animate attributeName="stroke-dashoffset" from="0" to="-12" dur=".5s" repeatCount="indefinite"/></line>':"/>";
b.innerHTML='<svg width="210" height="46" viewBox="0 0 210 46" xmlns="http://www.w3.org/2000/svg">'+
'<rect x="2" y="11" width="56" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/><text x="30" y="27" text-anchor="middle" fill="var(--mut)" font-size="10">S-SBC</text>'+
'<line x1="58" y1="23" x2="104" y2="23" stroke="'+lc+'" stroke-width="2"'+la+
'<rect x="104" y="11" width="40" height="24" rx="4" fill="var(--p2)" stroke="'+ac+'"/><text x="124" y="27" text-anchor="middle" fill="'+ac+'" font-size="10">AS</text>'+
'<line x1="144" y1="23" x2="188" y2="23" stroke="'+lc+'" stroke-width="2"'+la+
'<rect x="188" y="11" width="20" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/><text x="196" y="27" text-anchor="middle" fill="var(--mut)" font-size="8">NH</text>'+
(rv?'<text x="106" y="9" fill="var(--rule)" font-size="9">'+esc(rv.rule_id)+"</text>":"")+"</svg>"}
async function fr(){try{var r=await fetch(A+"/api/v1/rules");rd=await r.json();
if(cv==="rules")rr();if(cv==="configuration")rcfg()}catch(e){}}
function rr(){if(!rd)return;var h=E("nhT").querySelector("tbody");C(h);
(rd.next_hops||[]).forEach(function(x){h.innerHTML+="<tr><td>"+esc(x.name)+"</td><td>"+esc(x.address)+"</td><td>"+x.port+
"</td><td>"+x.priority+"</td><td>"+esc(x.description)+"</td></tr>"});
var t=E("rlT").querySelector("tbody");C(t);
(rd.rules||[]).forEach(function(r){var m=r.match||{},ms=[];
if(m.called_prefixes&&m.called_prefixes.length)ms.push("prefix:"+m.called_prefixes.join(","));
if(m.called_numbers&&m.called_numbers.length)ms.push("exact:"+m.called_numbers.join(","));
if(m.number_format)ms.push("fmt:"+m.number_format);
var a=r.action||{},as='<span class="tag '+(a.kind==="route"?"rt":"rj")+'">'+a.kind+"</span>";
if(a.kind==="route"){as+=" hops:"+(a.next_hops||[]).join(",");if(a.translate){as+=" "+(a.translate.strip_prefix?"-"+a.translate.strip_prefix:"")+
(a.translate.prepend?"+"+a.translate.prepend:"")}}else{as+=" "+a.status}
t.innerHTML+="<tr><td>"+esc(r.rule_id)+"</td><td>"+r.priority+'</td><td><span class="tag '+(r.enabled?"en":"di")+'">'+
(r.enabled?"on":"off")+"</span></td><td>"+esc(r.description)+"</td><td>"+esc(ms.join(" | "))+"</td><td>"+as+"</td></tr>"})}
async function fs(){try{var r=await fetch(A+"/api/v1/screening");sd=await r.json();
if(cv==="screening")rsd();if(cv==="configuration")rcfg()}catch(e){}}
function rl(id,rows){var t=E(id);if(!t)return;var b=t.querySelector("tbody");C(b);
if(!rows.length){b.innerHTML='<tr><td colspan="3" class="empty">no entries</td></tr>';return}
rows.forEach(function(x){b.innerHTML+="<tr><td>"+esc(x.entry_id)+"</td><td>"+esc(x.value)+"</td><td>"+esc(x.reason)+"</td></tr>"})}
function rsd(){if(!sd)return;var c=E("scrC");if(!c)return;C(c);var w=sd.window||{},rp=sd.reputation||{};
[["data set",sd.name],["source",sd.source],["window (s)",w.seconds],["max calls / window",w.max_calls],
["reputation default",rp.default_score],["reject below",rp.reject_below],["reject penalty",rp.reject_penalty],
["half-life (s)",rp.half_life_seconds]
].forEach(function(r){c.innerHTML+='<div class="cr"><span class="ck">'+esc(r[0])+'</span><span class="cv">'+esc(String(r[1]))+"</span></div>"});
rl("blT",sd.block_list||[]);rl("alT",sd.allow_list||[])}
function rcfg(){var c=E("cfgC");if(!c)return;if(!hd){c.innerHTML='<div class="empty">loading...</div>';return}C(c);
var rows=null;
if(rd){rows=[["AS version",hd.version||"-"],["AS status",hd.status||"-"],["Uptime (s)",Math.round(hd.uptime_seconds||0)],
["Rule set loaded",hd.rule_set_loaded],["Rule set name",rd.name||"-"],["Rule set source",rd.source||"-"],
["Rule set version",rd.version||"-"],["Rules (total)",(rd.rules||[]).length],["Next hops (total)",(rd.next_hops||[]).length]]}
else if(sd){rows=[["AS version",hd.version||"-"],["AS status",hd.status||"-"],["Uptime (s)",Math.round(hd.uptime_seconds||0)],
["Screening data loaded",hd.screening_data_loaded],["Data set",sd.name||"-"],["Data source",sd.source||"-"],
["Block list (total)",(sd.block_list||[]).length],["Allow list (total)",(sd.allow_list||[]).length],
["Window (s)",(sd.window||{}).seconds],["Max calls / window",(sd.window||{}).max_calls]]}
if(!rows){c.innerHTML='<div class="empty">no configuration available</div>';return}
rows.forEach(function(r){c.innerHTML+='<div class="cr"><span class="ck">'+esc(r[0])+'</span><span class="cv">'+esc(String(r[1]))+"</span></div>"})}
function rs(){if(!md)return;var g=E("sg");C(g);var cs=[["Total calls",md.calls_total||0]];
Object.entries(md.calls_by_disposition||{}).forEach(function(d){cs.push([d[0],d[1]])});
cs.forEach(function(c){g.innerHTML+='<div class="sc"><div class="n">'+c[1]+'</div><div class="l">'+esc(c[0])+"</div></div>"});
rbc("dispC",md.calls_by_disposition||{},{completed:"g",failed:"r",rejected:"o",no_match:"gr",abandoned:"gr"});
rbc("rhC",md.rule_hits||{});rbc("vcC",md.counters||{});var t=E("errT").querySelector("tbody");C(t);
var es=Object.entries(md.errors_by_code||{});if(!es.length){t.innerHTML='<tr><td colspan="2" class="empty">no errors</td></tr>'}
else{es.forEach(function(e){t.innerHTML+="<tr><td>"+esc(e[0])+"</td><td>"+e[1]+"</td></tr>"})}}
function rbc(id,d,cl){var c=E(id);C(c);var es=Object.entries(d);if(!es.length){c.innerHTML='<div class="empty">no data</div>';return}
var mx=Math.max.apply(null,es.map(function(e){return e[1]}));
es.forEach(function(e){var p=mx>0?Math.round(e[1]/mx*100):0;var cls=(cl&&cl[e[0]])||"a";
c.innerHTML+='<div class="br"><span class="bl">'+esc(e[0])+'</span><div class="bt"><div class="bf '+cls+'" style="width:'+p+'%"></div></div><span class="bv">'+e[1]+"</span></div>"})}
function sv(v){cv=v;document.querySelectorAll(".nav button").forEach(function(b){b.classList.toggle("act",b.dataset.v===v)});
document.querySelectorAll(".vw").forEach(function(w){w.classList.remove("act")});E("vw-"+v).classList.add("act");
if(v==="rules"){if(!rd)fr();else rr()}if(v==="screening"){if(!sd)fs();else rsd()}if(v==="configuration"){if(!rd)fr();if(!sd)fs();if(rd||sd)rcfg()}if(v==="statistics")rs();if(v==="call-trace")rtl()}
function cws(){try{ws=new WebSocket(W)}catch(e){ewso();return}
ws.onopen=function(){E("wsSt").textContent="live";E("wsSt").className="si ws live"};
ws.onmessage=function(m){try{var d=JSON.parse(m.data);if(d.type==="traces"&&d.traces){d.traces.forEach(function(t){
if(!tc.find(function(c){return c.call_id===t.call_id})){tc.unshift(t);if(tc.length>200)tc.pop()}});
if(cv==="call-trace")rtl();if(sel){var t=tc.find(function(c){return c.call_id===sel});if(t)rte(t.events||[])}}}catch(e){}};
ws.onclose=function(){ewso()};ws.onerror=function(){ws.close()}}
function ewso(){E("wsSt").textContent="offline";E("wsSt").className="si ws down";if(!wr){wr=setTimeout(function(){wr=null;cws()},3000)}}
E("apiUrl").textContent=A;document.querySelectorAll(".nav button").forEach(function(b){b.onclick=function(){sv(b.dataset.v)}});
E("filt").oninput=rtl;fh();fm();ftr();fr();fs();cws();setInterval(fh,3000);setInterval(fm,3000);setInterval(ftr,5000);setInterval(fs,5000);
</script></body></html>
"""


def create_app(*, as_api_url: str = DEFAULT_AS_API_URL) -> FastAPI:
    """Create the console application.

    Args:
        as_api_url: URL of the AS internal API the browser-side JavaScript calls.

    Returns:
        A FastAPI application with the console health endpoint and operations page.
    """
    app = FastAPI(title="3rd-party AS console", version="0.1.0")

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        """Report that the console process is alive."""
        return {"status": "ok", "component": "console"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the operations console page with the AS API URL injected."""
        return CONSOLE_PAGE.replace("__AS_API_URL__", as_api_url)

    return app


def main(argv: list[str] | None = None) -> int:
    """Run the console with uvicorn.

    Args:
        argv: Command line arguments; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="3rd-party AS console")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--as-api-url",
        default=os.environ.get("AS_INTERNAL_API_URL", DEFAULT_AS_API_URL),
        help="URL of the AS internal API (default: env AS_INTERNAL_API_URL or "
        "http://127.0.0.1:8080)",
    )
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(as_api_url=args.as_api_url)
    uvicorn.run(app, host=args.address, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
