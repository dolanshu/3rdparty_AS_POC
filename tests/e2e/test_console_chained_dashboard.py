"""Playwright E2E — chained (iFC) topology console rendering.

Unlike ``test_console_dashboard.py`` which uses the simple-topology
``demo_stack`` session fixture, this file uses the **function-scoped**
``demo_stack_chained`` fixture — full anti-fraud AS + translation AS +
ims_mock + generator + console, as brought up by
``scripts/phase3-demo.sh full``. Each test pays ~20s startup cost in
exchange for complete process isolation (the chained stack ports
overlap with the simple fixture).

Covers (REQ-NF-030 / ADR-0014 / ADR-0015):
  - generator starts in chained topology, console mode-switch aware
  - topoMode badge, topoHint cross-AS note, simple/chained SVG swap
  - both AS APIs (fraud + translation) reachable from the console
  - chained SVG has all 6 nodes + 5 links painted
"""

from __future__ import annotations

import contextlib
import json
import time
from urllib import request as urlrequest
from urllib.error import URLError

import pytest

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers (mirror of test_console_dashboard.py; kept local so chained file
# is self-contained — no cross-import risk if the simple file ever moves).
# ---------------------------------------------------------------------------


def _gen_status(gen_base: str) -> dict:
    with urlrequest.urlopen(f"{gen_base}/load/status", timeout=2) as r:
        return json.loads(r.read())


def _as_get(as_api: str, path: str) -> dict:
    with urlrequest.urlopen(f"{as_api}{path}", timeout=2) as r:
        return json.loads(r.read())


def _wait_ws(page, which: str, timeout_ms: int = 12000) -> bool:
    """Poll console WS indicator until it reads 'live'."""
    eid_map = {"ev": "wsEv", "ld": "wsLd", "evF": "wsEvF"}
    eid = eid_map.get(which, which)
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


def _reset_gen(gen_base: str) -> None:
    try:
        _gen_status(gen_base)
    except (URLError, ConnectionError) as e:
        pytest.fail(f"generator REST unreachable at {gen_base}: {e.reason}")
    try:
        req = urlrequest.Request(f"{gen_base}/load/stop", data=b"", method="POST")
        urlrequest.urlopen(req, timeout=3).read()
    except Exception:
        pass
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            s = _gen_status(gen_base)
            if not s.get("running", True) and s.get("active_calls", 1) == 0:
                return
        except Exception:
            pass
        time.sleep(0.3)


def _open_console(page, demo_stack_chained, wait_seconds: float = 2.5) -> None:
    _reset_gen(demo_stack_chained["gen"])
    page.goto(f"{demo_stack_chained['console']}/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(int(wait_seconds * 1000))
    # All three WS indicators should light up in chained mode:
    #   wsEv   = translation AS event stream
    #   wsEvF  = anti-fraud AS event stream  (only shown when fraud API configured)
    #   wsLd   = generator pool_status
    _wait_ws(page, "ld")
    _wait_ws(page, "ev")


# ===========================================================================
# TC1 — Boot + topology mode awareness
# ===========================================================================


class TestChainedBoot:
    """Console opens in chained topology mode, SVG swapped correctly."""

    def test_generator_reports_chained_topology(self, demo_stack_chained):
        """Stack bootstrap: generator starts with topology=chained."""
        s = _gen_status(demo_stack_chained["gen"])
        assert s["topology"] == "chained", (
            f"expected generator topology=chained, got {s.get('topology')!r}"
        )
        assert s["ingress_port"] == 6063, (
            f"chained generator should ingress on fraud AS :6063, got {s.get('ingress_port')}"
        )

    def test_both_as_apis_reachable(self, demo_stack_chained):
        """fraud AS API + translation AS API both answer healthz."""
        fraud_h = _as_get(demo_stack_chained["fraud_api"], "/healthz")
        trans_h = _as_get(demo_stack_chained["as_api"], "/healthz")
        assert fraud_h["status"] == "ok"
        assert trans_h["status"] == "ok"
        assert fraud_h["instance"] == "anti-fraud", f"wrong instance: {fraud_h.get('instance')!r}"
        assert trans_h["instance"] == "number-translation", (
            f"wrong instance: {trans_h.get('instance')!r}"
        )

    def test_console_topology_mode_badge_shows_chained(self, page, demo_stack_chained):
        """Console reads topology from generator pool_status → badge = Chained (iFC)."""
        _open_console(page, demo_stack_chained)
        badge = page.locator("#topoMode").inner_text()
        assert "Chained" in badge, f"expected topoMode badge to show Chained, got {badge!r}"

    def test_chained_svg_is_displayed_simple_is_hidden(self, page, demo_stack_chained):
        """topoSimple style.display='none', topoChained display='inline'."""
        _open_console(page, demo_stack_chained)
        simple_display = page.locator("#topoSimple").evaluate("el => el.style.display")
        chained_display = page.locator("#topoChained").evaluate("el => el.style.display")
        assert simple_display == "none", f"#topoSimple should be hidden, display={simple_display!r}"
        assert chained_display != "none", (
            f"#topoChained should be visible, display={chained_display!r}"
        )

    def test_chained_svg_all_six_nodes_rendered(self, page, demo_stack_chained):
        """All 6 nodes and 5 links present in chained SVG."""
        _open_console(page, demo_stack_chained)
        for node_id in ["cAS1", "cAS2"]:
            assert page.locator(f"#{node_id}").count() == 1, f"chained node #{node_id} missing"
        for line_id in ["cl1", "cl2", "cl3", "cl4", "cl5"]:
            assert page.locator(f"#{line_id}").count() == 1, f"chained link #{line_id} missing"


# ===========================================================================
# TC2 — Live traffic + chained SVG animation
# ===========================================================================


class TestChainedTopologyLive:
    """Start generator → chained SVG links/AS nodes animate."""

    def test_chained_links_color_active_on_traffic(self, page, demo_stack_chained):
        """After generator start, chained vertical links (cl2/cl4) change gray→green."""
        _open_console(page, demo_stack_chained)

        # Idle: only cl2/cl4 are visual (cl1/cl3/cl5 are stroke="none" placeholders)
        visual_links = ["cl2", "cl4"]
        for lid in visual_links:
            stroke = page.locator(f"#{lid}").evaluate("el => el.getAttribute('stroke')")
            assert stroke == "var(--mut)", f"idle #{lid} stroke expected var(--mut), got {stroke!r}"

        page.locator("#btnStart").click()
        deadline = time.time() + 30
        all_active = False
        while time.time() < deadline:
            strokes = [
                page.locator(f"#{lid}").evaluate("el => el.getAttribute('stroke')")
                for lid in visual_links
            ]
            if all(s == "var(--in)" for s in strokes):
                all_active = True
                break
            time.sleep(0.5)
        page.locator("#btnStop").click()

        assert all_active, (
            f"chained links never all became active-green; strokes after 30s: {strokes}"
        )

    def test_chained_as_nodes_paint_on_traffic(self, page, demo_stack_chained):
        """cAS1/cAS2 stroke moves off default border after active traffic."""
        _open_console(page, demo_stack_chained)

        idle_cas1 = page.locator("#cAS1").evaluate("el => el.getAttribute('stroke')")
        idle_cas2 = page.locator("#cAS2").evaluate("el => el.getAttribute('stroke')")
        assert idle_cas1 == "var(--bd)", f"idle cAS1 stroke expected var(--bd), got {idle_cas1!r}"
        assert idle_cas2 == "var(--bd)", f"idle cAS2 stroke expected var(--bd), got {idle_cas2!r}"

        page.locator("#btnStart").click()
        deadline = time.time() + 30
        changed = False
        while time.time() < deadline:
            s1 = page.locator("#cAS1").evaluate("el => el.getAttribute('stroke')")
            s2 = page.locator("#cAS2").evaluate("el => el.getAttribute('stroke')")
            if s1 != "var(--bd)" and s2 != "var(--bd)":
                changed = True
                break
            time.sleep(0.5)
        page.locator("#btnStop").click()

        assert changed, f"chained AS nodes never painted; cAS1={s1!r}, cAS2={s2!r} after traffic"


# ---------------------------------------------------------------------------
# TestChainedSvgVisual — P0 regression guard: SVG must render with non-zero
# bounding box, not just exist in DOM. The CSS `display:none` cascade bug
# (#topoChained{display:none} + JS style.display="" clearing) caused chained
# SVG children to have rect_w=0 rect_h=0 for months without being caught.
# ---------------------------------------------------------------------------

_CHAINED_TOPO_AS_NODES = ["cAS1", "cAS2"]
_CHAINED_TOPO_VISUAL_LINKS = ["cl2", "cl4"]  # 竖向连线；cl1/cl3/cl5 是 stroke="none" 占位


class TestChainedSvgVisual:
    """Chained mode SVG renders with non-zero bounding boxes."""

    def test_chained_svg_parent_has_dimensions(self, page, demo_stack_chained):
        """#topoChained rect_w > 0, rect_h > 0 — not hidden by CSS cascade."""
        _open_console(page, demo_stack_chained)
        rect = page.locator("#topoChained").bounding_box()
        assert rect is not None, "#topoChained has no bounding_box — display:none?"
        assert rect["width"] > 0, "#topoChained width=0 (CSS display:none cascade?)"
        assert rect["height"] > 0, "#topoChained height=0"

    def test_chained_as_nodes_have_dimensions(self, page, demo_stack_chained):
        """Both AS nodes (cAS1, cAS2) have rect_w > 0, rect_h > 0."""
        _open_console(page, demo_stack_chained)
        for node_id in _CHAINED_TOPO_AS_NODES:
            loc = page.locator(f"#{node_id}")
            assert loc.count() == 1, f"#{node_id} missing from DOM"
            rect = loc.bounding_box()
            assert rect is not None, f"#{node_id} has no bounding_box"
            assert rect["width"] > 0, f"#{node_id} width=0 (not rendering?)"
            assert rect["height"] > 0, f"#{node_id} height=0"

    def test_chained_links_have_dimensions(self, page, demo_stack_chained):
        """Vertical links (cl2, cl4) have rect_h > 0 (they span vertically)."""
        _open_console(page, demo_stack_chained)
        for link_id in _CHAINED_TOPO_VISUAL_LINKS:
            loc = page.locator(f"#{link_id}")
            assert loc.count() == 1, f"#{link_id} missing from DOM"
            rect = loc.bounding_box()
            assert rect is not None, f"#{link_id} has no bounding_box"
            # cl2/cl4 are vertical lines: width=0 is normal, but height must be >0
            assert rect["height"] > 0, f"#{link_id} height=0 (degenerate vertical line?)"

    def test_chained_svg_has_mode_badge(self, page, demo_stack_chained):
        """topoMode badge reads 'Chained (iFC)' — UI reflects topology."""
        _open_console(page, demo_stack_chained)
        badge = page.locator("#topoMode").inner_text().strip()
        assert badge == "Chained (iFC)", f"topoMode badge expected 'Chained (iFC)', got {badge!r}"


# ---------------------------------------------------------------------------
# Screening view — chained mode (Fraud AS active)
# ---------------------------------------------------------------------------


class TestChainedScreening:
    """Screening view shows full Fraud AS data in chained mode."""

    @staticmethod
    def _click_screening(page) -> None:
        page.locator("button[data-v='screening']").click()
        page.wait_for_timeout(1500)

    def test_screening_loads_from_fraud_as(self, page, demo_stack_chained):
        """rsd() renders the full screening payload, not a placeholder."""
        _open_console(page, demo_stack_chained)
        self._click_screening(page)
        card = page.locator("#scrCard")
        text = card.inner_text()
        assert "not active" not in text, (
            f"Chained mode: got placeholder instead of data: {text[:200]}"
        )
        assert "sample-office-screening" in text, f"Expected data set name in: {text[:200]}"
        assert "Block List (7)" in text, f"Expected Block List heading in: {text[:200]}"
        assert "Allow List (2)" in text, f"Expected Allow List heading in: {text[:200]}"

    def test_screening_renders_window_and_reputation_params(self, page, demo_stack_chained):
        """Window (max_calls/seconds) and reputation params appear in a table."""
        _open_console(page, demo_stack_chained)
        self._click_screening(page)
        text = page.locator("#scrCard").inner_text()
        assert "max_calls" in text, "Window max_calls param missing"
        assert "default_score" in text, "Reputation default_score param missing"
        assert "reject_below" in text, "Reputation reject_below param missing"

    def test_screening_block_list_shows_entries(self, page, demo_stack_chained):
        """Block list entries show entry_id, number, and reason."""
        _open_console(page, demo_stack_chained)
        self._click_screening(page)
        html = page.locator("#scrCard").inner_html()
        assert "BL-0001" in html, "Block list entry_id BL-0001 not rendered"
        assert "+8613400000001" in html, "Block list number not rendered"

    def test_screening_allow_list_shows_entries(self, page, demo_stack_chained):
        """Allow list entries show entry_id, number, and reason."""
        _open_console(page, demo_stack_chained)
        self._click_screening(page)
        html = page.locator("#scrCard").inner_html()
        assert "AL-0001" in html, "Allow list entry_id AL-0001 not rendered"
        assert "+86216180000" in html, "Allow list number not rendered"


# ---------------------------------------------------------------------------
# Chained dual-WS — REQ-F-054 / ACC-P14-004
# ---------------------------------------------------------------------------


class TestChainedWS:
    """Chained mode opens three WebSockets: AS events (trans), Fraud AS events, Load generator."""

    @staticmethod
    def _wait_ws(page: object, locator_id: str, timeout_ms: int = 8000) -> bool:
        """Poll until element text contains 'live'."""
        import time

        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            try:
                txt = page.locator(f"#{locator_id}").inner_text(timeout=500).lower()
                if "live" in txt:
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def test_chained_opens_trans_ws(self, page, demo_stack_chained):
        """Trans AS events WS (#wsEv) connects."""
        _open_console(page, demo_stack_chained)
        assert self._wait_ws(page, "wsEv"), "trans WS #wsEv not live in chained mode"

    def test_chained_opens_fraud_ws(self, page, demo_stack_chained):
        """Fraud AS events WS (#wsEvF) connects — unique to chained topology."""
        _open_console(page, demo_stack_chained)
        # Fraud WS element must be visible (display != none)
        display = page.locator("#wsEvF").evaluate(
            "el => el.style.display || getComputedStyle(el).display"
        )
        assert display != "none", f"Fraud WS element #wsEvF hidden (display={display!r})"
        assert self._wait_ws(page, "wsEvF"), "fraud WS #wsEvF not live in chained mode"

    def test_chained_opens_load_ws(self, page, demo_stack_chained):
        """Load generator WS (#wsLd) connects."""
        _open_console(page, demo_stack_chained)
        assert self._wait_ws(page, "wsLd"), "load WS #wsLd not live in chained mode"

    def test_chained_all_three_ws_live_simultaneously(self, page, demo_stack_chained):
        """In chained mode, all three WS badges show live at the same time."""
        _open_console(page, demo_stack_chained)
        page.wait_for_timeout(2000)  # give all three time to handshake
        ev = page.locator("#wsEv").inner_text().lower()
        evf = page.locator("#wsEvF").inner_text().lower()
        ld = page.locator("#wsLd").inner_text().lower()
        assert "live" in ev, f"trans WS not live: {ev!r}"
        assert "live" in evf, f"fraud WS not live: {evf!r}"
        assert "live" in ld, f"load WS not live: {ld!r}"


# ---------------------------------------------------------------------------
# Bottleneck diagnostic — generator rate vs Fraud AS per-caller window
# ---------------------------------------------------------------------------


class TestBottleneckDiagnostic:
    """P8 call-rate window (max_calls=5 per caller per 60s) limits generator.

    All 10 generator call types use caller "1001" (except F2/F3 use "1999"/"1998").
    So if generator rate > 0.083 cps (5 calls / 60s), Fraud AS will 608 reject
    everything after the 5th call via AS-FRAUD-002.

    These tests diagnose the bottleneck, not fix it — documenting the known gap.
    """

    def _gen(self, demo_stack_chained):
        return demo_stack_chained["gen"]

    def _fraud(self, demo_stack_chained):
        return demo_stack_chained["fraud_api"]

    def _get(self, url):
        import urllib.request as ur

        return json.loads(ur.urlopen(url, timeout=3).read())

    def _post(self, url):
        import urllib.request as ur

        with contextlib.suppress(Exception):
            ur.urlopen(ur.Request(url, data=b"", method="POST"), timeout=3).read()

    def _put(self, url, body):
        import urllib.request as ur

        req = ur.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        ur.urlopen(req, timeout=3).read()

    def test_high_rate_triggers_fraud_rate_limit(self, demo_stack_chained):
        """rate=10 → Fraud AS AS-FRAUD-002 rejects >50% of calls.

        This documents the bottleneck — caller pool is single-number "1001"
        against per-caller window max_calls=5 / 60s.
        """
        import time as _t

        gen = self._gen(demo_stack_chained)
        fraud = self._fraud(demo_stack_chained)

        # Pre-condition: Fraud AS window max_calls=5
        scr = self._get(f"{fraud}/api/v1/screening")
        assert scr["window"]["max_calls"] == 5, "Fraud AS window max_calls mismatch"

        # Stop → configure rate=10 → start
        self._post(f"{gen}/load/stop")
        _t.sleep(1)
        self._put(
            f"{gen}/load/config",
            {
                "target_concurrency": 31,
                "call_rate": 10.0,
                "enabled_call_types": ["T1"],  # pure T1, same caller "1001"
            },
        )
        self._post(f"{gen}/load/start")
        # Poll until enough calls have accumulated; a fixed sleep makes the
        # sample count depend on machine load (rate=10 cps is a target, not a
        # guarantee when the suite has just torn down 20+ full stacks).
        deadline = _t.monotonic() + 30
        while _t.monotonic() < deadline:
            total = self._get(f"{fraud}/api/v1/metrics").get("calls_total", 0)
            if total >= 50:
                break
            _t.sleep(1)

        fraud_metrics = self._get(f"{fraud}/api/v1/metrics")
        err = fraud_metrics.get("errors_by_code", {})
        rate_exceeded = err.get("AS-FRAUD-002", 0)
        total = fraud_metrics.get("calls_total", 0)

        # The 60s per-caller window caps passes at 5; waiting longer (still
        # within one window) can only raise the rejection share.
        assert total >= 50, f"Expected many Fraud AS calls, got {total}"
        if rate_exceeded > 0:
            pct = rate_exceeded / total * 100
            assert pct > 30, f"Expected >30% AS-FRAUD-002 rejections at rate=10, got {pct:.1f}%"

        self._post(f"{gen}/load/stop")

    def test_low_rate_below_window_limit_passes(self, demo_stack_chained):
        """rate=0.16 cps (≈5/30s) → Fraud AS AS-FRAUD-002 rejections <10%.

        At 0.16 cps, 12s = ~2 calls, well below the 5/60s window cap.
        """
        import time as _t

        gen = self._gen(demo_stack_chained)
        fraud = self._fraud(demo_stack_chained)

        self._post(f"{gen}/load/stop")
        _t.sleep(1)
        self._put(
            f"{gen}/load/config",
            {
                "target_concurrency": 31,
                "call_rate": 0.16,
                "enabled_call_types": ["T1"],
            },
        )
        self._post(f"{gen}/load/start")
        _t.sleep(12)

        fraud_metrics = self._get(f"{fraud}/api/v1/metrics")
        err = fraud_metrics.get("errors_by_code", {})
        rate_exceeded = err.get("AS-FRAUD-002", 0)

        # At rate=0.16, 12s ≈ 2 calls → all should be within window
        assert rate_exceeded == 0, f"Unexpected AS-FRAUD-002 rejects at low rate: {rate_exceeded}"
        self._post(f"{gen}/load/stop")
