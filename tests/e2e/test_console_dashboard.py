"""Playwright E2E for P13 Enhanced Console Dashboard.

Three layers — Smoke (4) → Core (10) → Regressions (3) — total 17 tests.

Run order matters because each layer builds on the previous.
Run with the system python (has pytest-playwright):

    python3 -m pytest tests/e2e/ -v
    python3 -m pytest tests/e2e/ -v -k smoke
"""

from __future__ import annotations

import json
import time
from urllib import request as urlrequest

import pytest

# Generator-idle helper from conftest (pytest auto-loads)
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from conftest import _reset_gen  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gen_status(base_url: str) -> dict:
    """Fetch generator /load/status as JSON."""
    with urlrequest.urlopen(f"{base_url}/load/status", timeout=3) as r:
        return json.loads(r.read())



def _wait_ws(page, which="ev", timeout=8000):
    """Wait for a specific WebSocket indicator (ev=event ws, ld=load ws)."""
    import time as _t
    deadline = _t.time() + timeout / 1000
    id_map = {"ev": "wsEv", "ld": "wsLd"}
    eid = id_map.get(which, which)
    while _t.time() < deadline:
        txt = page.locator(f"#{eid}").inner_text()
        if "live" in txt:
            return True
        _t.sleep(0.2)
    return False

def _poll_gauge(page, timeout=10000):
    """Wait until gauge shows 0/X."""
    import time as _t
    deadline = _t.time() + timeout / 1000
    while _t.time() < deadline:
        if page.locator("#gaugeVal").inner_text().startswith("0 /"):
            return True
        _t.sleep(0.3)
    return False



def _click_visible(page, selector: str, timeout: int = 5000) -> None:
    page.locator(selector).wait_for(state="visible", timeout=timeout)
    page.click(selector)


def _get_line_labels_len(page) -> int:
    return page.evaluate(
        "() => Chart.getChart(document.getElementById('lineChart')).data.labels.length"
    )


def _get_line_active_data(page) -> list:
    return page.evaluate(
        "() => Chart.getChart(document.getElementById('lineChart')).data.datasets[0].data"
    )


# ===========================================================================
# SMOKE LAYER — 基础连通性
# ===========================================================================

class TestSmoke:
    def test_page_loads_without_js_errors(self, page, demo_stack):
        """S1 — 无 pageerror，Chart.js 4.4.8 加载成功，3 个 chart 实例。"""
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)
        chart_ok = page.evaluate(
            "() => typeof Chart === 'function' && Chart.version === '4.4.8'"
        )
        assert chart_ok, f"Chart.js wrong: {errors}"
        n = page.evaluate("() => Object.keys(Chart.instances).length")
        assert n == 3, f"Chart.instances count={n} (expected 3)"
        assert len(errors) == 0, f"JS pageerrors: {errors}"

    def test_both_websockets_connect(self, page, demo_stack):
        """S2 — event ws + load ws 连成功，持续稳定。"""
        ws_urls: list[str] = []
        def _on_ws(ws):
            ws_urls.append(ws.url)
        page.on("websocket", _on_ws)
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(6000)
        assert "live" in page.locator("#wsLd").inner_text()
        assert "live" in page.locator("#wsEv").inner_text()
        page.wait_for_timeout(3000)
        assert "live" in page.locator("#wsLd").inner_text()
        assert "live" in page.locator("#wsEv").inner_text()

    def test_initial_controls_state(self, page, demo_stack):
        """S3 — 初始控件状态正确。"""
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        assert not page.locator("#btnStart").is_disabled()
        assert page.locator("#btnStop").is_disabled()
        assert "0 /" in page.locator("#gaugeVal").inner_text()

    def test_start_button_hits_rest_endpoint(self, page, demo_stack):
        """S5 — Start 按钮 → generator running=true。"""
        gen_base = demo_stack["gen"]
        _reset_gen(gen_base)
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(3000)
        assert _gen_status(gen_base).get("running") is True


# ===========================================================================
# CORE LAYER — 用户主路径
# ===========================================================================

