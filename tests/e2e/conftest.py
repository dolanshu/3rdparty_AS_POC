"""Playwright E2E — session-scoped demo stack fixture.

Launches the full Phase 3 stack (core mock → translation AS → load generator
→ enhanced console) once per pytest session, waits for all healthz to come
up, then yields a dict of base URLs. Teardown kills everything.

Run with the system python so playwright/pytest-playwright are available,
but the spawned child processes use the project venv python (which has
sippy + as_platform + FastAPI installed).
"""

from __future__ import annotations

import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib import request as urlrequest

import pytest

PROJECT_ROOT = "/home/shudong/project/3rtparty_AS_POC"
VENV_PY = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")


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


def _reset_gen(gen_base: str) -> None:
    """Force generator to idle (POST /load/stop + wait until running=false)."""
    import json as _json
    try:
        urlrequest.urlopen(f"{gen_base}/load/stop", data=b"", timeout=3).read()
    except Exception:
        pass
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            with urlrequest.urlopen(f"{gen_base}/load/status", timeout=2) as r:
                if not _json.loads(r.read()).get("running", True):
                    return
        except Exception:
            pass
        time.sleep(0.3)


@pytest.fixture(scope="session")
def demo_stack():
    """Bring up 4 processes once for the whole e2e session."""
    for p in STACK_PORTS:
        _kill_port(p)

    # ---- Generate a routing rules file that points every next-hop at the
    #      single core-mock UAS (port 5061). The shipped config targets six
    #      distinct ports (15061–15066), which we don't want to bring up in e2e.
    import yaml as _yaml

    _rules_src = pathlib.Path(PROJECT_ROOT) / "config" / "routing_rules.yaml"
    _rules_dst = pathlib.Path(tempfile.mkdtemp(prefix="e2e-rules-")) / "rules.yaml"
    with _rules_src.open() as _f:
        _doc = _yaml.safe_load(_f)
    for _nh in _doc.get("next_hops", []):
        _nh["port"] = 5061
    with _rules_dst.open("w") as _f:
        _yaml.safe_dump(_doc, _f, sort_keys=False, allow_unicode=True)

    env = os.environ.copy()
    procs: list[subprocess.Popen] = []

    # 1. Core mock UAS  (UDP :5061 UAS, :15060 UAC trunk)
    #    --trunk-port avoids the default "listen_port - 1" = 5060, which would
    #    collide with the AS SIP port below.
    procs.append(subprocess.Popen(
        [VENV_PY, "-m", "s_sbc_mock.main",
         "--listen-port", "5061", "--trunk-port", "15060"],
        cwd=PROJECT_ROOT, env=env,
    ))

    # 2. Translation AS  (SIP UDP :5060, API HTTP :8080)
    env_as = env.copy()
    env_as["SBC_PEER_ADDRESS"] = "127.0.0.1"
    env_as["SBC_PEER_PORT"] = "5061"
    env_as["RULES_FILE"] = str(_rules_dst)
    _as_log = open("/tmp/e2e-as.log", "w")
    procs.append(subprocess.Popen([VENV_PY, "-m", "as_app.main"], cwd=PROJECT_ROOT, env=env_as, stdout=_as_log, stderr=subprocess.STDOUT))

    # 3. Load generator  (HTTP :8765, SIP client → AS :5060)
    procs.append(subprocess.Popen(
        [VENV_PY, "tools/call_load_generator.py",
         "--as-port", "5060", "--http-port", "8765"],
        cwd=PROJECT_ROOT, env=env,
    ))

    # 4. Enhanced console  (HTTP :8081)
    procs.append(subprocess.Popen(
        [VENV_PY, "-m", "console.main",
         "--port", "8081",
         "--as-api-url", "http://127.0.0.1:8080",
         "--load-api-url", "http://127.0.0.1:8765"],
        cwd=PROJECT_ROOT, env=env,
    ))

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
        raise RuntimeError("demo_stack failed to come up within 20s")

    yield {
        "console": "http://127.0.0.1:8081",
        "as_api": "http://127.0.0.1:8080",
        "gen": "http://127.0.0.1:8765",
    }

    # --- teardown ---
    for p in procs:
        try:
            p.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    for port in STACK_PORTS:
        _kill_port(port)
