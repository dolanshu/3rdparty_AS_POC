"""Playwright E2E — session-scoped demo stack fixture.

Launches the full Phase 3 stack (core mock → translation AS → load generator
→ enhanced console) once per pytest session, waits for all healthz to come
up, then yields a dict of base URLs. Teardown kills everything.

Run with the system python so playwright/pytest-playwright are available,
but the spawned child processes use the project venv python (which has
sippy + as_platform + FastAPI installed).
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import signal
import socket
import subprocess
import time
from urllib import request as urlrequest

import pytest

# R3-P0-2: PROJECT_ROOT de-hardcoded — use pathlib relative to this file
PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parents[2])
VENV_PY = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")

# Corporate/WSL proxies often intercept 127.0.0.1 unless bypassed — breaks health polls.
_LOCAL_NO_PROXY_HOSTS = ("127.0.0.1", "localhost", "::1")


def _ensure_local_no_proxy() -> None:
    for var in ("NO_PROXY", "no_proxy"):
        existing = [p.strip() for p in os.environ.get(var, "").split(",") if p.strip()]
        for host in _LOCAL_NO_PROXY_HOSTS:
            if host not in existing:
                existing.append(host)
        os.environ[var] = ",".join(existing)


_ensure_local_no_proxy()


def _env_with_local_no_proxy(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for var in ("NO_PROXY", "no_proxy"):
        env[var] = os.environ.get(var, "")
    return env


# ---------------------------------------------------------------------------
# Port / health helpers
# ---------------------------------------------------------------------------


def _kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"]).decode().strip()
        for pid in out.splitlines():
            subprocess.run(["kill", "-9", pid], capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    time.sleep(0.3)


def _wait_udp_port(port: int, timeout: float = 15.0) -> bool:
    """UDP port readiness probe — fail to bind = something is listening."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", port))
            s.close()
            # bind succeeded → nobody is listening yet → retry
        except OSError:
            # bind failed (EADDRINUSE) → something is listening → good
            return True
        time.sleep(0.3)
    return False


