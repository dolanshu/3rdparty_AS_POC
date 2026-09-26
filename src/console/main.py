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
.chart-h .t{font-size:12px;font-weight:600;color:var(--acc);flex-shrink:0}
.chart-h .v{font-size:11px;color:var(--mut);min-width:92px;text-align:right;flex-shrink:0}
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
.ti:hover{background:var(--p2)}.ti.sel{background:var(--p2);border-left:3px solid var(--acc)}.ti .cid{color:var(--acc);font-size:11px;width:240px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
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
.flow-wrap{flex:1;min-height:280px;overflow:auto;border:1px solid var(--bd);border-radius:6px;background:var(--bg);padding:8px}
.flow-hdr{font-size:11px;color:var(--mut);margin-bottom:8px;word-break:break-all}
#traceFlowSvg{width:100%;min-height:200px;display:block}
.trace-modal{display:none;position:fixed;inset:0;z-index:100;align-items:center;justify-content:center}
.trace-modal.open{display:flex}
.trace-modal-bg{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.trace-modal-box{position:relative;background:var(--panel);border:1px solid var(--bd);border-radius:8px;max-width:560px;width:90%;max-height:80vh;overflow:auto;padding:14px;z-index:1}
.trace-modal-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-weight:600;color:var(--acc)}
.trace-modal-h button{border:none;background:0;color:var(--mut);font-size:18px;cursor:pointer}
.trace-attrs{font-size:11px;color:var(--mut);margin-top:10px;white-space:pre-wrap;word-break:break-all;background:var(--bg);padding:8px;border-radius:4px;border:1px solid var(--bd)}
.mut{color:var(--mut);font-size:11px;margin:6px 0}
</style></head><body>
<div class="sb" id="sb">
<div class="si"><span class="dot" id="aDot"></span><span class="sv" id="aSt">connecting</span></div>
<div class="si" id="fraudHealth" style="display:none"><span class="dot" id="fDot"></span><span class="sv" id="fSt">fraud</span></div>
<div class="si"><span class="sl">instance</span><span class="sv" id="aInst">-</span></div>
<div class="si"><span class="sl">ver</span><span class="sv" id="aVer">-</span></div>
<div class="si"><span class="sl">uptime</span><span class="sv" id="aUp">-</span></div>
<div class="si"><span class="sl">calls</span><span class="sv" id="aCal">0</span></div>
<div class="si"><span class="sl">active</span><span class="sv" id="aAct">0</span></div>
<div class="si"><span class="sl">concurrent</span><span class="sv" id="aTgt">-</span></div>
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
<div class="ctl-row"><label>Concurrent</label><input type="range" id="tgtSlider" min="1" max="50" value="10" disabled><span class="val" id="tgtVal">10</span></div>
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
<div class="st2">Call Trace — message flow</div>
<p class="flow-hdr" id="traceFlowHeader">Select a call from Live Call Trace below</p>
<div class="flow-wrap" id="traceFlowWrap"><svg id="traceFlowSvg" xmlns="http://www.w3.org/2000/svg"></svg></div>
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
<div class="st2" style="margin-top:16px">Call Types</div>
<p style="margin-bottom:6px;color:var(--mut);font-size:11px">T1–T6 exercise the <span style="color:var(--acc)">Translation AS</span>; F1–F4 exercise the <span style="color:var(--acc)">Anti-fraud AS</span>.</p>
<table style="font-size:12px">
<thead><tr><th>Type</th><th>Input</th><th>Behaviour</th></tr></thead>
<tbody>
<tr><td>T1</td><td>+86… E.164</td><td>convert to 0…, relay</td></tr>
<tr><td>T2</td><td>0… national</td><td>keep format, relay</td></tr>
<tr><td>T3</td><td>00… international</td><td>convert to +…, relay</td></tr>
<tr><td>T4</td><td>4-digit short code</td><td>no matching rule → 404</td></tr>
<tr><td>T5</td><td>reachable next hop</td><td>200 OK</td></tr>
<tr><td>T6</td><td>unreachable next hop</td><td>3 s timeout → AS fails</td></tr>
<tr><td>F1</td><td>allow-listed caller</td><td>relay → downstream AS</td></tr>
<tr><td>F2</td><td>block-listed caller</td><td>608 Rejected</td></tr>
<tr><td>F3</td><td>high-rate caller</td><td>608 Rejected</td></tr>
<tr><td>F4</td><td>missing P-Asserted-Identity</td><td>fail-open → relay</td></tr>
</tbody>
</table>
<div class="st2" style="margin-top:16px">Author</div>
<p style="margin-bottom:8px">Dolan Shu &lt;dolan.d.shu@gmail.com&gt;</p>
</div>

<aside class="right">
<div class="sm-card t">
<div class="chart-h"><span class="t">State Distribution</span><span class="v" id="pieVal">0 calls</span></div>
<div class="chart-wrap"><canvas id="pieChart"></canvas></div>
</div>
<div class="sm-card g">
<div class="chart-h"><span class="t">Network Topology</span><span class="topo-mode" id="topoMode">Simple</span><span class="v" id="topoVal">idle</span></div>
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
<svg viewBox="0 0 500 280" xmlns="http://www.w3.org/2000/svg" id="topoChained">
<!-- Placeholder lines (cl1, cl3, cl5) — no visual role; skipped by paintLinks -->
<line id="cl1" x1="0" y1="0" x2="0" y2="0" stroke="none" stroke-width="0"/>
<line id="cl3" x1="0" y1="0" x2="0" y2="0" stroke="none" stroke-width="0"/>
<line id="cl5" x1="0" y1="0" x2="0" y2="0" stroke="none" stroke-width="0"/>
<!-- Row 1: AS layer -->
<rect x="60" y="35" width="120" height="40" rx="6" fill="var(--p2)" stroke="var(--bd)" id="cAS1"/>
<text x="120" y="60" text-anchor="middle" fill="var(--mut)" font-size="12">Anti-fraud</text>
<rect x="320" y="35" width="120" height="40" rx="6" fill="var(--p2)" stroke="var(--bd)" id="cAS2"/>
<text x="380" y="60" text-anchor="middle" fill="var(--mut)" font-size="12">Translation</text>
<!-- Vertical links: Core box → AS nodes -->
<line id="cl2" x1="120" y1="140" x2="120" y2="75" stroke="var(--mut)" stroke-width="2"/>
<line id="cl4" x1="380" y1="140" x2="380" y2="75" stroke="var(--mut)" stroke-width="2"/>
<!-- Row 2: Core network box -->
<rect x="50" y="140" width="400" height="110" rx="8" fill="var(--p2)" stroke="var(--bd)" stroke-width="1" id="cCore"/>
<line x1="60" y1="195" x2="440" y2="195" stroke="var(--bd)" stroke-width="1" stroke-dasharray="4,3"/>
<text x="250" y="175" text-anchor="middle" fill="var(--int)" font-size="13" font-weight="bold">S-SBC</text>
<text x="250" y="225" text-anchor="middle" fill="var(--int)" font-size="13" font-weight="bold">S-CSCF (iFC)</text>
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

<div class="trace-modal" id="traceDetailModal">
<div class="trace-modal-bg" id="traceDetailClose"></div>
<div class="trace-modal-box">
<div class="trace-modal-h"><span>Trace event</span><button type="button" id="traceDetailX" title="Close">×</button></div>
<div id="traceDetailBody"></div>
</div>
</div>

<script>
"use strict";
var _host = location.hostname;
var AS_URL = "__AS_API_URL__".replace(/:\\/\\/[^:/]+/, "://" + _host);
var FRAUD_URL = "__FRAUD_API_URL__" ? "__FRAUD_API_URL__".replace(/:\\/\\/[^:/]+/, "://" + _host) : "";
var LD_URL = "__LOAD_API_URL__".replace(/:\\/\\/[^:/]+/, "://" + _host);
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
var selectedCallId = null, selectedSource = null, traceEvents = [], traceMessages = null;
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
  el.innerHTML = 'binding: <span class="bind-tag">'+esc(bc)+'</span> (rate×duration='+theoretical+', max='+tgt+')';
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
  var simple = E("topoSimple"), chained = E("topoChained");
  if(topologyMode === "chained"){
    if(simple) simple.style.display = "none";
    if(chained) chained.style.display = "inline";
  } else {
    if(simple) simple.style.display = "inline";
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
    else { el.checked = true; if(lab) lab.classList.add("on"); }
    if(lab) lab.style.opacity = disabled ? "0.35" : "1";
  });
}

