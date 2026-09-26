# Testing plan: Call Trace message flow

**Feature:** `call-trace-message-flow`  
**Status:** Executed — Stages 6 and 9 complete (2026-09-24)  
**Related:** REQ-F-056 (A), REQ-F-057 (B), ACC-P15-001, ACC-P15-002  

---

## 1. Strategy

| Layer | Phase A | Phase B |
| --- | --- | --- |
| Unit | JS mapping `eventToArrow()` pure logic (optional extract to testable functions or integration-only) | Message JSON schema builder tests in AS |
| Integration | Console HTML markers + REST trace fetch via real AS | `GET .../messages` with `SipMessageRecorder` |
| E2E Playwright | Select row → Call Trace → SVG arrows ≥ N | Modal contains `INVITE sip:` substring |

Prefer **integration** for Phase A core (no browser required for ladder correctness). E2E proves operator workflow.

---

## 2. Phase A tests

### 2.1 `tests/integration/test_console_call_trace_flow.py` (new file)

| # | Test | Assert |
| --- | --- | --- |
| 1 | `test_console_page_has_call_trace_flow_markers` | `#traceFlowSvg`, `#traceDetailModal`, `#traceFlowHeader` in `CONSOLE_PAGE` |
| 2 | `test_trace_event_to_arrow_mapping_documented` | Optional: import shared mapping if extracted to Python test helper mirroring JS |

### 2.2 `tests/integration/test_call_trace_sequence.py` (new file)

Uses `trunk_pair` + internal API:

| # | Test | Assert |
| --- | --- | --- |
| 1 | `test_completed_call_trace_has_invite_and_200_events` | `GET /api/v1/traces/{id}` events include trunk INVITE, next_hop 200, internal decision |
| 2 | `test_trace_events_ordered_for_sequence_render` | timestamps non-decreasing |

### 2.3 `tests/e2e/test_console_dashboard.py` (extend)

| # | Test | Assert |
| --- | --- | --- |
| 1 | `test_call_trace_view_shows_sequence_after_row_select` | Start generator → click `#tlist .ti` first row → `#vw-call-trace.act` → `#traceFlowSvg arrow` count ≥ 3 |
| 2 | `test_call_trace_modal_opens_on_arrow_click` | click arrow → `#traceDetailModal` visible + contains `INVITE` or `200` |

Update `docs/testing/e2e-playwright-plan.md` §3.x with test #44–45.

### 2.4 `tests/integration/test_console.py` (extend)

- Replace placeholder assertion: `#vw-call-trace` must **not** contain only "Switch to the Dashboard"
- Assert `#traceFlowSvg` present

---

## 3. Phase B tests

### 3.1 `tests/integration/test_call_trace_messages_api.py` (new)

| # | Test | Assert |
| --- | --- | --- |
| 1 | `test_messages_api_returns_invite_for_completed_call` | After `trunk_pair` call, `GET .../messages` ≥ 2 messages, one starts with `INVITE` |
| 2 | `test_messages_include_outbound_call_id_field` | outbound leg id present |

### 3.2 E2E

| # | Test | Assert |
| --- | --- | --- |
| 1 | `test_call_trace_modal_shows_sip_payload` | modal `pre` matches `Call-ID:` header line |

Update `docs/testing/integration-plan.md` §3.9.

---

## 4. Commands

```bash
# Phase A gate
uv run pytest tests/integration/test_console_call_trace_flow.py \
  tests/integration/test_call_trace_sequence.py \
  tests/integration/test_console.py -v -k "call_trace or trace_flow"
uv run pytest tests/e2e/test_console_dashboard.py -v -k "call_trace"

# Phase B gate
uv run pytest tests/integration/test_call_trace_messages_api.py -v
uv run pytest tests/e2e/test_console_dashboard.py -v -k "sip_payload"

# Full regression (before Stage 11)
NO_PROXY=127.0.0.1,localhost uv run pytest tests/unit tests/integration -q
uv run ruff check .
```

---

## 5. Doc updates (Stage 4 / 6 / 9)

| File | Change |
| --- | --- |
| `docs/testing/integration-plan.md` | +2 files, +N tests |
| `docs/testing/e2e-playwright-plan.md` | #44–45, REQ-F-056 mapping |
| `docs/testing/unit-plan.md` | optional mapping test |

---

## 6. Acceptance evidence

| ACC | Evidence |
| --- | --- |
| ACC-P15-001 | pytest integration + e2e commands above |
| ACC-P15-002 | messages API integration + e2e modal SIP |