def _wait_http(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlrequest.urlopen(url, timeout=2) as r:
                r.read()
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------

STACK_PORTS = [5061, 5060, 8080, 8765, 8081]

# M-5 / R2-P2-3: The old conftest-local _reset_gen (only checked `running`,
# 8s deadline) is confirmed DEAD CODE (grep finds only its own definition).
# The dashboard test file provides a stronger version that also waits for
# active_calls==0 and distinguishes unreachable vs. timeout.  We keep the
# dashboard file's version as the canonical one and remove this duplicate.


@pytest.fixture(scope="session")
def demo_stack(tmp_path_factory):
    """Bring up 4 processes once for the whole e2e session."""
    for p in STACK_PORTS:
        _kill_port(p)

    # N-2/N-3: use tmp_path_factory for rules file + per-process logs so
    # the session directory is cleaned up by pytest and logs don't collide
    # across parallel or repeated runs.
    session_tmp = tmp_path_factory.mktemp("e2e-stack")

    # ---- Generate a routing rules file that points every next-hop at the
    #      single core-mock UAS (port 5061). The shipped config targets six
    #      distinct ports (15061–15066), which we don't want to bring up in e2e.
    import yaml as _yaml

    _rules_src = pathlib.Path(PROJECT_ROOT) / "config" / "routing_rules.yaml"
    _rules_dst = session_tmp / "rules.yaml"
    with _rules_src.open() as _f:
        _doc = _yaml.safe_load(_f)
    for _nh in _doc.get("next_hops", []):
        _nh["port"] = 5061
    with _rules_dst.open("w") as _f:
        _yaml.safe_dump(_doc, _f, sort_keys=False, allow_unicode=True)

    env = _env_with_local_no_proxy()
    procs: list[subprocess.Popen] = []
    log_files: list = []

    def _log_path(name: str):
        h = open(session_tmp / f"{name}.log", "w")  # noqa: SIM115 — caller manages lifetime
        log_files.append(h)
        return h

    # 1. Core mock UAS  (UDP :5061 UAS, :15060 UAC trunk)
    #    --trunk-port avoids the default "listen_port - 1" = 5060, which would
    #    collide with the AS SIP port below.
    _core_log = _log_path("core-mock")
    procs.append(
        subprocess.Popen(
            [VENV_PY, "-m", "s_sbc_mock.main", "--listen-port", "5061", "--trunk-port", "15060"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=_core_log,
            stderr=subprocess.STDOUT,
        )
    )

    # 2. Translation AS  (SIP UDP :5060, API HTTP :8080)
    env_as = env.copy()
    env_as["SBC_PEER_ADDRESS"] = "127.0.0.1"
    env_as["SBC_PEER_PORT"] = "5061"
    env_as["RULES_FILE"] = str(_rules_dst)
    _as_log = _log_path("as")
    procs.append(
        subprocess.Popen(
            [VENV_PY, "-m", "as_app.main"],
            cwd=PROJECT_ROOT,
            env=env_as,
            stdout=_as_log,
            stderr=subprocess.STDOUT,
        )
    )

    # 3. Load generator  (HTTP :8765, SIP client → AS :5060)
    _gen_log = _log_path("generator")
    procs.append(
        subprocess.Popen(
            [VENV_PY, "tools/call_load_generator.py", "--as-port", "5060", "--http-port", "8765"],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=_gen_log,
            stderr=subprocess.STDOUT,
        )
    )

    # 4. Enhanced console  (HTTP :8081)
    _console_log = _log_path("console")
    procs.append(
        subprocess.Popen(
            [
                VENV_PY,
                "-m",
                "console.main",
                "--port",
                "8081",
                "--as-api-url",
                "http://127.0.0.1:8080",
                "--load-api-url",
                "http://127.0.0.1:8765",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=_console_log,
            stderr=subprocess.STDOUT,
        )
    )

    # Wait for health checks
    ok = (
        _wait_udp_port(5061, 20)
        and _wait_http("http://127.0.0.1:8080/healthz", 20)
        and _wait_http("http://127.0.0.1:8765/load/status", 20)
        and _wait_http("http://127.0.0.1:8081/healthz", 20)
    )
    if not ok:
        # tearDown and bail
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        for lf in log_files:
            lf.close()
        raise RuntimeError("demo_stack failed to come up within 20s")

    yield {
        "console": "http://127.0.0.1:8081",
        "as_api": "http://127.0.0.1:8080",
        "gen": "http://127.0.0.1:8765",
    }

    # --- teardown ---
    for p in procs:
        with contextlib.suppress(ProcessLookupError):
            p.send_signal(signal.SIGTERM)
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    for port in STACK_PORTS:
        _kill_port(port)
    # N-3: close log handles so tmp_path_factory can clean up
    for lf in log_files:
        lf.close()


# ---------------------------------------------------------------------------
# Chained-mode fixture — full anti-fraud + translation AS + ims_mock + generator + console
# ---------------------------------------------------------------------------

_CHAINED_PORTS = [5060, 5063, 8080, 8082, 8765, 8081, 5070, 5071, 5072, 5073]


@pytest.fixture(scope="function")
def demo_stack_chained():
    """Phase 3 chained stack via ``scripts/phase3-demo.sh full``.

    Function scope so a chained test session does not race with
    ``demo_stack`` (which is session scope and occupies 5060/8080/8765/8081).
    Each test starts its own full stack and tears it down cleanly.
    """
    for port in _CHAINED_PORTS:
        _kill_port(port)

    env = _env_with_local_no_proxy()
    proc = subprocess.Popen(
        ["bash", str(pathlib.Path(PROJECT_ROOT) / "scripts" / "phase3-demo.sh"), "full"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    ready = True
    last_port = None
    failed_label = ""
    # HTTP services first (fast signal), then UDP
    http_endpoints = [
        ("fraud AS API", 8082, "/healthz"),
        ("translation AS API", 8080, "/healthz"),
        ("console", 8081, "/healthz"),
        ("generator", 8765, "/load/status"),  # no /healthz on generator
    ]
    for label, port, path in http_endpoints:
        last_port = port
        if not _wait_http(f"http://127.0.0.1:{port}{path}", 35):
            failed_label = label
            ready = False
            break
    if ready:
        for label, port in [
            ("ims_mock return", 5070),
            ("fraud AS SIP", 5063),
            ("translation AS SIP", 5060),
        ]:
            last_port = port
            if not _wait_udp_port(port, 35):
                failed_label = label
                ready = False
                break

    if not ready:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        for p in _CHAINED_PORTS:
            _kill_port(p)
        raise RuntimeError(
            f"demo_stack_chained failed — port {last_port} / {failed_label} not ready within 35s"
        )

    yield {
        "console": "http://127.0.0.1:8081",
        "as_api": "http://127.0.0.1:8080",
        "fraud_api": "http://127.0.0.1:8082",
        "gen": "http://127.0.0.1:8765",
    }

    # --- teardown ---
    with contextlib.suppress(ProcessLookupError):
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    for port in _CHAINED_PORTS:
        _kill_port(port)