function updateTopology(){
  var m = topoIntensity();
  if(topologyMode === "chained"){
    paintLinks(["cl2","cl4"], m.intensity, m.linkColor);
    paintNodes(["cAS1","cAS2","cCore"], m.nodeStroke);
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

// --- Call Trace sequence view (REQ-F-056, ADR-0016) ----------------------
function traceApiBase(source){
  if(source && source.indexOf("fraud")>=0 && FRAUD_URL) return FRAUD_URL;
  return AS_URL;
}
function normDir(d){
  d = (d||"").toLowerCase();
  if(d==="in"||d==="inbound") return "in";
  if(d==="out"||d==="outbound") return "out";
  if(d==="internal"||d==="int") return "internal";
  return d;
}
function eventArrowMeta(ev){
  var leg = (ev.attributes && ev.attributes.leg) || "-";
  var dir = normDir(ev.direction);
  if(dir==="internal"){
    return {kind:"note", label:(ev.method||"decision")+(ev.summary?": "+ev.summary.slice(0,36):""), rule:ev.rule_id};
  }
  var from=1,to=1,color="var(--mut)";
  if(dir==="in" && leg==="trunk"){ from=0; to=1; color="var(--in)"; }
  else if(dir==="out" && leg==="trunk"){ from=1; to=0; color="var(--out)"; }
  else if(dir==="in" && leg==="next_hop"){ from=2; to=1; color="var(--in)"; }
  else if(dir==="out" && leg==="next_hop"){ from=1; to=2; color="var(--out)"; }
  var label = ev.method || "?";
  if(ev.rule_id) label += " · "+ev.rule_id;
  return {kind:"arrow", from:from, to:to, label:label, color:ev.rule_id?"var(--rule)":color, rule:ev.rule_id};
}
function renderSequenceSvg(events){
  var svg = E("traceFlowSvg"); if(!svg) return;
  if(!events.length){ svg.innerHTML=""; return; }
  var xs=[60,160,260], names=["S-SBC fwd","AS","S-SBC ret"];
  var rowH=32, top=48, h=top+events.length*rowH+24;
  svg.setAttribute("viewBox","0 0 320 "+h);
  var parts=['<defs><marker id="arrowHead" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="var(--mut)"/></marker></defs>'];
  for(var i=0;i<3;i++){
    parts.push('<line x1="'+xs[i]+'" y1="22" x2="'+xs[i]+'" y2="'+(h-8)+'" stroke="var(--bd)" stroke-width="1"/>');
    parts.push('<text x="'+xs[i]+'" y="16" text-anchor="middle" fill="var(--mut)" font-size="10">'+names[i]+'</text>');
  }
  events.forEach(function(ev, idx){
    var y=top+idx*rowH, meta=eventArrowMeta(ev);
    if(meta.kind==="note"){
      parts.push('<g class="seq-step" data-event-index="'+idx+'"><rect x="'+(xs[1]-58)+'" y="'+(y-10)+'" width="116" height="18" rx="3" fill="var(--p2)" stroke="'+(ev.rule_id?"var(--rule)":"var(--int)")+'"/>');
      parts.push('<text x="'+xs[1]+'" y="'+(y+2)+'" text-anchor="middle" fill="var(--int)" font-size="9">'+esc(meta.label.slice(0,22))+'</text></g>');
    }else{
      var x1=xs[meta.from], x2=xs[meta.to];
      parts.push('<g class="seq-step" data-event-index="'+idx+'">');
      parts.push('<line class="seq-arrow" x1="'+x1+'" y1="'+y+'" x2="'+x2+'" y2="'+y+'" stroke="'+meta.color+'" stroke-width="2" marker-end="url(#arrowHead)"/>');
      parts.push('<text x="'+((x1+x2)/2)+'" y="'+(y-5)+'" text-anchor="middle" fill="var(--tx)" font-size="9">'+esc(meta.label)+'</text>');
      parts.push('<rect x="'+Math.min(x1,x2)+'" y="'+(y-10)+'" width="'+Math.max(Math.abs(x2-x1),20)+'" height="16" fill="transparent"/></g>');
    }
  });
  svg.innerHTML = parts.join("");
  svg.querySelectorAll(".seq-step").forEach(function(g){
    g.style.cursor="pointer";
    g.onclick=function(){ showDetail(parseInt(g.getAttribute("data-event-index"),10)); };
  });
}
function matchMessage(ev, messages, eventIndex){
  if(!messages || !messages.length) return null;
  var dir = normDir(ev.direction);
  var method = (ev.method || "").toUpperCase();
  var candidates = [];
  for(var i=0;i<messages.length;i++){
    var m = messages[i];
    if(normDir(m.direction) !== dir) continue;
    var firstLine = (m.text || "").split("\\n")[0].toUpperCase();
    if(firstLine.indexOf(method) === 0 || firstLine.indexOf("SIP/2.0 "+method) >= 0){
      candidates.push(m);
    }
  }
  if(!candidates.length) return null;
  if(typeof eventIndex === "number" && candidates.length === 1) return candidates[0];
  if(typeof eventIndex === "number" && eventIndex < candidates.length) return candidates[eventIndex];
  return candidates[0];
}
function showDetail(index){
  var ev = traceEvents[index]; if(!ev) return;
  var body = E("traceDetailBody"), modal = E("traceDetailModal");
  if(!body||!modal) return;
  var leg = (ev.attributes && ev.attributes.leg) || "-";
  var attrs = ev.attributes ? JSON.stringify(ev.attributes,null,2) : "{}";
  var sip = traceMessages ? matchMessage(ev, traceMessages, index) : null;
  var sipBlock = sip ? '<pre class="trace-sip">'+esc(sip.text)+'</pre>' :
    (traceMessages !== null ? '<p class="mut">SIP capture unavailable for this step</p>' : '');
  body.innerHTML = '<p><strong>'+esc(ev.method)+'</strong> · '+esc(ev.direction)+' · '+esc(leg)+'</p>'+
    '<p class="mut">'+esc(ev.summary||"")+'</p>'+
    '<table><tr><td>timestamp</td><td>'+esc(ev.timestamp||"")+'</td></tr>'+
    '<tr><td>peer</td><td>'+esc(ev.peer||"-")+'</td></tr>'+
    '<tr><td>rule_id</td><td>'+esc(ev.rule_id||"-")+'</td></tr></table>'+
    sipBlock+
    '<pre class="trace-attrs">'+esc(attrs)+'</pre>';
  modal.classList.add("open");
}
function closeDetail(){ var m=E("traceDetailModal"); if(m) m.classList.remove("open"); }
async function loadCallTrace(callId, source){
  var hdr=E("traceFlowHeader");
  if(hdr) hdr.textContent="loading "+callId+"…";
  traceEvents=[]; traceMessages=null;
  try{
    var base=traceApiBase(source);
    var r=await fetch(base+"/api/v1/traces/"+encodeURIComponent(callId));
    if(!r.ok) throw new Error("HTTP "+r.status);
    var data=await r.json();
    traceEvents=data.events||[];
    try{
      var mr=await fetch(base+"/api/v1/traces/"+encodeURIComponent(callId)+"/messages");
      if(mr.ok){ var mdata=await mr.json(); traceMessages=mdata.messages||[]; }
    }catch(_ignore){ traceMessages=null; }
    if(hdr) hdr.textContent=callId+" · "+esc(source||"as_translation")+" · "+traceEvents.length+" events";
    renderSequenceSvg(traceEvents);
  }catch(e){
    traceEvents=[];
    if(hdr) hdr.textContent="failed to load trace for "+callId+" ("+e+")";
    renderSequenceSvg([]);
  }
}
function selectTraceRow(callId, source){
  selectedCallId=callId; selectedSource=source||null;
  renderTrace();
  loadCallTrace(callId, source);
  sv("call-trace");
}

function renderTrace(){
  var f = (E("filt").value || "").toLowerCase(), l = E("tlist");
  l.innerHTML = "";
  var q = tc.filter(function(t){return !f || t.call_id.toLowerCase().indexOf(f) >= 0;});
  if(!q.length){l.innerHTML='<div class="empty">no calls yet</div>';E("traceCount").textContent="0 calls";return}
  q.forEach(function(t){
    var d = document.createElement("div"); d.className = "ti";
    if(selectedCallId === t.call_id) d.classList.add("sel");
    d.dataset.callId = t.call_id;
    d.dataset.source = t.source || "";
    var stCls = t.event.indexOf("ended")>=0?"ok":t.event.indexOf("rejected")>=0?"rj":t.event.indexOf("timeout")>=0?"to":"";
    var stLabel = t.event.replace("call_","");
    d.innerHTML='<span class="cid">'+esc(t.call_id)+'</span>'+
      '<span class="ev">'+esc(t.event)+' · '+esc(t.source||"")+'</span>'+
      '<span class="st '+stCls+'">'+esc(stLabel)+'</span>';
    d.onclick=function(){ selectTraceRow(t.call_id, t.source); };
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
      if(s.topology) setTopologyMode(s.topology);  // close race window: REST also updates topology
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
  if(v==="statistics"){if(!md)fm().then(function(){if(cv==="statistics")rs()});else rs()}
  if(v==="call-trace" && selectedCallId){ loadCallTrace(selectedCallId, selectedSource); }
}

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
async function fs(){
  if(!FRAUD_URL){sd={noFraud:true};rsd();return}
  try{var r=await fetch(FRAUD_URL+"/api/v1/screening");if(!r.ok)return;sd=await r.json();
  if(cv==="screening")rsd()}catch(e){}}
function rsd(){
  var c=E("scrCard");
  if(sd&&sd.noFraud){c.innerHTML='<div class="empty">Screening is provided by the Anti-fraud AS (not active in this topology).</div>';return}
  if(!sd)return;
  var w=sd.window||{},rp=sd.reputation||{},bl=sd.block_list||[],al=sd.allow_list||[];
  var h='<h3 style="margin:0 0 4px;font-size:13px;color:var(--acc)">'+esc(sd.name||"-")+'</h3>';
  h+='<p style="margin:0 0 12px;color:var(--mut);font-size:11px">'+esc(sd.description||"")+'</p>';
  // Window + Reputation 参数（2 列）
  h+='<table style="font-size:11px;margin-bottom:12px"><thead><tr><th colspan="2">Window</th><th colspan="2">Reputation</th></tr></thead><tbody>';
  h+='<tr><td>max_calls</td><td>'+w.max_calls+' / '+w.seconds+'s</td><td>default_score</td><td>'+rp.default_score+'</td></tr>';
  h+='<tr><td colspan="2"></td><td>reject_below</td><td>'+rp.reject_below+'</td></tr>';
  h+='<tr><td colspan="2"></td><td>reject_penalty</td><td>'+rp.reject_penalty+'</td></tr>';
  h+='<tr><td colspan="2"></td><td>half_life</td><td>'+rp.half_life_seconds+'s</td></tr>';
  h+='<tr><td colspan="2"></td><td>max_tracked_callers</td><td>'+(rp.max_tracked_callers||"-")+'</td></tr>';
  h+='</tbody></table>';
  // Block list
  h+='<h4 style="margin:0 0 4px;font-size:12px;color:var(--rj)">Block List ('+bl.length+')</h4>';
  h+='<table style="font-size:11px"><thead><tr><th>Entry ID</th><th>Number / Prefix</th><th>Reason</th></tr></thead><tbody>';
  h+=bl.map(function(e){return'<tr><td>'+esc(e.entry_id||"")+'</td><td>'+esc(e.value||"")+'</td><td>'+esc(e.reason||"")+'</td></tr>'}).join("");
  if(!bl.length)h+='<tr><td colspan="3" style="color:var(--mut)">— empty —</td></tr>';
  h+='</tbody></table>';
  // Allow list
  h+='<h4 style="margin:10px 0 4px;font-size:12px;color:var(--rt)">Allow List ('+al.length+')</h4>';
  h+='<table style="font-size:11px"><thead><tr><th>Entry ID</th><th>Number / Prefix</th><th>Reason</th></tr></thead><tbody>';
  h+=al.map(function(e){return'<tr><td>'+esc(e.entry_id||"")+'</td><td>'+esc(e.value||"")+'</td><td>'+esc(e.reason||"")+'</td></tr>'}).join("");
  if(!al.length)h+='<tr><td colspan="3" style="color:var(--mut)">— empty —</td></tr>';
  h+='</tbody></table>';
  c.innerHTML=h;
}
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
if(E("traceDetailClose")) E("traceDetailClose").onclick = closeDetail;
if(E("traceDetailX")) E("traceDetailX").onclick = closeDetail;
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
