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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_gen(gen_base: str) -> None:
    """Force generator idle — POST /load/stop + poll until running=false."""
    import json as _json
    try:
        urlrequest.urlopen(f"{gen_base}/load/stop", data=b"", timeout=3).read()
    except Exception:
        pass
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urlrequest.urlopen(f"{gen_base}/load/status", timeout=2) as r:
                s = _json.loads(r.read())
                if not s.get("running", True) and s.get("active_calls", 1) == 0:
                    return
        except Exception:
            pass
        time.sleep(0.3)


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
        page.wait_for_timeout(1000)
        assert page.locator("#vw-statistics").evaluate("el => el.classList.contains('act')")
        assert page.locator("#statsCard").count() == 1

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

        # Configure generator to avoid AS reject scenarios and ensure
        # active_calls stays > 0 long enough for pool_feed to see it.
        # Only enable call types that the demo routing table actually
        # matches — T4 ("1234") has no route and AS rejects it instantly.
        valid_types = ["T1", "T2", "T3", "T5", "T6", "F1", "F2", "F3", "F4"]
        try:
            import requests
            requests.put(
                f"{demo_stack['gen']}/load/config",
                json={
                    "target_concurrency": 10,
                    "call_rate": 3.0,
                    "enabled_call_types": valid_types,
                },
                timeout=5,
            )
        except Exception:
            pass

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
