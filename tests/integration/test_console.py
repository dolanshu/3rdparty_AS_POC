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

"""Integration tests for the M3 console and internal API.

Covers:

- ACC-M3-001: the console page has live flow, rule hit, statistics and topology;
  no third-party front-end libraries (no external ``<script src>`` or
  ``<link href>``); the console runs as a separate process.
- ACC-M3-002: the internal API serves health, metrics, rules and traces
  (``curl -s http://127.0.0.1:<port>/healthz`` -> ``{"status":"ok",...}``).
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from console.main import CONSOLE_PAGE

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _free_tcp_port() -> int:
    """Reserve a free TCP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_http(url: str, timeout_seconds: float = 15.0) -> bytes:
    """Poll a URL until it responds, then return the body.

    Args:
        url: URL to poll.
        timeout_seconds: How long to keep polling.

    Returns:
        The response body.

    Raises:
        TimeoutError: When the endpoint never came up.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.read()
        except OSError as exc:
            last_error = exc
            time.sleep(0.15)
    raise TimeoutError(f"{url} never came up: {last_error}")


def _start_as(repo_root: Path, rules_file: Path, api_port: int, tmp_path: Path) -> subprocess.Popen:
    """Start the AS process with its internal API on ``api_port``.

    Args:
        repo_root: Repository root for the working directory.
        rules_file: Path of the routing rules file.
        api_port: TCP port for the internal API.
        tmp_path: Temporary directory for logs.

    Returns:
        The started ``subprocess.Popen`` object.
    """
    environment = dict(os.environ)
    environment.update(
        {
            "SIP_LISTEN_ADDRESS": "127.0.0.1",
            "SIP_LISTEN_PORT": str(_free_udp_port()),
            "SBC_PEER_ADDRESS": "127.0.0.1",
            "SBC_PEER_PORT": str(_free_udp_port()),
            "ALLOWED_PEERS": "127.0.0.1",
            "RULES_FILE": str(rules_file),
            "INTERNAL_API_ADDRESS": "127.0.0.1",
            "INTERNAL_API_PORT": str(api_port),
            "LOG_LEVEL": "WARNING",
            "LOG_STRUCTURED": "true",
            "LOG_PAYLOADS": "false",
        }
    )
    log = tmp_path / "as.log"
    log_handle = log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "as_app.main"],
        cwd=repo_root,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    return process


def _start_console(
    repo_root: Path, as_api_url: str, console_port: int, tmp_path: Path
) -> subprocess.Popen:
    """Start the console process as a separate process (ADR-0002).

    Args:
        repo_root: Repository root for the working directory.
        as_api_url: URL of the AS internal API the console should reach.
        console_port: TCP port for the console web server.
        tmp_path: Temporary directory for logs.

    Returns:
        The started ``subprocess.Popen`` object.
    """
    log = tmp_path / "console.log"
    log_handle = log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "console.main",
            "--address",
            "127.0.0.1",
            "--port",
            str(console_port),
            "--as-api-url",
            as_api_url,
        ],
        cwd=repo_root,
        env=dict(os.environ),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    return process


def _terminate(process: subprocess.Popen) -> None:
    """Send SIGTERM and kill if it doesn't exit.

    Args:
        process: The process to terminate.
    """
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


# ---------------------------------------------------------------------------
# ACC-M3-001: console page content (fast, in-process)
# ---------------------------------------------------------------------------

_SCRIPT_SRC = re.compile(r'<script[^>]*\bsrc\s*=\s*"([^"]+)"', re.IGNORECASE)
_EXTERNAL_LINK = re.compile(r"<link[^>]*\bhref\s*=", re.IGNORECASE)


def test_console_page_has_only_vendored_static_scripts() -> None:
    """ACC-P13-006: all ``<script src>`` point to ``/static/`` (vendored).

    REQ-F-050 / ADR-0011: Chart.js is vendored under /static/. No CDN or
    external references; no ``<link href>`` to external resources.
    """
    import re

    scripts = re.findall(r'<script[^>]*\bsrc\s*=\s*"([^"]+)"', CONSOLE_PAGE, re.IGNORECASE)
    assert scripts, "expected at least one <script src> (vendored Chart.js)"
    for src in scripts:
        assert src.startswith("/static/"), f"script not under /static/: {src}"
    links = re.findall(r'<link[^>]*\bhref\s*=\s*"([^"]+)"', CONSOLE_PAGE, re.IGNORECASE)
    assert not links, f"external <link href> found: {links}"


def test_console_page_has_chartjs_canvases() -> None:
    """REQ-F-045/046/047: three chart canvases — line, pie, gauge."""
    assert "lineChart" in CONSOLE_PAGE, "line chart canvas missing (REQ-F-045)"
    assert "pieChart" in CONSOLE_PAGE, "pie/doughnut chart canvas missing (REQ-F-046)"
    assert "gaugeChart" in CONSOLE_PAGE, "capacity gauge canvas missing (REQ-F-047)"
    assert "chart.umd.min.js" in CONSOLE_PAGE, "Chart.js UMD bundle not referenced"


def test_console_page_contains_operations_ui_elements() -> None:
    """ACC-M3-001 / ACC-P13-001..004: the enhanced console UI surfaces.

    P13 Dashboard layout: dark theme, status bar (instance/ver/uptime/calls/
    active/target + WS indicators), left nav (Dashboard/Call Trace/Rules/
    Screening/Statistics/About + load generator controls), centre panel
    (line chart + gauge), right panel (pie chart + SVG topology with 4 nodes),
    bottom trace panel. Direction colour coding preserved.
    """
    page = CONSOLE_PAGE
    # Dark operations-console theme.
    assert "#0d1117" in page, "dark background not found"
    # Status bar: instance, version, uptime, calls, active, target.
    for label in ("uptime", "calls", "ver", "instance", "active", "target"):
        assert label in page, f"status-bar item '{label}' not found"
    # Left navigation: Dashboard is the new default, plus the legacy views.
    for nav in ("Dashboard", "Call Trace", "Rules", "Screening", "Statistics", "About"):
        assert nav in page, f"navigation item '{nav}' not found"
    assert 'data-v="dashboard"' in page, "Dashboard navigation entry not found"
    # Live message flow: direction colour coding (inbound/outbound/internal).
    for var in ("--in", "--out", "--int"):
        assert var in page, f"direction colour variable '{var}' not found"
    # Rule-hit highlighting.
    assert "--rule" in page, "rule-hit colour not found"
    # Chart.js canvases (REQ-F-045/046/047).
    assert "lineChart" in page, "line chart canvas missing (REQ-F-045)"
    assert "pieChart" in page, "pie/doughnut chart canvas missing (REQ-F-046)"
    assert "gaugeChart" in page, "capacity gauge canvas missing (REQ-F-047)"
    # SVG topology with 4 nodes (REQ-F-048): S-CSCF, Anti-fraud, Translation, core.
    assert "<svg" in page, "SVG topology not found"
    assert "S-CSCF" in page, "S-CSCF node not found in topology"
    assert "Anti-fraud" in page, "Anti-fraud node not found in topology"
    assert "Translation" in page, "Translation node not found in topology"
    # Load generator controls (REQ-F-049).
    assert "tgtSlider" in page, "target concurrency slider not found"
    assert "rateSlider" in page, "call rate slider not found"
    assert "btnStart" in page, "Start button not found"
    assert "btnStop" in page, "Stop button not found"
    # Live call trace panel.
    assert "Live Call Trace" in page, "live call trace panel not found"


def test_console_page_injects_as_api_url() -> None:
    """The configured AS API URL is injected into the page at request time."""
    assert "__AS_API_URL__" in CONSOLE_PAGE, "AS API URL placeholder missing"
    rendered = CONSOLE_PAGE.replace("__AS_API_URL__", "http://10.0.0.1:9999")
    assert "http://10.0.0.1:9999" in rendered
    assert "__AS_API_URL__" not in rendered


def test_console_page_carries_the_screening_and_instance_surfaces() -> None:
    """P8: the second AS surface is on the one shared page (LLD section 9.10).

    The console is one page for both instances, so it needs the Screening view,
    the statistics panel, and the instance identity in the status bar and the
    document title — the page must say which AS it is displaying, and read that
    identity from ``/healthz`` rather than infer it from a port.
    """
    page = CONSOLE_PAGE
    # The navigation entry and the Screening view it selects.
    assert 'data-v="screening"' in page, "Screening navigation entry not found"
    assert "vw-screening" in page, "screening view container not found"
    assert "scrCard" in page, "screening card container not found"
    # Statistics panel (P13 simplified: statsCard with total + disposition).
    assert "vw-statistics" in page, "statistics view container not found"
    assert "statsCard" in page, "statistics card container not found"
    # Instance identity: a status-bar chip and the document title both read /healthz.
    assert 'id="aInst"' in page, "instance status-bar chip not found"
    assert "hd.instance" in page, "the instance identity is not read from /healthz"
    assert "document.title" in page, "the page title is not set from the instance identity"


# ---------------------------------------------------------------------------
# ACC-M3-002: internal API serves health, metrics, rules and traces
# ---------------------------------------------------------------------------


def test_internal_api_serves_health_metrics_rules_and_traces(
    rules_file: Path, repo_root: Path, tmp_path: Path
) -> None:
    """ACC-M3-002: the internal API serves health, metrics, rules and traces.

    REQ-F-011: the AS exposes its internal state through a REST API.
    """
    api_port = _free_tcp_port()
    as_proc = _start_as(repo_root, rules_file, api_port, tmp_path)
    try:
        _wait_for_http(f"http://127.0.0.1:{api_port}/healthz")

        # GET /healthz -> {"status":"ok", ...}
        with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/healthz", timeout=5) as resp:
            health = json.loads(resp.read().decode())
        assert health["status"] == "ok"
        assert health["rule_set_loaded"] is True
        assert "version" in health
        assert health["uptime_seconds"] >= 0.0

        # GET /api/v1/metrics
        with urllib.request.urlopen(
            f"http://127.0.0.1:{api_port}/api/v1/metrics", timeout=5
        ) as resp:
            metrics = json.loads(resp.read().decode())
        assert "calls_total" in metrics
        assert "calls_by_disposition" in metrics
        assert "peer_status" in metrics

        # GET /api/v1/rules
        with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/v1/rules", timeout=5) as resp:
            rules = json.loads(resp.read().decode())
        assert "rules" in rules
        assert len(rules["rules"]) >= 1
        assert "next_hops" in rules
        assert len(rules["next_hops"]) >= 1

        # GET /api/v1/traces (empty when no calls have been made)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{api_port}/api/v1/traces", timeout=5
        ) as resp:
            traces = json.loads(resp.read().decode())
        assert "calls" in traces
        assert isinstance(traces["calls"], list)

        # GET /api/v1/traces/{call_id} (unknown Call-ID returns empty events)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{api_port}/api/v1/traces/no-such-call", timeout=5
        ) as resp:
            trace = json.loads(resp.read().decode())
        assert trace["call_id"] == "no-such-call"
        assert trace["events"] == []
    finally:
        _terminate(as_proc)


# ---------------------------------------------------------------------------
# ACC-M3-001: console runs as a separate process (full stack)
# ---------------------------------------------------------------------------


def test_console_runs_as_separate_process_with_no_external_refs(
    rules_file: Path, repo_root: Path, tmp_path: Path
) -> None:
    """ACC-M3-001 / ACC-P13-006: console process serves the page; only vendored scripts.

    The console is a separate process (ADR-0002) that reaches the AS through its
    internal API. All ``<script src>`` point to ``/static/`` (vendored, ADR-0011);
    no external ``<link href>`` references (REQ-NF-010).
    """
    api_port = _free_tcp_port()
    console_port = _free_tcp_port()
    as_api_url = f"http://127.0.0.1:{api_port}"
    as_proc = _start_as(repo_root, rules_file, api_port, tmp_path)
    console_proc: subprocess.Popen | None = None
    try:
        _wait_for_http(f"http://127.0.0.1:{api_port}/healthz")
        console_proc = _start_console(repo_root, as_api_url, console_port, tmp_path)
        page_bytes = _wait_for_http(f"http://127.0.0.1:{console_port}/healthz")
        health = json.loads(page_bytes.decode())
        assert health["status"] == "ok"
        assert health["component"] == "console"

        # Fetch the operations page.
        with urllib.request.urlopen(f"http://127.0.0.1:{console_port}/", timeout=5) as resp:
            body = resp.read().decode()
        assert "<svg" in body, "SVG topology not in served page"
        assert "Call Trace" in body, "navigation not in served page"
        # All <script src> must be vendored under /static/ (ADR-0011, REQ-F-050).
        scripts = _SCRIPT_SRC.findall(body)
        assert scripts, "expected at least one <script src> (vendored Chart.js)"
        for src in scripts:
            assert src.startswith("/static/"), f"script not under /static/: {src}"
        assert not _EXTERNAL_LINK.search(body), "external <link href> in served page"
        # The AS API URL must be injected, not left as a placeholder.
        assert "__AS_API_URL__" not in body, "AS API URL placeholder not replaced"
        assert as_api_url in body, "AS API URL not injected into served page"
        # Vendored Chart.js serves correctly.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{console_port}/static/chart.umd.min.js", timeout=5
        ) as resp:
            chart_js = resp.read()
        assert len(chart_js) > 10000, "vendored Chart.js seems too small"
        assert b"Chart.js" in chart_js or b"chart.js" in chart_js.lower(), (
            "vendored Chart.js content not recognised"
        )
    finally:
        if console_proc is not None:
            _terminate(console_proc)
        _terminate(as_proc)