class TestCoreUserJourney:
    def test_start_generator_actually_runs(self, page, demo_stack):
        """C1 — Start → generator 真跑。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(3000)
        s = _gen_status(demo_stack["gen"])
        assert s.get("running") is True
        assert s.get("active_calls", 0) > 0

    def test_stop_button_becomes_enabled_after_start(self, page, demo_stack):
        """C2 — Start 后 Stop 按钮变可用（曾是 bug #2）。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(3000)
        assert not page.locator("#btnStop").is_disabled(), \
            "btnStop still disabled — WS pool_status_update missing running field or wrong attribute path"

    def test_gauge_updates_live(self, page, demo_stack):
        """C3 — 仪表盘实时显示 active 值。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(3000)
        gauge_text = page.locator("#gaugeVal").inner_text()
        assert gauge_text != "0 / 10", f"gauge still idle: '{gauge_text}'"
        page.wait_for_timeout(3000)
        live = page.locator("#liveVal").inner_text()
        assert live != "0 active", f"liveVal reset to zero: '{live}'"

    def test_line_chart_accumulates_points(self, page, demo_stack):
        """C4 — 折线图有数据点推进。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(5000)
        labels_len = _get_line_labels_len(page)
        assert labels_len >= 6, f"line chart only {labels_len} labels"
        non_zero = [v for v in _get_line_active_data(page) if v > 0]
        assert len(non_zero) >= 1, "all active data points are zero"

    def test_pie_chart_counters_increment(self, page, demo_stack):
        """C5 — 饼图 counters 累加。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        _wait_ws(page, "ld")
        _wait_ws(page, "ev")
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(8000)
        pie_data = page.evaluate(
            "() => Chart.getChart(document.getElementById('pieChart')).data.datasets[0].data"
        )
        assert sum(pie_data) >= 3, f"pie chart total={sum(pie_data)}"

    def test_topology_links_change(self, page, demo_stack):
        """C6 — 拓扑链路粗细/颜色变化。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(4000)
        topo = page.evaluate("""() => ({
            sw: document.getElementById('l1').getAttribute('stroke-width'),
            val: document.getElementById('topoVal').innerText
        })""")
        assert int(topo["sw"]) > 1, f"topo sw still idle: {topo}"
        assert topo["val"] != "idle", f"topoVal still idle: {topo}"

    def test_trace_panel_has_call_records(self, page, demo_stack):
        """C8 — trace 面板有 ≥3 条通话记录。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        _wait_ws(page, "ld")
        _wait_ws(page, "ev")
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(8000)
        items = page.locator("#tlist .ti")
        assert items.count() >= 3, f"trace items={items.count()}"

    def test_stop_resets_everything_to_zero(self, page, demo_stack):
        """C10 — Stop → 全部归零。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(3000)
        _click_visible(page, "#btnStop")
        _poll_gauge(page, timeout=15000)
        assert page.locator("#gaugeVal").inner_text().startswith("0 /"),             f"gauge not reset: {page.locator('#gaugeVal').inner_text()}"
        assert page.locator("#liveVal").inner_text() == "0 active",             f"live not reset: {page.locator('#liveVal').inner_text()}"
        s = _gen_status(demo_stack["gen"])
        assert s.get("running") is False
        assert s.get("active_calls", -1) == 0

    def test_start_becomes_enabled_after_stop(self, page, demo_stack):
        """C11 — Stop 后 Start 重新可用。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart"); page.wait_for_timeout(2000)
        _click_visible(page, "#btnStop"); page.wait_for_timeout(3000)
        assert not page.locator("#btnStart").is_disabled()
        assert page.locator("#btnStop").is_disabled()

    def test_slider_change_updates_generator(self, page, demo_stack):
        """C12 — target slider 调到 30 → generator 收到 PUT /load/config。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        put_bodies: list[str] = []
        def _on_resp(resp):
            req = resp.request
            if "/load/config" in resp.url and req.method == "PUT":
                put_bodies.append(req.post_data or "")
        page.on("response", _on_resp)
        # range input can't .fill() — set via JS + dispatch change
        page.evaluate("""() => {
            var s = document.getElementById('tgtSlider');
            s.value = 30;
            s.dispatchEvent(new Event('input'));
            s.dispatchEvent(new Event('change'));
        }""")
        page.wait_for_timeout(1500)
        assert any('"target_concurrency":30' in b.replace(' ', '') for b in put_bodies), \
            f"expected PUT target_concurrency=30, got: {put_bodies[:3]}"


# ===========================================================================
# REGRESSIONS LAYER — 稳定性
# ===========================================================================

class TestRegressions:
    def test_refresh_does_not_leak_chart_instances(self, page, demo_stack):
        """R4 — 刷新 3 次，Chart.instances 始终 = 3。"""
        for _ in range(3):
            page.goto(f"{demo_stack['console']}/")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)
            n = page.evaluate("() => Object.keys(Chart.instances).length")
            assert n == 3, f"Chart.instances count={n}"

    def test_rapid_start_stop_cycles(self, page, demo_stack):
        """R6 — Start/Stop 快速连点 5 次，结束时 idle 状态。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        for _ in range(5):
            _click_visible(page, "#btnStart"); page.wait_for_timeout(1500)
            _click_visible(page, "#btnStop"); page.wait_for_timeout(2000)
        assert not page.locator("#btnStart").is_disabled()

    def test_long_run_line_chart_rolls(self, page, demo_stack):
        """R7 — Start 10s，折线图 ≤ 60 点（ROLL_WINDOW）不爆。"""
        _reset_gen(demo_stack["gen"])
        page.goto(f"{demo_stack['console']}/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)
        _click_visible(page, "#btnStart")
        page.wait_for_timeout(10000)
        labels_len = _get_line_labels_len(page)
        assert labels_len <= 60, f"grew to {labels_len}"
        assert labels_len >= 15, f"only {labels_len} after 10s"
