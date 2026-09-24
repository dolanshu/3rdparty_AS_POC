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

"""Console process — Enhanced operations dashboard (Phase 3 P13/P14, ADR-0011).

The console is a separate process serving a dark operations dashboard with
live call-count charts, state distribution, capacity gauge, mode-aware SVG
topology and load-generator controls. Uses vendored Chart.js UMD bundle
served from ``/static/`` (ADR-0011, REQ-F-050). P14 adds dual-AS event
streams and topology modes aligned with P9b (ADR-0015).
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
DEFAULT_FRAUD_API_URL = ""
DEFAULT_LOAD_API_URL = "http://127.0.0.1:8765"

_STATIC_DIR = Path(__file__).parent / "static"

# P13 Enhanced Console: multi-panel CSS Grid layout with 3 Chart.js panels
# plus SVG topology + load generator controls.
# Tokens __AS_API_URL__, __FRAUD_API_URL__ and __LOAD_API_URL__ are replaced at request time.
CONSOLE_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>3rd-party AS Console — Enhanced</title>
<script src="/static/chart.umd.min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--p2:#1c2330;--bd:#30363d;--tx:#c9d1d9;--mut:#8b949e;--acc:#58a6ff;--in:#3fb950;--out:#f0883e;--int:#8b949e;--rule:#d2a8ff;--err:#f85149;--warn:#d29922}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--tx);font-family:"SF Mono","Cascadia Code","Consolas",monospace;font-size:13px;overflow:hidden;overflow-x:hidden}
html,body{width:100%;height:100%;margin:0;padding:0}

/* Status bar */
.sb{display:flex;align-items:center;gap:16px;padding:6px 14px;background:var(--panel);border-bottom:1px solid var(--bd);height:38px}
.si{display:flex;align-items:center;gap:5px}.sl{color:var(--mut);font-size:11px;text-transform:uppercase}.sv{font-weight:600}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mut)}.dot.ok{background:var(--in)}.dot.er{background:var(--err)}.sp{flex:1}
.ws{font-size:11px;color:var(--mut)}.ws.live{color:var(--in)}.ws.down{color:var(--err)}

/* Main grid: 3 columns — nav / centre / right */
.grid{display:grid;grid-template-columns:200px 1fr 280px;grid-template-rows:1fr 220px;height:calc(100vh - 38px);gap:0;min-width:0;overflow:hidden}
.nav{background:var(--panel);border-right:1px solid var(--bd);padding:8px 0;overflow-y:auto;min-width:0}
.nav button{display:block;width:100%;text-align:left;padding:9px 14px;border:none;background:0;color:var(--mut);font:inherit;cursor:pointer;border-left:3px solid transparent}
.nav button:hover{color:var(--tx);background:var(--p2)}.nav button.act{color:var(--acc);border-left-color:var(--acc);background:var(--p2)}
.ctl{margin-top:12px;padding:8px 14px;border-top:1px solid var(--bd)}
.ctl .h{color:var(--mut);font-size:11px;text-transform:uppercase;margin-bottom:6px}

/* Centre panel — charts stacked */
.centre{display:flex;flex-direction:column;overflow:hidden;border-right:1px solid var(--bd);min-width:0}
.chart-card{flex:1;min-height:0;min-width:0;padding:10px 14px;border-bottom:1px solid var(--bd);display:flex;flex-direction:column}
.chart-card:last-child{border-bottom:none}
.chart-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.chart-h .t{font-size:12px;font-weight:600;color:var(--acc)}.chart-h .v{font-size:11px;color:var(--mut)}
.chart-wrap{flex:1;min-height:0;position:relative}

/* Right panel — doughnut + topology */
.right{display:flex;flex-direction:column;overflow:hidden;min-width:0}
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
.ctl-row{display:flex;align-items:center;gap:8px;margin:6px 0;min-width:0}
.ctl-row label{font-size:11px;color:var(--mut);width:70px;flex-shrink:0}
.ctl-row input[type=range]{flex:1;min-width:0;accent-color:var(--acc)}
.ctl-row .val{width:30px;text-align:right;font-size:11px;color:var(--tx);flex-shrink:0}
.btns{display:flex;gap:6px;margin-top:8px}
.btns button{flex:1;padding:6px;border:1px solid var(--bd);border-radius:4px;background:var(--p2);color:var(--tx);font:inherit;font-size:11px;cursor:pointer}
.btns button:hover{border-color:var(--acc);color:var(--acc)}.btns button:disabled{opacity:.4;cursor:not-allowed}
.toggle-row{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.toggle-row label{font-size:10px;padding:2px 5px;border:1px solid var(--bd);border-radius:3px;cursor:pointer;background:var(--p2);color:var(--mut);display:flex;align-items:center;gap:3px}
.toggle-row input{accent-color:var(--acc)}
.toggle-row label.on{color:var(--in);border-color:var(--in)}

/* View — legacy panels */
.vw{display:none;height:100%;overflow-y:auto;padding:14px;grid-column:2;grid-row:1}.vw.act{display:block}
.st2{font-size:14px;font-weight:600;margin-bottom:8px;color:var(--acc)}
.card{border:1px solid var(--bd);border-radius:6px;background:var(--panel);padding:11px;margin-bottom:12px;overflow-x:auto}
table{width:100%;border-collapse:collapse}th,td{padding:5px 9px;text-align:left;border-bottom:1px solid var(--bd)}th{color:var(--mut);font-size:11px;text-transform:uppercase}td{font-size:12px;word-break:break-all}
.tag{display:inline-block;background:var(--p2);border:1px solid var(--bd);border-radius:3px;padding:0 4px;font-size:11px;margin:1px}.tag.en{color:var(--in);border-color:var(--in)}.tag.di{color:var(--err);border-color:var(--err)}.tag.rt{color:var(--acc)}.tag.rj{color:var(--warn)}
.empty{color:var(--mut);padding:10px;text-align:center;font-size:12px}
.topo-mode{display:inline-block;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid var(--acc);color:var(--acc);margin-left:6px}
.topo-hint{font-size:10px;color:var(--mut);margin-top:4px;line-height:1.3}
.topo-wrap svg.dim{opacity:.22}
#topoChained{display:none}
.stat-total{color:var(--acc);font-size:14px;font-weight:700;margin-bottom:10px}
.stat-section{margin-bottom:14px}
.stat-h{font-size:11px;text-transform:uppercase;color:var(--mut);margin-bottom:6px}
tr.err-row td{color:var(--err)}
.bind-ind{font-size:11px;color:var(--mut);margin-top:6px;line-height:1.4}
.bind-tag{display:inline-block;padding:1px 6px;border-radius:3px;border:1px solid var(--acc);color:var(--acc);font-weight:600;text-transform:lowercase}
.as-summary{font-size:11px;color:var(--mut);margin-top:8px;line-height:1.5}
.as-summary a{color:var(--acc);text-decoration:none}
.as-summary a:hover{text-decoration:underline}
.rule-link{color:var(--acc);text-decoration:none}
.rule-link:hover{text-decoration:underline}
</style></head><body>
<div class="sb" id="sb">
<div class="si"><span class="dot" id="aDot"></span><span class="sv" id="aSt">connecting</span></div>
<div class="si" id="fraudHealth" style="display:none"><span class="dot" id="fDot"></span><span class="sv" id="fSt">fraud</span></div>
<div class="si"><span class="sl">instance</span><span class="sv" id="aInst">-</span></div>
<div class="si"><span class="sl">ver</span><span class="sv" id="aVer">-</span></div>
<div class="si"><span class="sl">uptime</span><span class="sv" id="aUp">-</span></div>
<div class="si"><span class="sl">calls</span><span class="sv" id="aCal">0</span></div>
<div class="si"><span class="sl">active</span><span class="sv" id="aAct">0</span></div>
<div class="si"><span class="sl">target</span><span class="sv" id="aTgt">-</span></div>
<div class="sp"></div>
<div class="si ws" id="wsEv">trans ws: offline</div>
<div class="si ws" id="wsEvF" style="display:none">fraud ws: offline</div>
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
<div class="bind-ind" id="bindInd"></div>
<div class="as-summary" id="asSummary"><span style="color:var(--mut)">loading AS metrics…</span></div>
</div>
</section>

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

<aside class="right">
<div class="sm-card t">
<div class="chart-h"><span class="t">State Distribution</span><span class="v" id="pieVal">0 calls</span></div>
<div class="chart-wrap"><canvas id="pieChart"></canvas></div>
</div>
<div class="sm-card g">
<div class="chart-h"><span class="t">Network Topology</span><span class="topo-mode" id="topoMode">Simple</span><span class="v" id="topoVal">idle</span></div>
<div class="topo-hint" id="topoHint" style="display:none">Cross-AS trace: correlate on ICID (P-Charging-Vector), not Call-ID.</div>
<div class="topo-wrap">
<svg viewBox="0 0 320 120" xmlns="http://www.w3.org/2000/svg" id="topoSimple">
<rect x="4" y="48" width="54" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)" id="nSsbc"/>
<text x="31" y="64" text-anchor="middle" fill="var(--mut)" font-size="10">S-SBC</text>
<line id="l1" x1="58" y1="60" x2="82" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="82" y="48" width="90" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)" id="nTrans"/>
<text x="127" y="64" text-anchor="middle" fill="var(--mut)" font-size="10">Translation AS</text>
<line id="l2" x1="172" y1="60" x2="196" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="196" y="48" width="70" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)" id="nRet"/>
<text x="231" y="64" text-anchor="middle" fill="var(--mut)" font-size="10">S-SBC ret</text>
</svg>
<svg viewBox="0 0 400 120" xmlns="http://www.w3.org/2000/svg" id="topoChained">
<rect x="2" y="48" width="40" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="22" y="64" text-anchor="middle" fill="var(--mut)" font-size="9">Gen</text>
<line id="cl1" x1="42" y1="60" x2="58" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="58" y="48" width="44" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="80" y="64" text-anchor="middle" fill="var(--mut)" font-size="9">S-SBC</text>
<line id="cl2" x1="102" y1="60" x2="118" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="118" y="48" width="56" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)" id="cAS1"/>
<text x="146" y="64" text-anchor="middle" fill="var(--mut)" font-size="9">Anti-fraud</text>
<line id="cl3" x1="174" y1="60" x2="190" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="190" y="48" width="36" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="208" y="64" text-anchor="middle" fill="var(--mut)" font-size="9">iFC</text>
<line id="cl4" x1="226" y1="60" x2="242" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="242" y="48" width="56" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)" id="cAS2"/>
<text x="270" y="64" text-anchor="middle" fill="var(--mut)" font-size="9">Translation</text>
<line id="cl5" x1="298" y1="60" x2="314" y2="60" stroke="var(--mut)" stroke-width="2"/>
<rect x="314" y="48" width="36" height="24" rx="4" fill="var(--p2)" stroke="var(--bd)"/>
<text x="332" y="64" text-anchor="middle" fill="var(--mut)" font-size="9">UAS</text>
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

</div>

<script>
"use strict";
var _host = location.hostname;
var AS_URL = "__AS_API_URL__".replace(/:\/\/[^:/]+/, "://" + _host);
var FRAUD_URL = "__FRAUD_API_URL__" ? "__FRAUD_API_URL__".replace(/:\/\/[^:/]+/, "://" + _host) : "";
var LD_URL = "__LOAD_API_URL__".replace(/:\/\/[^:/]+/, "://" + _host);
var W_EV = AS_URL.replace(/^http/, "ws") + "/ws/p12/events";
var W_EV_F = FRAUD_URL ? FRAUD_URL.replace(/^http/, "ws") + "/ws/p12/events" : "";
var W_LD = LD_URL.replace(/^http/, "ws") + "/ws/pool";

// --- state ---------------------------------------------------------------
var cv = "dashboard", hd = null, md = null, rd = null, sd = null;
var wsEv = null, wsEvF = null, wsLd = null, wrEv = null, wrEvF = null, wrLd = null;
var topologyMode = "simple";
var activeCalls = 0, targetConc = 10, callRate = 3.0, poolRunning = false;
var callStates = {}; // call_id -> state
var counters = { active: 0, completed: 0, rejected_608: 0, timeout: 0 };
var lineData = { labels: [], active: [], completed: [], rejected: [] };
var ROLL_WINDOW = 60; // 30s at 0.5s ticks = 60 points
var tc = [], sel = null;
var CALL_TYPES = ["T1","T2","T3","T4","T5","T6","F1","F2","F3","F4"];
var enabledTypes = new Set(CALL_TYPES);
var lineChart, pieChart, gaugeChart;
var AVG_DURATION = 10.4; // DurationModel.AVG_DURATION_SECONDS (ADR-0013)
var DISP_LABELS = {completed:"Completed",no_match:"No match (404)",rejected:"Rejected (603)",cancelled:"Cancelled"};

function E(i){return document.getElementById(i)}
function esc(s){if(s===null||s===undefined)return"";return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

function fmtTable(headers, rows, rowCls){
  if(!rows.length) return "";
  return '<table><thead><tr>'+headers.map(function(h){return "<th>"+h+"</th>"}).join("")+
    '</tr></thead><tbody>'+rows.map(function(r){
      var cls = rowCls ? rowCls(r) : "";
      return "<tr"+(cls?' class="'+cls+'"':"")+">"+r.map(function(c){return "<td>"+c+"</td>"}).join("")+"</tr>";
    }).join("")+"</tbody></table>";
}
function peerStatusCell(status){
  var cls = status==="reachable"?"ok":status==="unreachable"?"er":"";
  return '<span class="dot '+cls+'" style="display:inline-block;margin-right:6px;vertical-align:middle"></span>'+esc(status);
}
function updateBindingIndicator(s){
  var el = E("bindInd"); if(!el) return;
  var bc = s.binding_constraint;
  if(!bc){ el.textContent = ""; return; }
  var rate = s.call_rate != null ? s.call_rate : callRate;
  var tgt = s.target_concurrency != null ? s.target_concurrency : targetConc;
  var theoretical = (rate * AVG_DURATION).toFixed(1);
  el.innerHTML = 'binding: <span class="bind-tag">'+esc(bc)+'</span> (rate×duration='+theoretical+', target='+tgt+')';
}
function updateAsSummary(){
  var el = E("asSummary"); if(!el || !md) return;
  var parts = [(md.calls_total||0)+' total calls'];
  var rh = md.rule_hits || {}, topRule = null, topCount = 0;
  Object.keys(rh).forEach(function(k){ if(rh[k] > topCount){ topCount = rh[k]; topRule = k; }});
  if(topRule) parts.push('top rule: '+esc(topRule)+' ('+topCount+')');
  var err = md.errors_by_code || {}, errKeys = Object.keys(err);
  if(errKeys.length){
    var errStr = errKeys.sort().map(function(k){ return esc(k)+': '+err[k]; }).join(', ');
    parts.push('<span style="color:var(--err)">errors: '+errStr+'</span>');
  }
  el.innerHTML = parts.join(' · ')+' · <a href="#" id="asSumLink">Statistics →</a>';
  var link = E("asSumLink");
  if(link) link.onclick = function(e){ e.preventDefault(); sv("statistics"); return false; };
}

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

function topoIntensity(){
  var instantActive = Math.max(activeCalls || 0, counters.active || 0);
  var totalTraffic = (counters.completed || 0) + (counters.rejected_608 || 0) + (counters.timeout || 0);
  var intensity = Math.min(8, 1 + instantActive * 0.6 + Math.min(3, totalTraffic * 0.03));
  // Link color: only active vs idle (no warn/err on links — those are AS-internal states).
  var linkColor = (instantActive > 0 || totalTraffic > 0) ? "var(--in)" : "var(--mut)";
  // AS node stroke: warn/err live here, not on links.
  var nodeStroke = "var(--bd)";
  if(counters.rejected_608 > 0) nodeStroke = "var(--err)";
  else if(counters.timeout > 0) nodeStroke = "var(--warn)";
  else if(instantActive > 0 || totalTraffic > 0) nodeStroke = "var(--in)";
  return {intensity: intensity, linkColor: linkColor, nodeStroke: nodeStroke, instantActive: instantActive, totalTraffic: totalTraffic};
}

function paintLinks(ids, intensity, color){
  ids.forEach(function(id){
    var l = E(id);
    if(l){ l.setAttribute("stroke-width", intensity); l.setAttribute("stroke", color); }
  });
}

function paintNodes(nodeIds, stroke){
  nodeIds.forEach(function(id){
    var n = E(id);
    if(n){ n.setAttribute("stroke", stroke); }
  });
}

function setTopologyMode(mode){
  topologyMode = mode || "simple";
  var labels = {simple: "Simple", fraud: "Fraud only", chained: "Chained (iFC)"};
  E("topoMode").textContent = labels[topologyMode] || topologyMode;
  E("topoHint").style.display = topologyMode === "chained" ? "" : "none";
  var simple = E("topoSimple"), chained = E("topoChained");
  if(topologyMode === "chained"){
    if(simple) simple.style.display = "none";
    if(chained) chained.style.display = "";
  } else {
    if(simple) simple.style.display = "";
    if(chained) chained.style.display = "none";
  }
  applyToggleGating();
  updateTopology();
}

function applyToggleGating(){
  var tOnly = topologyMode === "fraud", fOnly = topologyMode === "simple";
  CALL_TYPES.forEach(function(t){
    var el = E("tog_"+t), lab = el ? el.parentElement : null;
    if(!el) return;
    var isT = t.charAt(0) === "T", disabled = (tOnly && isT) || (fOnly && !isT);
    el.disabled = disabled;
    if(disabled){ el.checked = false; if(lab) lab.classList.remove("on"); }
    else if(el.checked && lab) lab.classList.add("on");
    if(lab) lab.style.opacity = disabled ? "0.35" : "1";
  });
}

function updateTopology(){
  var m = topoIntensity();
  if(topologyMode === "chained"){
    paintLinks(["cl1","cl2","cl3","cl4","cl5"], m.intensity, m.linkColor);
    paintNodes(["cAS1","cAS2"], m.nodeStroke);
  } else {
    paintLinks(["l1","l2"], m.intensity, m.linkColor);
    paintNodes(["nTrans"], m.nodeStroke);
  }
  if(m.instantActive > 0) E("topoVal").textContent = m.instantActive + " active";
  else if(m.totalTraffic > 0) E("topoVal").textContent = m.totalTraffic + " calls total";
  else E("topoVal").textContent = "idle";
}

// --- event handlers ------------------------------------------------------
function onPoolStatus(d){
  // WS messages wrap snapshot in {attributes:{...}}; REST returns flat.
  var s = d.attributes || d;
  if(s.topology) setTopologyMode(s.topology);
  targetConc = s.target_concurrency || targetConc;
  callRate = s.call_rate || callRate;
  activeCalls = s.active_calls || 0;
  poolRunning = !!s.running;
  // Update controls
  E("tgtSlider").value = targetConc; E("tgtVal").textContent = targetConc;
  E("rateSlider").value = callRate; E("rateVal").textContent = callRate;
  E("btnStart").disabled = poolRunning; E("btnStop").disabled = !poolRunning;
  E("tgtSlider").disabled = false; E("rateSlider").disabled = false;
  // Update charts
  updateGauge();
  updateTopology();
  pushLinePoint(activeCalls, 0, 0);
  updateBindingIndicator(s);
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
  wsEv.onopen = function(){E("wsEv").textContent="trans ws: live";E("wsEv").className="si ws live"};
  wsEv.onmessage = function(m){try{var d=JSON.parse(m.data);onCallEvent(d)}catch(e){}};
  wsEv.onclose = function(){ewsEv()}; wsEv.onerror = function(){wsEv.close()};
}
function ewsEv(){E("wsEv").textContent="trans ws: offline";E("wsEv").className="si ws down";if(!wrEv){wrEv=setTimeout(function(){wrEv=null;connEv()},3000)}}
function connEvF(){
  if(!W_EV_F) return;
  try{wsEvF = new WebSocket(W_EV_F)}catch(e){ewsEvF();return}
  wsEvF.onopen = function(){E("wsEvF").textContent="fraud ws: live";E("wsEvF").className="si ws live"};
  wsEvF.onmessage = function(m){try{var d=JSON.parse(m.data);onCallEvent(d)}catch(e){}};
  wsEvF.onclose = function(){ewsEvF()}; wsEvF.onerror = function(){wsEvF.close()};
}
function ewsEvF(){if(!W_EV_F)return;E("wsEvF").textContent="fraud ws: offline";E("wsEvF").className="si ws down";if(!wrEvF){wrEvF=setTimeout(function(){wrEvF=null;connEvF()},3000)}}

function pollLd(){
  // REST-first unlock: controls must not depend on the WebSocket being reachable
  fetch(LD_URL+"/load/status").then(function(r){return r.json()}).then(function(s){
    if(s){targetConc=s.target_concurrency||targetConc;callRate=s.call_rate||callRate;
      activeCalls=s.active_calls||0;poolRunning=s.running||false;
      E("tgtSlider").value=targetConc;E("tgtVal").textContent=targetConc;
      E("rateSlider").value=callRate;E("rateVal").textContent=callRate;
      E("btnStart").disabled=poolRunning;E("btnStop").disabled=!poolRunning;
      E("tgtSlider").disabled=false;E("rateSlider").disabled=false;
      updateGauge();updateTopology();updateBindingIndicator(s);}
  }).catch(function(){});
}
function connLd(){
  pollLd();
  try{wsLd = new WebSocket(W_LD)}catch(e){ewsLd();return}
  wsLd.onopen = function(){
    E("wsLd").textContent="load ws: live";E("wsLd").className="si ws live";
    // Immediately unlock controls (pool is idle on startup, so Start = enabled)
    E("btnStart").disabled = false; E("btnStop").disabled = true;
    E("tgtSlider").disabled = false; E("rateSlider").disabled = false;
    pollLd();
  };
  wsLd.onmessage = function(m){try{var d=JSON.parse(m.data);if(d.event==="pool_status_update"||(d.attributes!==undefined&&d.attributes.active_calls!==undefined))onPoolStatus(d)}catch(e){}};
  wsLd.onclose = function(){ewsLd()}; wsLd.onerror = function(){wsLd.close()};
}
function ewsLd(){E("wsLd").textContent="load ws: offline";E("wsLd").className="si ws down";if(!wrLd){wrLd=setTimeout(function(){wrLd=null;connLd()},3000)}}

// --- health / metrics ----------------------------------------------------
async function fh(){try{var r=await fetch(AS_URL+"/healthz");if(!r.ok)return;hd=await r.json();
  E("aSt").textContent=hd.status;E("aDot").className="dot "+(hd.status==="ok"?"ok":"er");
  E("aVer").textContent=hd.version||"-";E("aInst").textContent=hd.instance||"-";
  E("aUp").textContent=Math.round(hd.uptime_seconds||0)+"s";
  document.title=(hd.instance?hd.instance+" - ":"")+"3rd-party AS Console"}catch(e){E("aSt").textContent="unreachable";E("aDot").className="dot er"}}
async function ff(){if(!FRAUD_URL)return;try{var r=await fetch(FRAUD_URL+"/healthz");if(!r.ok)return;var fd=await r.json();
  E("fSt").textContent=fd.status;E("fDot").className="dot "+(fd.status==="ok"?"ok":"er")}catch(e){E("fSt").textContent="unreachable";E("fDot").className="dot er"}}

async function fm(){try{var r=await fetch(AS_URL+"/api/v1/metrics");if(!r.ok)return;md=await r.json();
  E("aCal").textContent=md.calls_total||0;
  if(cv==="statistics") rs();
  if(cv==="dashboard") updateAsSummary()}catch(e){}}

// --- load generator REST ------------------------------------------------
async function ldStart(){try{await fetch(LD_URL+"/load/start",{method:"POST"})}catch(e){}}
async function ldStop(){try{await fetch(LD_URL+"/load/stop",{method:"POST"})}catch(e){}}
async function ldConfig(){
  var types = []; CALL_TYPES.forEach(function(t){if(E("tog_"+t).checked)types.push(t)});
  var body = { target_concurrency: parseInt(E("tgtSlider").value), call_rate: parseFloat(E("rateSlider").value), enabled_call_types: types, topology: topologyMode };
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
  if(v==="statistics"){if(!md)fm().then(function(){if(cv==="statistics")rs()});else rs()}}

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
  var html='<p class="stat-total">'+(md.calls_total||0)+' total calls</p>';
  var disp=md.calls_by_disposition||{};
  var dispRows=Object.keys(disp).sort().map(function(k){return [DISP_LABELS[k]||k,disp[k]];});
  if(dispRows.length) html+='<div class="stat-section"><div class="stat-h">Disposition</div>'+
    fmtTable(["Disposition","Count"],dispRows)+'</div>';
  var err=md.errors_by_code||{};
  var errRows=Object.keys(err).sort().map(function(k){return [esc(k),err[k]];});
  if(errRows.length) html+='<div class="stat-section"><div class="stat-h">Errors by code</div>'+
    fmtTable(["Error code","Count"],errRows,function(){return "err-row";})+'</div>';
  var rh=md.rule_hits||{};
  var ruleRows=Object.keys(rh).sort(function(a,b){return rh[b]-rh[a];}).map(function(k){
    return ['<a href="#" class="rule-link" data-rule="'+esc(k)+'">'+esc(k)+'</a>',rh[k]];});
  if(ruleRows.length) html+='<div class="stat-section"><div class="stat-h">Rule hits</div>'+
    fmtTable(["Rule ID","Hits"],ruleRows)+'</div>';
  var ps=md.peer_status||{};
  var peerRows=Object.keys(ps).sort().map(function(k){return [esc(k),peerStatusCell(ps[k])];});
  if(peerRows.length) html+='<div class="stat-section"><div class="stat-h">Peer status</div>'+
    fmtTable(["Peer","Status"],peerRows)+'</div>';
  if(!dispRows.length&&!errRows.length&&!ruleRows.length&&!peerRows.length)
    html+='<p class="empty">No metrics yet</p>';
  c.innerHTML=html;
  c.querySelectorAll(".rule-link").forEach(function(a){
    a.onclick=function(e){e.preventDefault();sv("rules");return false;};});}

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
if(FRAUD_URL){ E("fraudHealth").style.display=""; E("wsEvF").style.display=""; }
setTopologyMode("simple");
fh(); ff(); fm(); fr(); fs();
connEv(); if(W_EV_F) connEvF(); connLd();
setInterval(fh, 3000); setInterval(ff, 3000); setInterval(fm, 3000);
setInterval(pollLd, 5000);
// Push a line chart point every 500ms for the rolling view
setInterval(function(){ pushLinePoint(activeCalls, 0, 0); }, 500);
</script></body></html>
"""


