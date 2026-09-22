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

"""Console process — Enhanced operations dashboard (Phase 3 P13, ADR-0011).

The console is a separate process serving a dark operations dashboard with
live call-count charts, state distribution, capacity gauge, dynamic SVG
topology and load-generator controls. Uses vendored Chart.js UMD bundle
served from ``/static/`` (ADR-0011, REQ-F-050).
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

__all__ = ["CONSOLE_PAGE", "create_app", "main"]

DEFAULT_AS_API_URL = "http://127.0.0.1:8080"
DEFAULT_LOAD_API_URL = "http://127.0.0.1:8765"

_STATIC_DIR = Path(__file__).parent / "static"

# P13 Enhanced Console: multi-panel CSS Grid layout with 3 Chart.js panels
# plus SVG topology + load generator controls.
# Tokens __AS_API_URL__ and __LOAD_API_URL__ are replaced at request time.
CONSOLE_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>3rd-party AS Console — Enhanced</title>
<script src="/static/chart.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--p2:#1c2330;--bd:#30363d;--tx:#c9d1d9;--mut:#8b949e;--acc:#58a6ff;--in:#3fb950;--out:#f0883e;--int:#8b949e;--rule:#d2a8ff;--err:#f85149;--warn:#d29922}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--tx);font-family:"SF Mono","Cascadia Code","Consolas",monospace;font-size:13px;overflow:hidden}

/* Status bar */
.sb{display:flex;align-items:center;gap:16px;padding:6px 14px;background:var(--panel);border-bottom:1px solid var(--bd);height:38px}
.si{display:flex;align-items:center;gap:5px}.sl{color:var(--mut);font-size:11px;text-transform:uppercase}.sv{font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mut)}.dot.ok{background:var(--in)}.dot.er{background:var(--err)}.sp{flex:1}
.ws{font-size:11px;color:var(--mut)}.ws.live{color:var(--in)}.ws.down{color:var(--err)}

/* Main grid: 3 columns — nav / centre / right */
.grid{display:grid;grid-template-columns:180px 1fr 320px;grid-template-rows:1fr 220px;height:calc(100vh - 38px);gap:0}
.nav{background:var(--panel);border-right:1px solid var(--bd);padding:8px 0;overflow-y:auto}
.nav button{display:block;width:100%;text-align:left;padding:9px 14px;border:none;background:0;color:var(--mut);font:inherit;cursor:pointer;border-left:3px solid transparent}
.nav button:hover{color:var(--tx);background:var(--p2)}.nav button.act{color:var(--acc);border-left-color:var(--acc);background:var(--p2)}
.ctl{margin-top:12px;padding:8px 14px;border-top:1px solid var(--bd)}
.ctl .h{color:var(--mut);font-size:11px;text-transform:uppercase;margin-bottom:6px}

/* Centre panel — charts stacked */
.centre{display:flex;flex-direction:column;overflow:hidden;border-right:1px solid var(--bd)}
.chart-card{flex:1;min-height:0;padding:10px 14px;border-bottom:1px solid var(--bd);display:flex;flex-direction:column}
.chart-card:last-child{border-bottom:none}
.chart-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.chart-h .t{font-size:12px;font-weight:600;color:var(--acc)}.chart-h .v{font-size:11px;color:var(--mut)}
.chart-wrap{flex:1;min-height:0;position:relative}

/* Right panel — doughnut + topology */
.right{display:flex;flex-direction:column;overflow:hidden}
.sm-card{padding:10px 14px;border-bottom:1px solid var(--bd);display:flex;flex-direction:column}
.sm-card.t{height:55%}
.sm-card.g{height:45%}
.sm-card:last-child{border-bottom:none}
.topo-wrap{flex:1;display:flex;align-items:center;justify-content:center}
.topo-wrap svg{width:100%;height:100%;max-height:140px}

/* Bottom — trace */
.trace{grid-column:1 / -1;border-top:1px solid var(--bd);background:var(--panel);display:flex;flex-direction:column;min-height:0}
.trace-h{padding:6px 14px;border-bottom:1px solid var(--bd);display:flex;gap:10px;align-items:center}
.trace-h .t{font-weight:600;color:var(--acc);font-size:12px}
.trace-h .tf{flex:1;background:var(--bg);border:1px solid var(--bd);border-radius:4px;padding:3px 6px;color:var(--tx);font:inherit;font-size:12px}
.tl{flex:1;overflow-y:auto;padding:4px 0}.ti{padding:4px 14px;cursor:pointer;border-bottom:1px solid var(--bd);display:flex;gap:10px}
.ti:hover{background:var(--p2)}.ti .cid{color:var(--acc);font-size:11px;width:240px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ti .ev{color:var(--mut);font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ti .st{font-size:11px;width:80px;text-align:right;flex-shrink:0}.st.ok{color:var(--in)}.st.rj{color:var(--err)}.st.to{color:var(--warn)}

/* Controls */
.ctl-row{display:flex;align-items:center;gap:8px;margin:6px 0}
.ctl-row label{font-size:11px;color:var(--mut);width:80px;flex-shrink:0}
.ctl-row input[type=range]{flex:1;accent-color:var(--acc)}
.ctl-row .val{width:30px;text-align:right;font-size:11px;color:var(--tx)}
.btns{display:flex;gap:6px;margin-top:8px}
.btns button{flex:1;padding:6px;border:1px solid var(--bd);border-radius:4px;background:var(--p2);color:var(--tx);font:inherit;font-size:11px;cursor:pointer}
.btns button:hover{border-color:var(--acc);color:var(--acc)}.btns button:disabled{opacity:.4;cursor:not-allowed}
.toggle-row{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.toggle-row label{font-size:10px;padding:2px 5px;border:1px solid var(--bd);border-radius:3px;cursor:pointer;background:var(--p2);color:var(--mut);display:flex;align-items:center;gap:3px}
.toggle-row input{accent-color:var(--acc)}
.toggle-row label.on{color:var(--in);border-color:var(--in)}

/* View — legacy panels */
.vw{display:none;height:100%;overflow-y:auto;padding:14px}.vw.act{display:block}
.st2{font-size:14px;font-weight:600;margin-bottom:8px;color:var(--acc)}
.card{border:1px solid var(--bd);border-radius:6px;background:var(--panel);padding:11px;margin-bottom:12px;overflow-x:auto}
table{width:100%;border-collapse:collapse}th,td{padding:5px 9px;text-align:left;border-bottom:1px solid var(--bd)}th{color:var(--mut);font-size:11px;text-transform:uppercase}td{font-size:12px;word-break:break-all}
.tag{display:inline-block;background:var(--p2);border:1px solid var(--bd);border-radius:3px;padding:0 4px;font-size:11px;margin:1px}.tag.en{color:var(--in);border-color:var(--in)}.tag.di{color:var(--err);border-color:var(--err)}.tag.rt{color:var(--acc)}.tag.rj{color:var(--warn)}
.empty{color:var(--mut);padding:10px;text-align:center;font-size:12px}
</style></head><body>
<div class="sb" id="sb">
<div class="si"><span class="dot" id="aDot"></span><span class="sv" id="aSt">connecting</span></div>
<div class="si"><span class="sl">instance</span><span class="sv" id="aInst">-</span></div>
<div class="si"><span class="sl">ver</span><span class="sv" id="aVer">-</span></div>
<div class="si"><span class="sl">uptime</span><span class="sv" id="aUp">-</span></div>
<div class="si"><span class="sl">calls</span><span class="sv" id="aCal">0</span></div>
<div class="si"><span class="sl">active</span><span class="sv" id="aAct">0</span></div>
<div class="si"><span class="sl">target</span><span class="sv" id="aTgt">-</span></div>
<div class="sp"></div>
<div class="si ws" id="wsEv">event ws: offline</div>
<div class="si ws" id="wsLd">load ws: offline</div>
</div>

<div class="grid">
<nav class="nav" id="nav">
<button data-v="dashboard" class="act">Dashboard</button>
<button data-v="call-trace">Call Trace</button>
<button data-v="rules">Rules</button>
<button data-v="screening">Screening</button>
<button data-v="statistics">Statistics</button>
<button data-v="about">About</button>
<div class="ctl">
<div class="h">Load Generator</div>
<div class="ctl-row"><label>Target</label><input type="range" id="tgtSlider" min="1" max="50" value="10" disabled><span class="val" id="tgtVal">10</span></div>
<div class="ctl-row"><label>Call rate</label><input type="range" id="rateSlider" min="0.1" max="10" step="0.1" value="3.0" disabled><span class="val" id="rateVal">3.0</span></div>
<div class="btns"><button id="btnStart" disabled>Start</button><button id="btnStop" disabled>Stop</button></div>
<div class="h" style="margin-top:10px">Call Types</div>
<div class="toggle-row" id="typeToggles"></div>
</div>
</nav>

<section class="centre" id="vw-dashboard">
<div class="chart-card">
<div class="chart-h"><span class="t">Call Count (rolling 30s)</span><span class="v" id="liveVal">0 active</span></div>
<div class="chart-wrap"><canvas id="lineChart"></canvas></div>
</div>
<div class="chart-card">
<div class="chart-h"><span class="t">Capacity Gauge</span><span class="v" id="gaugeVal">0 / 10</span></div>
<div class="chart-wrap"><canvas id="gaugeChart"></canvas></div>
</div>
</section>

<aside class="right">
<div class="sm-card t">
<div class="chart-h"><span class="t">State Distribution</span><span class="v" id="pieVal">0 calls</span></div>
<div class="chart-wrap"><canvas id="pieChart"></canvas></div>
</div>
<div class="sm-card g">
<div class="chart-h"><span class="t">Network Topology</span><span class="v" id="topoVal">idle</span></div>
<div class="topo-wrap">
<svg viewBox="0 0 320 120" xmlns="http://www.w3.org/2000/svg" id="topoSvg">
<rect x="4" y="48" width="52" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="30" y="64" text-anchor="middle" fill="var(--mut)" font-size="10">S-CSCF</text>
<line id="l1" x1="56" y1="60" x2="96" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="96" y="48" width="72" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="132" y="64" text-anchor="middle" fill="var(--mut)" font-size="10">Anti-fraud</text>
<line id="l2" x1="168" y1="60" x2="208" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="208" y="48" width="64" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="240" y="64" text-anchor="middle" fill="var(--mut)" font-size="10">Translation</text>
<line id="l3" x1="272" y1="60" x2="312" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="312" y="48" width="4" height="24" rx="1" fill="var(--p2)" stroke="var(--bd)"/>
<text x="318" y="100" text-anchor="middle" fill="var(--mut)" font-size="10">core</text>
</svg>
</div>
</div>
</aside>

<div class="trace">
<div class="trace-h">
<span class="t">Live Call Trace</span>
<input class="tf" id="filt" placeholder="filter Call-ID...">
<span class="ws" id="traceCount">0 calls</span>
</div>
<div class="tl" id="tlist"><div class="empty">no calls yet</div></div>
</div>

<div class="vw" id="vw-call-trace">
<div class="st2">Call Trace</div>
<p class="empty">Switch to the Dashboard view for the live trace panel at the bottom.</p>
</div>

<div class="vw" id="vw-rules">
<div class="st2">Routing Rules</div>
<div class="card" id="rulesCard"><div class="empty">loading...</div></div>
</div>

<div class="vw" id="vw-screening">
<div class="st2">Screening</div>
<div class="card" id="scrCard"><div class="empty">loading...</div></div>
</div>

<div class="vw" id="vw-statistics">
<div class="st2">Statistics</div>
<div class="card" id="statsCard"><div class="empty">loading...</div></div>
</div>

<div class="vw" id="vw-about">
<div class="st2">About</div>
<p style="margin-bottom:8px">A PoC of a third-party SIP Application Server (B2BUA) reached over a SIP trunk from the Service-SBC.</p>
<p style="margin-bottom:8px">Console: <span style="color:var(--acc)">FastAPI + HTML/CSS/JS + vendored Chart.js</span> (ADR-0011). Runs as a separate process (ADR-0002).</p>
<p style="margin-bottom:8px">AS API: <span style="color:var(--acc)" id="apiUrl">-</span></p>
<p>Load generator API: <span style="color:var(--acc)" id="loadUrl">-</span></p>
<p style="margin-top:8px;color:var(--mut);font-size:11px">Chart.js v4.4.8 — MIT license, vendored under /static/ (see chart.umd.min.js.LICENSE.txt).</p>
</div>

</div>

<script>
"use strict";
var AS_URL = "__AS_API_URL__", LD_URL = "__LOAD_API_URL__";
var W_EV = AS_URL.replace(/^http/, "ws") + "/ws/p12/events";
var W_LD = LD_URL.replace(/^http/, "ws") + "/ws/load";

// --- state ---------------------------------------------------------------
var cv = "dashboard", hd = null, md = null, rd = null, sd = null;
var wsEv = null, wsLd = null, wrEv = null, wrLd = null;
var activeCalls = 0, targetConc = 10, callRate = 3.0, poolRunning = false;
var callStates = {}; // call_id -> state
var counters = { active: 0, completed: 0, rejected_608: 0, timeout: 0 };
var lineData = { labels: [], active: [], completed: [], rejected: [] };
var ROLL_WINDOW = 60; // 30s at 0.5s ticks = 60 points
var tc = [], sel = null;
var CALL_TYPES = ["T1","T2","T3","T4","T5","T6","F1","F2","F3","F4"];
var enabledTypes = new Set(CALL_TYPES);
var lineChart, pieChart, gaugeChart;

function E(i){return document.getElementById(i)}
function esc(s){if(s===null||s===undefined)return"";return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

// --- charts --------------------------------------------------------------
function initCharts(){
  var C = Chart;
  Chart.defaults.color = getComputedStyle(document.documentElement).getPropertyValue("--mut");
  Chart.defaults.borderColor = getComputedStyle(document.documentElement).getPropertyValue("--bd");
  Chart.defaults.font.family = '"SF Mono","Cascadia Code","Consolas",monospace';
  Chart.defaults.font.size = 10;

  var acc = getComputedStyle(document.documentElement).getPropertyValue("--acc").trim();
  var grn = getComputedStyle(document.documentElement).getPropertyValue("--in").trim();
  var red = getComputedStyle(document.documentElement).getPropertyValue("--err").trim();
  var orn = getComputedStyle(document.documentElement).getPropertyValue("--warn").trim();

  // Line chart: call count over time
  var lctx = E("lineChart").getContext("2d");
  lineChart = new C(lctx, {
    type: "line",
    data: { labels: lineData.labels, datasets: [
      { label: "active", data: lineData.active, borderColor: acc, backgroundColor: acc + "22", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: "completed/s", data: lineData.completed, borderColor: grn, pointRadius: 0, borderWidth: 1.5 },
      { label: "rejected/s", data: lineData.rejected, borderColor: red, pointRadius: 0, borderWidth: 1.5 }
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top", labels: { boxWidth: 10 } } },
      scales: {
        x: { display: true, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
        y: { beginAtZero: true, display: true }
      }
    }
  });

  // Pie / doughnut: state distribution
  var pctx = E("pieChart").getContext("2d");
  pieChart = new C(pctx, {
    type: "doughnut",
    data: { labels: ["Active", "Completed", "Rejected 608", "Timeout"],
            datasets: [{ data: [0,0,0,0], backgroundColor: [acc, grn, red, orn], borderWidth: 0 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
               cutout: "65%",
               plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } } }
  });

  // Gauge: active / target
  var gctx = E("gaugeChart").getContext("2d");
  gaugeChart = new C(gctx, {
    type: "doughnut",
    data: { labels: ["Active", "Remaining"],
            datasets: [{ data: [0, 10], backgroundColor: [grn, getComputedStyle(document.documentElement).getPropertyValue("--p2").trim()],
                         borderWidth: 0, circumference: 180, rotation: 270 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: { duration: 200 },
               cutout: "75%",
               plugins: { legend: { display: false },
                          tooltip: { enabled: false } } }
  });
}

function pushLinePoint(act, comp, rej){
  var now = new Date().toLocaleTimeString();
  lineData.labels.push(now);
  lineData.active.push(act);
  lineData.completed.push(comp);
  lineData.rejected.push(rej);
  if(lineData.labels.length > ROLL_WINDOW){
    lineData.labels.shift();
    lineData.active.shift();
    lineData.completed.shift();
    lineData.rejected.shift();
  }
  lineChart.update("none");
  E("liveVal").textContent = act + " active";
}

function updatePie(){
  pieChart.data.datasets[0].data = [counters.active, counters.completed, counters.rejected_608, counters.timeout];
  pieChart.update();
  var total = counters.active + counters.completed + counters.rejected_608 + counters.timeout;
  E("pieVal").textContent = total + " calls";
}

function updateGauge(){
  var pct = targetConc > 0 ? Math.min(100, activeCalls / targetConc * 100) : 0;
  gaugeChart.data.datasets[0].data = [activeCalls, Math.max(0, targetConc - activeCalls)];
  var color = pct > 90 ? "var(--err)" : pct > 70 ? "var(--warn)" : "var(--in)";
  gaugeChart.data.datasets[0].backgroundColor[0] = getComputedStyle(document.documentElement).getPropertyValue(color).trim();
  gaugeChart.update();
  E("gaugeVal").textContent = activeCalls + " / " + targetConc;
  E("aAct").textContent = activeCalls;
  E("aTgt").textContent = targetConc;
}

function updateTopology(){
  // 3 links: l1 (SBC→anti-fraud), l2 (anti-fraud→translation), l3 (translation→core)
  var intensity = Math.min(8, 1 + activeCalls * 0.6);
  var color = "var(--mut)";
  if(counters.rejected_608 > 0) color = "var(--err)";
  else if(counters.timeout > 0) color = "var(--warn)";
  else if(activeCalls > 0) color = "var(--in)";
  ["l1","l2","l3"].forEach(function(id){
    var l = E(id);
    l.setAttribute("stroke-width", intensity);
    l.setAttribute("stroke", color);
  });
  E("topoVal").textContent = activeCalls > 0 ? activeCalls + " active" : "idle";
}

// --- event handlers ------------------------------------------------------
function onPoolStatus(d){
  targetConc = d.target_concurrency || targetConc;
  callRate = d.call_rate || callRate;
  activeCalls = d.active_calls || 0;
  poolRunning = d.running || false;
  // Update controls
  E("tgtSlider").value = targetConc; E("tgtVal").textContent = targetConc;
  E("rateSlider").value = callRate; E("rateVal").textContent = callRate;
  E("btnStart").disabled = poolRunning; E("btnStop").disabled = !poolRunning;
  E("tgtSlider").disabled = false; E("rateSlider").disabled = false;
  // Update charts
  updateGauge();
  updateTopology();
  pushLinePoint(activeCalls, 0, 0);
}

function onCallEvent(d){
  var cid = d.call_id, ev = d.event, src = d.source;
  if(!callStates[cid]) callStates[cid] = "started";
  if(ev === "call_started"){ counters.active++; callStates[cid] = "active"; }
  else if(ev === "call_routed" || ev === "call_allowed"){ callStates[cid] = "active"; }
  else if(ev === "call_rejected" || ev === "call_rejected_608"){
    counters.active = Math.max(0, counters.active - 1);
    counters.rejected_608++; callStates[cid] = "rejected";
  }
  else if(ev === "call_ended"){
    var prev = callStates[cid];
    if(prev === "active"){ counters.active = Math.max(0, counters.active - 1); counters.completed++; }
    callStates[cid] = "ended";
  }
  updatePie();
  updateGauge();
  updateTopology();
  // Add to trace
  tc.unshift({ call_id: cid, event: ev, source: src, ts: d.timestamp });
  if(tc.length > 100) tc.pop();
  renderTrace();
}

function renderTrace(){
  var f = (E("filt").value || "").toLowerCase(), l = E("tlist");
  l.innerHTML = "";
  var q = tc.filter(function(t){return !f || t.call_id.toLowerCase().indexOf(f) >= 0;});
  if(!q.length){l.innerHTML='<div class="empty">no calls yet</div>';E("traceCount").textContent="0 calls";return}
  q.forEach(function(t){
    var d = document.createElement("div"); d.className = "ti";
    var stCls = t.event.indexOf("ended")>=0?"ok":t.event.indexOf("rejected")>=0?"rj":t.event.indexOf("timeout")>=0?"to":"";
    var stLabel = t.event.replace("call_","");
    d.innerHTML='<span class="cid">'+esc(t.call_id)+'</span>'+
      '<span class="ev">'+esc(t.event)+' · '+esc(t.source||"")+'</span>'+
      '<span class="st '+stCls+'">'+esc(stLabel)+'</span>';
    l.appendChild(d);
  });
  E("traceCount").textContent = tc.length + " calls";
}

// --- web sockets ---------------------------------------------------------
function connEv(){
  try{wsEv = new WebSocket(W_EV)}catch(e){ewsEv();return}
  wsEv.onopen = function(){E("wsEv").textContent="event ws: live";E("wsEv").className="si ws live"};
  wsEv.onmessage = function(m){try{var d=JSON.parse(m.data);onCallEvent(d)}catch(e){}};
  wsEv.onclose = function(){ewsEv()}; wsEv.onerror = function(){wsEv.close()};
}
function ewsEv(){E("wsEv").textContent="event ws: offline";E("wsEv").className="si ws down";if(!wrEv){wrEv=setTimeout(function(){wrEv=null;connEv()},3000)}}

function connLd(){
  try{wsLd = new WebSocket(W_LD)}catch(e){ewsLd();return}
  wsLd.onopen = function(){E("wsLd").textContent="load ws: live";E("wsLd").className="si ws live"};
  wsLd.onmessage = function(m){try{var d=JSON.parse(m.data);if(d.type==="pool_status_update"||d.active_calls!==undefined)onPoolStatus(d)}catch(e){}};
  wsLd.onclose = function(){ewsLd()}; wsLd.onerror = function(){wsLd.close()};
}
function ewsLd(){E("wsLd").textContent="load ws: offline";E("wsLd").className="si ws down";if(!wrLd){wrLd=setTimeout(function(){wrLd=null;connLd()},3000)}}

// --- health / metrics ----------------------------------------------------
async function fh(){try{var r=await fetch(AS_URL+"/healthz");if(!r.ok)return;hd=await r.json();
  E("aSt").textContent=hd.status;E("aDot").className="dot "+(hd.status==="ok"?"ok":"er");
  E("aVer").textContent=hd.version||"-";E("aInst").textContent=hd.instance||"-";
  E("aUp").textContent=Math.round(hd.uptime_seconds||0)+"s";
  document.title=(hd.instance?hd.instance+" - ":"")+"3rd-party AS Console"}catch(e){E("aSt").textContent="unreachable";E("aDot").className="dot er"}}

async function fm(){try{var r=await fetch(AS_URL+"/api/v1/metrics");if(!r.ok)return;md=await r.json();
  E("aCal").textContent=md.calls_total||0}catch(e){}}

// --- load generator REST ------------------------------------------------
async function ldStart(){try{await fetch(LD_URL+"/load/start",{method:"POST"})}catch(e){}}
async function ldStop(){try{await fetch(LD_URL+"/load/stop",{method:"POST"})}catch(e){}}
async function ldConfig(){
  var types = []; CALL_TYPES.forEach(function(t){if(E("tog_"+t).checked)types.push(t)});
  var body = { target_concurrency: parseInt(E("tgtSlider").value), call_rate: parseFloat(E("rateSlider").value), enabled_call_types: types };
  try{await fetch(LD_URL+"/load/config",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})}catch(e){}
}

// --- nav / toggles -------------------------------------------------------
function sv(v){cv=v;
  document.querySelectorAll(".nav button").forEach(function(b){b.classList.toggle("act",b.dataset.v===v)});
  document.querySelectorAll(".vw").forEach(function(w){w.classList.remove("act")});
  var dash = E("vw-dashboard");
  var el = E("vw-"+v);
  if(v==="dashboard"){dash.style.display="";if(el)el.classList.remove("act")}
  else{dash.style.display="none";if(el)el.classList.add("act")}
  if(v==="rules"){if(!rd)fr();else rr()}if(v==="screening"){if(!sd)fs();else rsd()}
  if(v==="statistics"){if(!md)fm();else rs()}}

function buildToggles(){
  var c = E("typeToggles"); c.innerHTML = "";
  CALL_TYPES.forEach(function(t){
    var lab = document.createElement("label"); lab.htmlFor = "tog_"+t; lab.className = "on";
    lab.innerHTML = '<input type="checkbox" id="tog_'+t+'" checked> '+t;
    lab.querySelector("input").onchange = function(){lab.classList.toggle("on", this.checked); ldConfig()};
    c.appendChild(lab);
  });
}

// --- legacy panels (rules/stats) -----------------------------------------
async function fr(){try{var r=await fetch(AS_URL+"/api/v1/rules");if(!r.ok)return;rd=await r.json();
  if(cv==="rules")rr()}catch(e){}}
function rr(){if(!rd)return;var c=E("rulesCard");
  c.innerHTML='<table><thead><tr><th>Rule ID</th><th>Priority</th><th>Action</th><th>Description</th></tr></thead><tbody>'+
  (rd.rules||[]).map(function(r){
    var a=r.action||{},as=a.kind==="route"?'<span class="tag rt">route</span>':'<span class="tag rj">reject '+a.status+'</span>';
    return"<tr><td>"+esc(r.rule_id)+"</td><td>"+r.priority+"</td><td>"+as+"</td><td>"+esc(r.description||"")+"</td></tr>"}).join("")+
  "</tbody></table>"}
async function fs(){try{var r=await fetch(AS_URL+"/api/v1/screening");if(!r.ok)return;sd=await r.json();
  if(cv==="screening")rsd()}catch(e){}}
function rsd(){if(!sd)return;var c=E("scrCard");
  c.innerHTML='<p style="color:var(--mut);font-size:12px;margin-bottom:8px">data set: '+esc(sd.name||"-")+'</p>'+
  '<p style="color:var(--mut);font-size:12px">block list: '+(sd.block_list||[]).length+' entries · allow list: '+(sd.allow_list||[]).length+' entries</p>'}
function rs(){if(!md)return;var c=E("statsCard");
  c.innerHTML='<p style="color:var(--acc);font-size:14px;font-weight:700;margin-bottom:8px">'+(md.calls_total||0)+' total calls</p>'+
  '<p style="color:var(--mut);font-size:12px">disposition: '+JSON.stringify(md.calls_by_disposition||{})+'</p>'}

// --- init ----------------------------------------------------------------
E("apiUrl").textContent = AS_URL; E("loadUrl").textContent = LD_URL;
document.querySelectorAll(".nav button").forEach(function(b){b.onclick=function(){sv(b.dataset.v)}});
E("filt").oninput = renderTrace;
E("btnStart").onclick = ldStart; E("btnStop").onclick = ldStop;
E("tgtSlider").oninput = function(){E("tgtVal").textContent=this.value};
E("tgtSlider").onchange = ldConfig;
E("rateSlider").oninput = function(){E("rateVal").textContent=parseFloat(this.value).toFixed(1)};
E("rateSlider").onchange = ldConfig;
buildToggles();
initCharts();
fh(); fm(); fr(); fs();
connEv(); connLd();
setInterval(fh, 3000); setInterval(fm, 3000);
// Push a line chart point every 500ms for the rolling view
setInterval(function(){ pushLinePoint(activeCalls, 0, 0); }, 500);
</script></body></html>
"""


