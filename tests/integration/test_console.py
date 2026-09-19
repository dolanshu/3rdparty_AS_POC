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

_EXTERNAL_SCRIPT = re.compile(r"<script[^>]*\bsrc\s*=", re.IGNORECASE)
_EXTERNAL_LINK = re.compile(r"<link[^>]*\bhref\s*=", re.IGNORECASE)


def test_console_page_has_no_third_party_front_end_libraries() -> None:
    """ACC-M3-001: no external ``<script src>`` or ``<link href>`` in the page.

    REQ-NF-010: the demo works offline with no third-party front-end libraries.
    """
    assert not _EXTERNAL_SCRIPT.search(CONSOLE_PAGE), "external <script src> found"
    assert not _EXTERNAL_LINK.search(CONSOLE_PAGE), "external <link href> found"


def test_console_page_contains_operations_ui_elements() -> None:
    """ACC-M3-001: the page has the four AGENT.md 4.4 UI surfaces.

    Checks for: dark theme colour, status bar (peer/version/uptime/calls),
    left navigation (Call Trace / Rules / Configuration / Statistics / About),
    live message flow with direction colour coding, rule-hit highlighting,
    statistics bars, and an inline SVG topology.
    """
    page = CONSOLE_PAGE
    # Dark operations-console theme.
    assert "#0d1117" in page, "dark background not found"
    # Status bar: peer state, version, uptime, call counters.
    for label in ("uptime", "calls", "peers", "ver"):
        assert label in page, f"status-bar item '{label}' not found"
    # Left navigation with the M3 views plus the P8 Screening view.
    for nav in ("Call Trace", "Rules", "Screening", "Configuration", "Statistics", "About"):
        assert nav in page, f"navigation item '{nav}' not found"
    # Live message flow: direction colour coding (inbound/outbound/internal).
    for var in ("--in", "--out", "--int"):
        assert var in page, f"direction colour variable '{var}' not found"
    # Rule-hit highlighting.
    assert "--rule" in page, "rule-hit colour not found"
    assert "rule_id" in page, "rule_id rendering not found"
    # Statistics: bar chart containers for dispositions and rule hits.
    assert "dispC" in page, "statistics bar chart not found"
    assert "rhC" in page, "rule hits chart not found"
    # Inline SVG topology.
    assert "<svg" in page, "SVG topology not found"
    assert "S-SBC" in page, "S-SBC node not found in topology"
    assert "AS" in page, "AS node not found in topology"


def test_console_page_injects_as_api_url() -> None:
    """The configured AS API URL is injected into the page at request time."""
    assert "__AS_API_URL__" in CONSOLE_PAGE, "AS API URL placeholder missing"
    rendered = CONSOLE_PAGE.replace("__AS_API_URL__", "http://10.0.0.1:9999")
    assert "http://10.0.0.1:9999" in rendered
    assert "__AS_API_URL__" not in rendered


def test_console_page_carries_the_screening_and_instance_surfaces() -> None:
    """P8: the second AS surface is on the one shared page (LLD section 9.10).

    The console is one page for both instances, so it needs the Screening view (the block and
    allow lists plus the screening parameters), the verdict chart in Statistics, and the
    instance identity in the status bar and the document title — the page must say which AS
    it is displaying, and read that identity from ``/healthz`` rather than infer it from a
    port.
    """
    page = CONSOLE_PAGE
    # The navigation entry and the Screening view it selects.
    assert 'data-v="screening"' in page, "Screening navigation entry not found"
    for element in ("vw-screening", "scrC", "blT", "alT"):
        assert element in page, f"screening view element '{element}' not found"
    # Verdict chart in the statistics view.
    assert "vcC" in page, "verdict chart container not found"
    assert "Verdicts" in page, "verdict chart label not found"
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
    """ACC-M3-001: the console process serves the page; no third-party libraries.

    The console is a separate process (ADR-0002) that reaches the AS through its
    internal API. The served page contains no external script or stylesheet
    references (REQ-NF-010).
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
        assert not _EXTERNAL_SCRIPT.search(body), "external <script src> in served page"
        assert not _EXTERNAL_LINK.search(body), "external <link href> in served page"
        # The AS API URL must be injected, not left as a placeholder.
        assert "__AS_API_URL__" not in body, "AS API URL placeholder not replaced"
        assert as_api_url in body, "AS API URL not injected into served page"
    finally:
        if console_proc is not None:
            _terminate(console_proc)
        _terminate(as_proc)