def create_app(
    *,
    as_api_url: str = DEFAULT_AS_API_URL,
    fraud_api_url: str = DEFAULT_FRAUD_API_URL,
    load_api_url: str = DEFAULT_LOAD_API_URL,
) -> FastAPI:
    """Create the enhanced console application (P13/P14).

    Args:
        as_api_url: URL of the translation AS internal API the browser fetches.
        fraud_api_url: Optional anti-fraud AS API for chained mode dual streams.
        load_api_url: URL of the load generator REST API the browser JS calls.

    Returns:
        A FastAPI application with health endpoint, console page, and
        ``/static/`` mount for vendored Chart.js.
    """
    app = FastAPI(title="3rd-party AS console (enhanced)", version="1.1.0")

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
            "fraud_api_url": fraud_api_url or None,
            "load_api_url": load_api_url,
            "started_at": time.time(),
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the enhanced console page with API URLs injected."""
        return (
            CONSOLE_PAGE.replace("__AS_API_URL__", as_api_url)
            .replace("__FRAUD_API_URL__", fraud_api_url)
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
        "--fraud-api-url",
        default=os.environ.get("FRAUD_INTERNAL_API_URL", DEFAULT_FRAUD_API_URL),
        help="URL of the anti-fraud AS internal API (optional; chained demo)",
    )
    parser.add_argument(
        "--load-api-url",
        default=os.environ.get("LOAD_API_URL", DEFAULT_LOAD_API_URL),
        help="URL of the load generator REST API (default: env LOAD_API_URL or "
        "http://127.0.0.1:8765)",
    )
    args = parser.parse_args(argv)

    import uvicorn

    app = create_app(
        as_api_url=args.as_api_url,
        fraud_api_url=args.fraud_api_url,
        load_api_url=args.load_api_url,
    )
    uvicorn.run(app, host=args.address, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