def create_app(
    *,
    as_api_url: str = DEFAULT_AS_API_URL,
    load_api_url: str = DEFAULT_LOAD_API_URL,
) -> FastAPI:
    """Create the enhanced console application (P13).

    Args:
        as_api_url: URL of the AS internal API the browser JS fetches from.
        load_api_url: URL of the load generator REST API the browser JS calls.

    Returns:
        A FastAPI application with health endpoint, console page, and
        ``/static/`` mount for vendored Chart.js.
    """
    app = FastAPI(title="3rd-party AS console (enhanced)", version="1.0.0")

    # Vendored Chart.js UMD bundle + license (ADR-0011, REQ-F-050)
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        """Report that the console process is alive."""
        return {
            "status": "ok",
            "component": "console",
            "as_api_url": as_api_url,
            "load_api_url": load_api_url,
            "started_at": time.time(),
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the enhanced console page with API URLs injected."""
        return (
            CONSOLE_PAGE.replace("__AS_API_URL__", as_api_url)
            .replace("__LOAD_API_URL__", load_api_url)
        )

    return app


def main(argv: list[str] | None = None) -> int:
    """Run the enhanced console with uvicorn.

    Args:
        argv: Command line arguments; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="3rd-party AS console (enhanced, P13)")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--as-api-url",
        default=os.environ.get("AS_INTERNAL_API_URL", DEFAULT_AS_API_URL),
        help="URL of the AS internal API (default: env AS_INTERNAL_API_URL or "
        "http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--load-api-url",
        default=os.environ.get("LOAD_API_URL", DEFAULT_LOAD_API_URL),
        help="URL of the load generator REST API (default: env LOAD_API_URL or "
        "http://127.0.0.1:8765)",
    )
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(as_api_url=args.as_api_url, load_api_url=args.load_api_url)
    uvicorn.run(app, host=args.address, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
