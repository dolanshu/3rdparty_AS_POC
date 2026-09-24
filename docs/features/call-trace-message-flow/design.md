# Design: Call Trace message flow view

**Feature:** `call-trace-message-flow`  
**ADR:** ADR-0016  
**Status:** Draft — approved at Stage 3 review; **implemented** Phase A + B (2026-09-24)  
**Phase A scope:** §1–§5 · **Phase B scope:** §6  

---

## 1. User flow

1. Operator runs load or single call; **Live Call Trace** (`#tlist`) accumulates P12 rows.
2. Operator **clicks one row** (or enters Call-ID in `#filt` and clicks a matching row).
3. Console sets `selectedCallId`, `selectedSource`, highlights row.
4. Console switches to **Call Trace** view (`sv("call-trace")`) — optional auto-switch; manual nav still works.
5. Call Trace centre panel loads `GET {base}/api/v1/traces/{call_id}` where `base` is `AS_URL` or `FRAUD_URL` from row `source`.
6. **SVG sequence diagram** renders in `#traceFlowSvg`.
7. Click an arrow → **modal** (`#traceDetailModal`) with event fields (Phase A) and optional SIP text (Phase B).

Bottom `#trace` panel **stays visible** on all views (unchanged grid).

---

## 2. Lifelines (match HLD)

| Lifeline ID | Label | Role |
| --- | --- | --- |
| `fwd` | mock S-SBC forward | Trunk ingress (`leg=trunk`, peer from first INVITE) |
| `as` | 3rd-party AS | B2BUA + internal decisions |
| `ret` | mock S-SBC return | Next hop (`leg=next_hop`) |

Topology mode does not change lifeline count in Phase A (always three — demo path). Chained mode hint text may note anti-fraud handled on a **separate** trace when `source` is fraud AS.

---

## 3. TraceEvent → arrow mapping

Input: ordered `events[]` from REST (`direction`, `method`, `summary`, `attributes.leg`, `rule_id`, …).

| Condition | From → To | Label |
| --- | --- | --- |
| `direction=in`, `leg=trunk` | fwd → as | `{method}` |
| `direction=out`, `leg=trunk` | as → fwd | `{method}` |
| `direction=in`, `leg=next_hop` | ret → as | `{method}` |
| `direction=out`, `leg=next_hop` | as → ret | `{method}` |
| `direction=internal` | as self-note (box on as lifeline) | `decision` / summary |

**Rule highlight:** if `rule_id` set, note border uses `--rule` colour.

**Ordering:** REST event order (timestamp monotonic within recorder).

---

## 4. UI components (DOM)

| Element | Purpose |
| --- | --- |
| `#vw-call-trace` | View container (replaces placeholder) |
| `#traceFlowHeader` | Selected Call-ID + source + loading/error |
| `#traceFlowSvg` | SVG sequence diagram |
| `#traceDetailModal` | Overlay modal (Phase A/B shared shell) |
| `#traceDetailBody` | Scrollable `<pre>` or structured fields |
| `#tlist .ti` | `data-call-id`, `data-source`; click → select |

### State variables (JS)

```javascript
var selectedCallId = null;
var selectedSource = null;  // matches P12 source string
var traceEvents = [];       // last fetch
var traceMessages = null;   // Phase B: array or null
```

### API helpers

```javascript
function traceApiBase(source) {
  if (source && source.indexOf("fraud") >= 0 && FRAUD_URL) return FRAUD_URL;
  return AS_URL;
}
async function loadCallTrace(callId, source) { /* fetch events; Phase B fetch messages */ }
function renderSequenceSvg(events, container) { /* sets data-event-index on arrows */ }
function showDetail(index) {
  var ev = traceEvents[index];
  var sip = traceMessages ? matchMessage(ev, traceMessages) : null;
  /* modal: event table + optional sip pre */
}
```

---

## 5. Phase A modal content

When `sip === null`:

- Title: `{method} · {direction} · {leg}`
- Fields: `timestamp`, `peer`, `summary`, `rule_id`, `attributes` (JSON pretty)
- Footer: Call-ID, link hint to Statistics/Rules if `rule_id` present

No fabricated SIP start-lines.

---

## 6. Phase B extension (seams only)

**Backend (`as_app`, mirror in `anti_fraud_as` if dual demo):**

- AS stack holds `SipMessageRecorder` (dual-write: still use `SipLogger` for stderr **or** recorder-only in demo — ADR-0016 decides).
- `GET /api/v1/traces/{call_id}/messages` returns:

```json
{
  "call_id": "<trunk>",
  "outbound_call_id": "<trunk>-b2b_1",
  "messages": [
    {"direction": "in", "peer": "127.0.0.1:5060", "call_id": "...", "text": "INVITE sip:..."}
  ]
}
```

**Console:** `loadCallTrace` also fetches messages; `showDetail` renders `text` in monospace when match found; else fallback to Phase A body + note "SIP capture unavailable".

**Matching:** index-order first; refine by `(direction, leg, method)` heuristic — document in ADR if imperfect.

**No change** to `renderSequenceSvg` layout between A and B.

---

## 7. Error and empty states

| State | UI |
| --- | --- |
| No selection | "Select a call from Live Call Trace below" |
| Loading | spinner text in header |
| Unknown Call-ID | empty events → "No trace recorded for this Call-ID" |
| Fetch failed | red banner + retry |
| Zero SIP messages (B) | modal event-only |

---

## 8. Testing hooks

- `#traceFlowSvg arrow[data-event-index="0"]` — integration/e2e selector
- `#traceDetailModal.visible` — class toggled on open
- `#vw-call-trace.act` — nav state

See `testing-plan.md`.

---

## 9. LLD pointer

Console enhancement only (Phase A): no AS code change.  
Phase B: internal API route + message recorder wiring — see `docs/architecture/lld.md` console section after Stage 3 merge (≤20 lines).
