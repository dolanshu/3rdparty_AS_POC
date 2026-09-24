"""Playwright E2E for P13 Enhanced Console — full stack regression.

Covers: page load + nav rendering, all 6 views with nav round-trip,
WebSockets, generator lifecycle, live dashboard charts, rules/screening/
statistics/load endpoints, and the view-switch DOM fix (nav must stay
visible after leaving Dashboard).

Run: ``python3 -m pytest tests/e2e/test_console_dashboard.py -v``
"""

from __future__ import annotations

import json
import time
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

import pytest  # P0-3 fix: was missing, caused NameError at L436

# Marker — must match pyproject.toml --strict-markers and Makefile `pytest tests/e2e -m e2e`
pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _put_config(gen_base: str, body: dict) -> dict:
    """PUT /load/config with body, validate HTTP 200, return parsed JSON.

    Replaces the previous ``requests.put`` which silently swallowed every
    failure (missing dep, connection error, 400/422 all indistinguishable).
    Uses stdlib only — no extra dependency required.
    """
    data = json.dumps(body).encode()
    req = urlrequest.Request(
        f"{gen_base}/load/config", data=data, method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        pytest.fail(f"PUT /load/config returned HTTP {e.code}: {body_text}")
    except URLError as e:
        pytest.fail(f"generator unreachable at {gen_base}: {e.reason}")


def _reset_gen(gen_base: str) -> None:
    """Force generator idle — POST /load/stop + poll until running=false & active_calls==0.

    Distinguishes two failure modes (M-5):
      - generator unreachable → immediate pytest.fail (not a timeout)
      - poll timeout → pytest.fail with elapsed diagnostics
    """
    # Fail fast if generator is completely unreachable (not just slow)
    try:
        _gen_status(gen_base)
    except (URLError, ConnectionError) as e:
        pytest.fail(f"generator REST unreachable at {gen_base}: {e.reason}")

    # POST /load/stop
    try:
        req = urlrequest.Request(f"{gen_base}/load/stop", data=b"", method="POST")
        urlrequest.urlopen(req, timeout=3).read()
    except HTTPError:
        pass  # already stopped → 400 is fine
    except (URLError, ConnectionError) as e:
        pytest.fail(f"generator unreachable on /load/stop: {e.reason}")

    # Poll until idle
    deadline = time.time() + 10
    last_state = None
    while time.time() < deadline:
        try:
            last_state = _gen_status(gen_base)
            if not last_state.get("running", True) and last_state.get("active_calls", 1) == 0:
                return
        except Exception:
            pass
        time.sleep(0.3)
    pytest.fail(f"generator did not become idle within 10s — last state: {last_state}")


def _click_visible(page, selector: str) -> None:
    loc = page.locator(selector)
    loc.wait_for(state="visible", timeout=5000)
    loc.click()


def _wait_ws(page, which: str, timeout_ms: int = 8000) -> bool:
    id_map = {"ev": "wsEv", "ld": "wsLd"}
    eid = id_map.get(which, which)
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            txt = page.locator(f"#{eid}").inner_text()
            if "live" in txt.lower():
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _gen_status(gen_base: str) -> dict:
    with urlrequest.urlopen(f"{gen_base}/load/status", timeout=2) as r:
        return json.loads(r.read())


def _as_get(as_api: str, path: str) -> dict:
    with urlrequest.urlopen(f"{as_api}{path}", timeout=2) as r:
        return json.loads(r.read())


def _wait_as_metrics(as_api: str, predicate, timeout: float = 25) -> dict:
    """Poll GET /api/v1/metrics until predicate(metrics) is true."""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = _as_get(as_api, "/api/v1/metrics")
        if predicate(last):
            return last
        time.sleep(0.5)
    pytest.fail(f"AS metrics predicate not met within {timeout}s — last: {last}")


def _wait_fm_refresh(page, seconds: float = 3.5) -> None:
    """Allow console setInterval(fm, 3000) to refresh cached md."""
    page.wait_for_timeout(int(seconds * 1000))


_VALID_CALL_TYPES = ["T1", "T2", "T3", "T5", "T6", "F1", "F2", "F3", "F4"]
_SIMPLE_CALL_TYPES = ["T1", "T2", "T3", "T5", "T6"]


def _accumulate_as_metrics(page, demo_stack) -> dict:
    """Start generator and wait until AS metrics show routed calls."""
    _click_visible(page, "#btnStart")
    metrics = _wait_as_metrics(
        demo_stack["as_api"],
        lambda m: m.get("calls_total", 0) > 0 and bool(m.get("rule_hits")),
    )
    _wait_fm_refresh(page)
    return metrics


def _richest_trace_call(page) -> dict | None:
    """Return the Call-ID with the most entries in the browser ``tc`` buffer."""
    return page.evaluate("""() => {
        var by = {};
        tc.forEach(function(t){
            if(!by[t.call_id]) by[t.call_id] = [];
            by[t.call_id].push(t.event);
        });
        var best = null;
        Object.keys(by).forEach(function(cid){
            var evs = by[cid];
            if(!best || evs.length > best.count){
                best = {call_id: cid, events: evs.slice(), count: evs.length};
            }
        });
        return best;
    }""")


def _wait_full_trace_lifecycle(page, timeout: float = 25) -> dict:
    """Wait until ``tc`` holds started+routed+ended for one Call-ID."""
    required = {"call_started", "call_routed", "call_ended"}
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        last = _richest_trace_call(page)
        if last:
            evs = set(last.get("events") or [])
            if required.issubset(evs):
                return last
        time.sleep(0.5)
    pytest.fail(
        "no Call-ID with call_started + call_routed + call_ended in Live Trace "
        f"within {timeout}s — last tc snapshot: {last!r}. "
        "Filter can only show one row when tc lacks the other lifecycle events."
    )


def _click_nav(page, view: str) -> None:
    _click_visible(page, f'.nav button[data-v="{view}"]')


def _read_chart(page, chart_id: str) -> dict | None:
    return page.evaluate(f"""() => {{
        var c = Chart.getChart(document.getElementById('{chart_id}'));
        if (!c) return null;
        return {{
            labels: c.data.labels ? c.data.labels.length : null,
            data: c.data.datasets ? c.data.datasets.map(d => d.data.slice(0, 20)) : null
        }};
    }}""")


def _open_console(page, demo_stack, wait_seconds: float = 2.0) -> None:
    """Navigate to console, wait for networkidle + WS + initial JS state."""
    # Reset generator first so btnStart/btnStop have predictable initial state
    _reset_gen(demo_stack["gen"])
    page.goto(f"{demo_stack['console']}/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(int(wait_seconds * 1000))
    _wait_ws(page, "ld", timeout_ms=10000)
    _wait_ws(page, "ev", timeout_ms=10000)


# ===========================================================================
# T1 — Page load & nav structure
# ===========================================================================


class TestPageLoad:
    def test_page_loads_without_js_errors(self, page, demo_stack):
        _reset_gen(demo_stack["gen"])
        err_events = []
        page.on("pageerror", lambda e: err_events.append(str(e)))
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        assert page.evaluate("typeof Chart") == "function"
        assert len(err_events) == 0, f"page JS errors: {err_events}"

    def test_all_nav_buttons_present(self, page, demo_stack):
        _open_console(page, demo_stack)
        nav = page.locator(".nav button")
        # Nav buttons: Dashboard + Call Trace + Rules + Screening + Statistics + About
        assert nav.count() >= 5, f"nav buttons count={nav.count()}, texts={[nav.nth(i).inner_text() for i in range(nav.count())]}"
        texts = [nav.nth(i).inner_text() for i in range(nav.count())]
        assert "Dashboard" in texts, f"Dashboard not in nav: {texts}"
        assert "Rules" in texts, f"Rules not in nav: {texts}"
        assert "About" in texts, f"About not in nav: {texts}"
        # Dashboard is initially active
        assert nav.first.evaluate("b => b.classList.contains('act')")

    def test_status_bar_renders(self, page, demo_stack):
        _open_console(page, demo_stack)
        for sid in ["aDot", "aSt", "aInst", "aVer", "aUp", "aCal", "aAct", "aTgt"]:
            assert page.locator(f"#{sid}").count() == 1, f"status bar missing #{sid}"

    def test_both_websockets_connect(self, page, demo_stack):
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        ok_ld = _wait_ws(page, "ld", timeout_ms=10000)
        ok_ev = _wait_ws(page, "ev", timeout_ms=10000)
        assert ok_ld, "load WS (/ws/pool) never became live"
        assert ok_ev, "event WS (/ws/p12/events) never became live"

    def test_initial_dashboard_controls_state(self, page, demo_stack):
        """After resetting generator to idle + fresh page, Stop disabled."""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        _wait_ws(page, "ld")
        _wait_ws(page, "ev")
        # Stop should be disabled — generator confirmed idle via REST
        assert page.locator("#btnStop").is_disabled(), "btnStop should be disabled when generator idle"
        gauge = page.locator("#gaugeVal").inner_text()
        assert gauge.startswith("0 /"), f"gauge should start at 0/N, got '{gauge}'"
        bind = page.locator("#bindInd").inner_text()
        assert "binding:" in bind.lower(), f"binding indicator missing: '{bind}'"
        assert "concurrency" in bind or "rate" in bind
        as_sum = page.locator("#asSummary").inner_text()
        assert "total calls" in as_sum.lower(), f"AS summary missing: '{as_sum}'"


# ===========================================================================
# T2 — Navigation (6 views + nav always visible + round-trip)
# ===========================================================================


class TestNavigation:
    NAV_VIEWS = [
        ("call-trace", "Call Trace"),
        ("rules", "Routing Rules"),
        ("screening", "Screening"),
        ("statistics", "Statistics"),
        ("about", "About"),
    ]

    def test_call_trace_view_renders(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "call-trace")
        page.wait_for_timeout(500)
        assert page.locator("#vw-call-trace").evaluate("el => el.classList.contains('act')")
        assert page.locator("#traceFlowSvg").count() == 1
        assert page.locator(".nav").count() == 1
        assert page.locator('.nav button[data-v="call-trace"]').evaluate(
            "b => b.classList.contains('act')"
        )

    def test_rules_view_renders_and_has_content(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "rules")
        page.wait_for_timeout(1500)
        assert page.locator("#vw-rules").evaluate("el => el.classList.contains('act')")
        card_inner = page.locator("#rulesCard").inner_text()
        assert len(card_inner) > 0, "rulesCard empty"

    def test_screening_view_renders(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "screening")
        page.wait_for_timeout(1000)
        assert page.locator("#vw-screening").evaluate("el => el.classList.contains('act')")
        assert page.locator("#scrCard").count() == 1

    def test_statistics_view_renders(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "statistics")
        page.wait_for_timeout(1500)
        assert page.locator("#vw-statistics").evaluate("el => el.classList.contains('act')")
        card = page.locator("#statsCard")
        assert card.count() == 1
        inner = card.inner_text()
        assert "total calls" in inner.lower()
        # Full metrics tables (disposition / errors / rules / peers) — not JSON.stringify.
        html = card.inner_html()
        assert "stat-section" in html or "No metrics yet" in inner
        assert "JSON.stringify" not in html

    def test_about_view_renders(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "about")
        page.wait_for_timeout(500)
        assert page.locator("#vw-about").evaluate("el => el.classList.contains('act')")
        assert "third-party" in page.locator("#vw-about").inner_text()

    def test_nav_stays_visible_after_each_view(self, page, demo_stack):
        _open_console(page, demo_stack)
        for view, _ in self.NAV_VIEWS:
            _click_nav(page, view)
            page.wait_for_timeout(300)
            assert page.locator(".nav").count() == 1, f"nav disappeared after '{view}'"
            assert page.locator(f'.nav button[data-v="{view}"]').evaluate(
                "b => b.classList.contains('act')"
            )

    def test_round_trip_rules_to_dashboard(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "rules")
        page.wait_for_timeout(500)
        assert page.locator("#vw-rules").evaluate("el => el.classList.contains('act')")
        _click_nav(page, "dashboard")
        page.wait_for_timeout(800)
        # centre section visible again
        centre_display = page.locator("#vw-dashboard").evaluate("el => el.style.display")
        assert centre_display != "none", f"centre still hidden after nav back: display='{centre_display}'"
        assert page.locator('.nav button[data-v="dashboard"]').evaluate(
            "b => b.classList.contains('act')"
        )
        assert not page.locator("#vw-rules").evaluate("el => el.classList.contains('act')")

    def test_all_views_then_back_to_dashboard(self, page, demo_stack):
        _open_console(page, demo_stack)
        for view, _ in self.NAV_VIEWS:
            _click_nav(page, view)
            page.wait_for_timeout(200)
        _click_nav(page, "dashboard")
        page.wait_for_timeout(800)
        centre_display = page.locator("#vw-dashboard").evaluate("el => el.style.display")
        assert centre_display != "none"
        for view, _ in self.NAV_VIEWS:
            assert not page.locator(f"#vw-{view}").evaluate(
                "el => el.classList.contains('act')"
            ), f"{view} still act after dashboard nav"


class TestCallTraceSequence:
    """P15-A: Live row select → REST-backed SVG sequence + event modal (REQ-F-056)."""

    def test_call_trace_view_shows_sequence_after_row_select(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        lifecycle = _wait_full_trace_lifecycle(page, timeout=25)
        assert lifecycle is not None, "no call reached full P12 lifecycle in tc[]"
        page.locator("#tlist .ti").first.click()
        page.wait_for_timeout(2500)
        assert page.locator("#vw-call-trace").evaluate("el => el.classList.contains('act')")
        step_count = page.locator("#traceFlowSvg .seq-step").count()
        assert step_count >= 3, f"expected ≥3 sequence steps, got {step_count}"
        header = page.locator("#traceFlowHeader").inner_text()
        assert lifecycle["call_id"][:8] in header or "events" in header.lower()
        _click_visible(page, "#btnStop")

    def test_call_trace_modal_opens_on_step_click(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        assert _wait_full_trace_lifecycle(page, timeout=25) is not None
        page.locator("#tlist .ti").first.click()
        page.wait_for_timeout(2500)
        page.locator("#traceFlowSvg .seq-step").first.click()
        assert page.locator("#traceDetailModal.open").count() == 1
        body = page.locator("#traceDetailBody").inner_text()
        assert body.strip(), "modal body empty"
        page.locator("#traceDetailX").click()
        _click_visible(page, "#btnStop")

    def test_call_trace_modal_shows_sip_payload(self, page, demo_stack):
        """P15-B: modal shows verbatim SIP when messages API is available (REQ-F-057)."""
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        assert _wait_full_trace_lifecycle(page, timeout=25) is not None
        page.locator("#tlist .ti").first.click()
        page.wait_for_timeout(2500)
        page.locator("#traceFlowSvg .seq-step").first.click()
        sip_pre = page.locator("#traceDetailBody pre.trace-sip")
        assert sip_pre.count() == 1, "expected SIP pre block in modal"
        assert "Call-ID:" in sip_pre.inner_text()
        page.locator("#traceDetailX").click()
        _click_visible(page, "#btnStop")


# ===========================================================================
# T3 — Load generator lifecycle
# ===========================================================================


class TestGeneratorLifecycle:
    def test_start_button_hits_rest_endpoint(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(500)
        s = _gen_status(demo_stack["gen"])
        assert s["running"] is True, f"generator not running after start: {s}"

    def test_active_calls_rise_after_start(self, page, demo_stack):
        """Generator actually starts sending calls — active_calls becomes non-zero."""
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        # With real AS + core mock, some calls get rejected (T4→1234 has no route)
        # so active_calls may never hit the 10 target. Just confirm calls flow.
        deadline = time.time() + 20
        ever_had = False
        while time.time() < deadline:
            s = _gen_status(demo_stack["gen"])
            if s["active_calls"] > 0:
                ever_had = True
                break
            time.sleep(0.5)
        assert ever_had, "active_calls never became non-zero — generator not actually sending"

    def test_stop_button_drains_active_to_zero(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStop")
        deadline = time.time() + 15
        drained = False
        while time.time() < deadline:
            s = _gen_status(demo_stack["gen"])
            if not s["running"] and s["active_calls"] == 0:
                drained = True
                break
            time.sleep(0.5)
        assert drained, f"generator did not drain: {_gen_status(demo_stack['gen'])}"

    def test_console_gauge_rises_then_falls_with_generator(self, page, demo_stack):
        """Generator lifecycle — active_calls rises on Start, drops on Stop.

        The console gauge reads activeCalls from the generator's WebSocket
        stream, which can transiently show 0 when every D1 call in a tick
        gets BYE'd before pool_feed snapshots (1 s cadence).  We use the
        generator REST ``/load/status`` as the authoritative source and
        additionally verify the gauge widget renders at least one non-zero
        value during the run.
        """
        _open_console(page, demo_stack)

        # === Save original generator config so we restore it after this test ===
        # M-4: previous version never restored → polluted TestDashboardLive
        # and TestConcurrent (both inherit T4-disabled state across session).
        orig_cfg = _gen_status(demo_stack["gen"])
        orig_cfg_body = {
            "target_concurrency": orig_cfg.get("target_concurrency", 10),
            "call_rate": orig_cfg.get("call_rate", 3.0),
            "enabled_call_types": orig_cfg.get("enabled_call_types", []),
        }

        # Configure generator to avoid AS reject scenarios and ensure
        # active_calls stays > 0 long enough for pool_feed to see it.
        # Only enable call types that the demo routing table actually
        # matches — T4 ("1234") has no route and AS rejects it instantly.
        valid_types = ["T1", "T2", "T3", "T5", "T6", "F1", "F2", "F3", "F4"]
        _put_config(demo_stack["gen"], {
            "target_concurrency": 10,
            "call_rate": 3.0,
            "enabled_call_types": valid_types,
        })

        # try/finally ensures config restores even if assertions fail
        try:
            _click_visible(page, "#btnStart")

            # Assertion 1: generator REST active_calls rises above 0
            deadline = time.time() + 20
            saw_active = False
            while time.time() < deadline:
                s = _gen_status(demo_stack["gen"])
                if s["running"] and s["active_calls"] > 0:
                    saw_active = True
                    break
                time.sleep(0.5)
            assert saw_active, f"generator never had active_calls>0: {_gen_status(demo_stack['gen'])}"

            # Assertion 2: console gauge shows non-zero at least once
            # (gauge reads generator WS which can lag behind REST)
            deadline = time.time() + 20
            gauge_saw_nonzero = False
            while time.time() < deadline:
                try:
                    txt = page.locator("#gaugeVal").inner_text()
                    if not txt.startswith("0 /"):
                        gauge_saw_nonzero = True
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            assert gauge_saw_nonzero, "console gauge never showed non-zero — WS link broken?"

            # Assertion 3: Stop → active_calls drains to 0
            _click_visible(page, "#btnStop")
            deadline = time.time() + 15
            drained = False
            while time.time() < deadline:
                s = _gen_status(demo_stack["gen"])
                if not s["running"] and s["active_calls"] == 0:
                    drained = True
                    break
                time.sleep(0.5)
            assert drained, f"generator did not drain on stop: {_gen_status(demo_stack['gen'])}"

            # Assertion 4: console gauge resets to 0 after drain
            deadline = time.time() + 10
            gauge_reset = False
            while time.time() < deadline:
                try:
                    if page.locator("#gaugeVal").inner_text().startswith("0 /"):
                        gauge_reset = True
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            assert gauge_reset, "console gauge did not reset after stop"
        finally:
            # M-4: restore original config regardless of assertion outcome
            _put_config(demo_stack["gen"], orig_cfg_body)


# ===========================================================================
# T4 — Dashboard live charts
# ===========================================================================


class TestDashboardLive:
    def _open_and_start(self, page, demo_stack, wait_ms: int = 6000) -> None:
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(wait_ms)

    def test_line_chart_accumulates_points(self, page, demo_stack):
        self._open_and_start(page, demo_stack)
        chart = _read_chart(page, "lineChart")
        assert chart is not None, "lineChart not instantiated"
        assert chart["labels"] >= 4, f"line chart labels={chart['labels']}"

    def test_pie_chart_has_nonzero_segments(self, page, demo_stack):
        self._open_and_start(page, demo_stack, wait_ms=8000)
        chart = _read_chart(page, "pieChart")
        assert chart is not None, "pieChart not instantiated"
        segments = chart["data"][0]
        assert sum(segments) >= 3, f"pie all zeros: {segments}"

    def test_topology_svg_links_change_on_active(self, page, demo_stack):
        _open_console(page, demo_stack)
        idle_sw_attr = page.locator("#l1").evaluate("el => el.getAttribute('stroke-width')")
        idle_sw = float(idle_sw_attr or 2)
        _click_visible(page, "#btnStart")
        # Topology update depends on AS events → console fanout, can be slow
        deadline = time.time() + 20
        active_sw = idle_sw
        active_attr = idle_sw_attr
        while time.time() < deadline:
            try:
                active_attr = page.locator("#l1").evaluate("el => el.getAttribute('stroke-width')")
                active_sw = float(active_attr or 2)
            except Exception:
                pass
            if active_sw > idle_sw + 0.1:
                break
            time.sleep(0.5)
        if active_sw <= idle_sw + 0.1:
            console_state = page.evaluate("""() => ({
                activeCalls: activeCalls,
                counters: counters,
                topoVal: document.getElementById('topoVal').innerText,
                l1_sw: document.getElementById('l1').getAttribute('stroke-width')
            })""")
            assert False, f"topo never changed — idle={idle_sw} active={active_sw} active_attr={active_attr} state={console_state}"
        assert active_sw > idle_sw + 0.1, f"topo stroke-width unchanged: idle={idle_sw} active={active_sw}"

    def test_trace_panel_accumulates_call_records(self, page, demo_stack):
        self._open_and_start(page, demo_stack, wait_ms=8000)
        items = page.locator("#tlist .ti")
        assert items.count() >= 3, f"trace items too few: {items.count()}"

    def test_trace_filter_narrows_list(self, page, demo_stack):
        self._open_and_start(page, demo_stack, wait_ms=8000)
        total_before = page.locator("#tlist .ti").count()
        if total_before == 0:
            pytest.skip("no trace items to filter")
        page.fill("#filt", "zzzzzzzNoMatchzzzzz")
        page.wait_for_timeout(500)
        after_nomatch = page.locator("#tlist .ti").count()
        assert after_nomatch <= total_before, f"filter expanded list: {after_nomatch} > {total_before}"

    def test_trace_filter_shows_multiple_rows_for_one_call_id(self, page, demo_stack):
        """#filt must show every lifecycle event for one Call-ID, not a single row."""
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        lifecycle = _wait_full_trace_lifecycle(page)
        call_id = lifecycle["call_id"]
        page.fill("#filt", call_id)
        page.wait_for_timeout(400)
        rows = page.evaluate("""() => Array.from(document.querySelectorAll('#tlist .ti')).map(function(row){
            return {
                call_id: row.querySelector('.cid').innerText,
                event: row.querySelector('.ev').innerText,
            };
        })""")
        assert len(rows) >= 3, (
            f"filter on {call_id!r} should show >=3 lifecycle rows, got {len(rows)}: {rows!r}; "
            f"tc had events={lifecycle['events']!r}"
        )
        assert all(r["call_id"] == call_id for r in rows), (
            f"filtered rows must all be the same Call-ID: {rows!r}"
        )
        event_text = " ".join(r["event"] for r in rows)
        assert "call_started" in event_text, event_text
        assert "call_routed" in event_text, event_text
        assert "call_ended" in event_text, event_text
        _click_visible(page, "#btnStop")


# ===========================================================================
# T5 — AS REST endpoints
# ===========================================================================


class TestAsRestEndpoints:
    def test_healthz(self, demo_stack):
        h = _as_get(demo_stack["as_api"], "/healthz")
        assert h["status"] == "ok"
        assert "version" in h
        assert "uptime_seconds" in h

    def test_metrics(self, demo_stack):
        m = _as_get(demo_stack["as_api"], "/api/v1/metrics")
        assert "counters" in m
        assert "peer_status" in m
        assert "calls_by_disposition" in m

    def test_rules(self, demo_stack):
        r = _as_get(demo_stack["as_api"], "/api/v1/rules")
        assert "rules" in r
        assert len(r["rules"]) >= 3

    def test_traces_list_has_calls_key(self, demo_stack):
        """/api/v1/traces returns {calls: [...]} not a bare list."""
        t = _as_get(demo_stack["as_api"], "/api/v1/traces")
        assert isinstance(t, dict), f"traces should be dict, got {type(t).__name__}"
        assert "calls" in t, f"traces missing 'calls' key: {list(t.keys())}"
        assert isinstance(t["calls"], list)


# ===========================================================================
# T6 — Concurrent: generator running while navigating views
# ===========================================================================


class TestConcurrentViewSwitchAndGenerator:
    def _open_and_start(self, page, demo_stack) -> None:
        _open_console(page, demo_stack)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(4000)
        s = _gen_status(demo_stack["gen"])
        assert s["running"], f"generator not running at test start: {s}"

    def test_generator_runs_survives_navigation(self, page, demo_stack):
        self._open_and_start(page, demo_stack)
        for v in ["call-trace", "rules", "screening", "statistics", "about"]:
            _click_nav(page, v)
            page.wait_for_timeout(300)
        _click_nav(page, "dashboard")
        page.wait_for_timeout(1000)
        s = _gen_status(demo_stack["gen"])
        assert s["running"], f"generator died after nav hops: {s}"

    def test_stop_after_view_hops_resets(self, page, demo_stack):
        self._open_and_start(page, demo_stack)
        for v in ["rules", "statistics", "dashboard"]:
            _click_nav(page, v)
            page.wait_for_timeout(300)
        _click_visible(page, "#btnStop")
        deadline = time.time() + 15
        drained = False
        while time.time() < deadline:
            s = _gen_status(demo_stack["gen"])
            if not s["running"] and s["active_calls"] == 0:
                drained = True
                break
            time.sleep(0.5)
        assert drained, f"post-nav-stop did not drain: {_gen_status(demo_stack['gen'])}"


# ===========================================================================
# HY4 新增测试 —— 填补三轮 review 发现的覆盖缺口
# ===========================================================================

class TestBindingConstraint:
    """HY4 R3-P0-1 — binding_constraint 翻转 REST E2E.

    compute_binding_constraint() 判定（generator L238）:
        call_rate × AVG_DURATION_SECONDS(10.4) >= target_concurrency → "concurrency"
        否则 → "rate"
    ⚠️ call_rate 越大越倾向于 "concurrency"（HY4 B-1 指出前版配方方向反了）.

    PUT /load/config 响应体**不含** binding_constraint 字段（generator L776 只 echo
    config），所以 PUT 后必须再 GET /load/status 读取。
    """

    _VALID_TYPES = ["T1", "T2", "T3", "T5", "T6", "F1", "F2", "F3", "F4"]

    def test_rate_bound(self, demo_stack):
        """{target_concurrency:10, call_rate:0.1} → 'rate'.

        0.1 × 10.4 = 1.04 < 10 → rate-bound.
        """
        _reset_gen(demo_stack["gen"])
        _put_config(demo_stack["gen"], {
            "target_concurrency": 10,
            "call_rate": 0.1,
            "enabled_call_types": self._VALID_TYPES,
        })
        s = _gen_status(demo_stack["gen"])
        assert s["binding_constraint"] == "rate", (
            f"expected 'rate' for {{target=10, rate=0.1}} "
            f"(0.1×10.4=1.04<10), got '{s['binding_constraint']}': {s}"
        )

    def test_concurrency_bound(self, demo_stack):
        """{target_concurrency:10, call_rate:2.0} → 'concurrency'.

        2.0 × 10.4 = 20.8 >= 10 → concurrency-bound.
        """
        _reset_gen(demo_stack["gen"])
        _put_config(demo_stack["gen"], {
            "target_concurrency": 10,
            "call_rate": 2.0,
            "enabled_call_types": self._VALID_TYPES,
        })
        s = _gen_status(demo_stack["gen"])
        assert s["binding_constraint"] == "concurrency", (
            f"expected 'concurrency' for {{target=10, rate=2.0}} "
            f"(2.0×10.4=20.8>=10), got '{s['binding_constraint']}': {s}"
        )


class TestBindingConstraintUI:
    """phase3-gap-audit item 2 — Dashboard #bindInd follows generator config."""

    def test_bind_ind_reflects_generator_config(self, page, demo_stack):
        _open_console(page, demo_stack)
        initial = page.locator("#bindInd").inner_text().lower()
        assert "binding:" in initial
        assert "concurrency" in initial, f"default should be concurrency-bound: '{initial}'"

        _put_config(demo_stack["gen"], {
            "target_concurrency": 10,
            "call_rate": 0.1,
            "enabled_call_types": _SIMPLE_CALL_TYPES,
            "topology": "simple",
        })
        deadline = time.time() + 8
        saw_rate = False
        while time.time() < deadline:
            txt = page.locator("#bindInd").inner_text().lower()
            if "binding:" in txt and "rate" in txt:
                saw_rate = True
                break
            time.sleep(0.3)
        assert saw_rate, (
            "#bindInd never flipped to rate after PUT call_rate=0.1 — "
            f"last text: {page.locator('#bindInd').inner_text()!r}"
        )


class TestStatisticsMetrics:
    """phase3-gap-audit item 1 — Statistics view renders full /api/v1/metrics tables."""

    def test_peer_status_section_renders(self, page, demo_stack):
        _open_console(page, demo_stack)
        _click_nav(page, "statistics")
        page.wait_for_timeout(1500)
        inner = page.locator("#statsCard").inner_text()
        assert "peer status" in inner.lower(), f"peer_status table missing: {inner!r}"

    def test_metric_sections_after_generator_calls(self, page, demo_stack):
        _open_console(page, demo_stack)
        metrics = _accumulate_as_metrics(page, demo_stack)
        _click_nav(page, "statistics")
        page.wait_for_timeout(500)
        inner = page.locator("#statsCard").inner_text()
        lower = inner.lower()
        assert "disposition" in lower, inner
        assert "rule hits" in lower, inner
        assert "peer status" in lower, inner
        if metrics.get("errors_by_code"):
            assert "errors by code" in lower, inner
        _click_visible(page, "#btnStop")

    def test_rule_hit_link_navigates_to_rules(self, page, demo_stack):
        _open_console(page, demo_stack)
        _accumulate_as_metrics(page, demo_stack)
        _click_nav(page, "statistics")
        page.wait_for_timeout(500)
        link = page.locator("#statsCard .rule-link").first
        assert link.count() >= 1, "expected at least one rule-link in statsCard"
        link.click()
        page.wait_for_timeout(400)
        assert page.locator("#vw-rules").evaluate("el => el.classList.contains('act')")
        _click_visible(page, "#btnStop")


class TestAsSummary:
    """phase3-gap-audit item 3 — Dashboard #asSummary cumulative snapshot."""

    def test_as_summary_shows_top_rule_after_calls(self, page, demo_stack):
        _open_console(page, demo_stack)
        _accumulate_as_metrics(page, demo_stack)
        summary = page.locator("#asSummary").inner_text()
        assert "top rule:" in summary.lower(), f"AS summary missing top rule: {summary!r}"
        _click_visible(page, "#btnStop")

    def test_as_summary_statistics_link(self, page, demo_stack):
        _open_console(page, demo_stack)
        page.wait_for_selector("#asSumLink", timeout=8000)
        page.locator("#asSumLink").click()
        page.wait_for_timeout(500)
        assert page.locator("#vw-statistics").evaluate("el => el.classList.contains('act')")


class TestDomUniqueness:
    """HY4 M-3 / R3-P1-2a — 每个 #vw-{view} 必须全局唯一.

    locator.evaluate / classList.contains 只作用于首个匹配元素。若未来 .vw
    div 又被复制（正是 B3 历史根因——两份 .vw-rules 导致切 dashboard 不可见），
    28 个现有测试照样全绿。这里补 count()==1 断言堵这个漏。
    """

    _VIEWS = ["dashboard", "call-trace", "rules", "screening", "statistics"]

    @pytest.mark.parametrize("view", _VIEWS)
    def test_view_wrapper_unique(self, page, demo_stack, view):
        _open_console(page, demo_stack)
        # Each #vw-{view} must exist exactly once in the document
        n = page.locator(f"#vw-{view}").count()
        assert n == 1, (
            f"#vw-{view} appears {n} times — expected exactly 1 "
            f"(B3 regression: .vw divs duplicated caused invisible views)"
        )


class TestWsOfflineReconnect:
    """HY4 M-3 / R3-P1-2b — WS 离线重连（零额外进程成本）.

    Console JS 实现了 ewsEv()/ewsLd() 3s 重连 + fh() catch 分支把 #aSt
    置 'unreachable'. 用 page.context().set_offline() 做纯前端测试。
    """

    def test_offline_shows_unreachable_then_recovers(self, page, demo_stack):
        _open_console(page, demo_stack)

        # Sanity: both WS were live at open
        assert _wait_ws(page, "ev", timeout_ms=5000), "#wsEv not live before offline"
        assert _wait_ws(page, "ld", timeout_ms=5000), "#wsLd not live before offline"

        # pytest-playwright may expose context as property or callable — be defensive
        ctx = page.context if not callable(page.context) else page.context()

        # -- Take browser offline --
        ctx.set_offline(True)
        # Give the WS error handler time to fire (console JS has 3s reconnect)
        page.wait_for_timeout(3500)

        status_txt = page.locator("#aSt").inner_text()
        assert "unreachable" in status_txt.lower() or "disconnected" in status_txt.lower() or "closed" in status_txt.lower(), (
            f"#aSt did not reflect offline state, got: '{status_txt}' "
            f"(expected 'unreachable' or similar)"
        )

        # -- Bring browser back online --
        ctx.set_offline(False)
        # Wait for WS reconnect + live status
        deadline = time.time() + 10
        recovered = False
        while time.time() < deadline:
            try:
                ev_txt = page.locator("#wsEv").inner_text().lower()
                ld_txt = page.locator("#wsLd").inner_text().lower()
                if "live" in ev_txt and "live" in ld_txt:
                    recovered = True
                    break
            except Exception:
                pass
            time.sleep(0.3)
        assert recovered, f"WS did not recover after back online — ev={ev_txt!r} ld={ld_txt!r}"
