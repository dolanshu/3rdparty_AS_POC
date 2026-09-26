"""Demo-script smoke test — validates the REAL user path, not just conftest.

This file exists because conftest.py silently patches two bugs that
``scripts/phase3-demo.sh`` had (port collision + routing_rules port rewrite).
For weeks the E2E suite was all-green but the demo script never worked —
users who ran `./scripts/phase3-demo.sh` saw an empty dashboard for
1+ minutes because the generator INVITEs landed on the wrong port.

These tests start the demo script as-is (no conftest patching), wait for
real calls to flow through, and assert AS metrics + traces accumulate.
If a future change breaks the demo script but conftest stays green,
these tests will catch it.

Run: python3 -m pytest tests/e2e/test_demo_script_path.py -v
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
from urllib import request as urlrequest
from urllib.error import URLError

import pytest

pytestmark = pytest.mark.e2e

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
RULES_FILE = PROJECT_ROOT / "config" / "routing_rules.yaml"
DEMO_SCRIPT = PROJECT_ROOT / "scripts" / "phase3-demo.sh"

# Use different ports than conftest demo_stack to avoid cross-test collision
# (conftest uses 5060/5061/8080/8765/8081). We use 5070/5071/8090/8775/8091.
_DEMO_PORTS = {
    "CORE_SIP": 5071,
    "CORE_UAC": 5072,
    "AS_TRANS_SIP": 5070,
    "AS_TRANS_API": 8090,
    "AS_FRAUD_SIP": 5073,
    "AS_FRAUD_API": 8092,
    "GEN_HTTP": 8775,
    "CONSOLE_HTTP": 8091,
}


def _http_get(url: str, timeout: float = 2.0) -> dict:
    with urlrequest.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _start_demo_env() -> dict[str, str]:
    """Env dict to run phase3-demo.sh with isolated ports."""
    env = os.environ.copy()
    for k, v in _DEMO_PORTS.items():
        env[k] = str(v)
    # Prevent wait() from blocking on demo's `read` prompt — just background it
    return env


class DemoStack:
    """Context manager that starts phase3-demo.sh and cleans up on exit."""

    def __init__(self, tmp_path: pathlib.Path):
        self.tmp = tmp_path
        self.log_dir = tmp_path / "demo-logs"
        self.log_dir.mkdir()
        self.proc: subprocess.Popen | None = None
        self.rules_backup: pathlib.Path | None = None

    def __enter__(self):
        # 1. Backup routing_rules.yaml (demo script rewrites it)
        if RULES_FILE.exists():
            self.rules_backup = self.tmp / "routing_rules.yaml.orig"
            self.rules_backup.write_bytes(RULES_FILE.read_bytes())

        # 2. Build env with isolated ports
        env = _start_demo_env()
        env["LOG_DIR"] = str(self.log_dir)

        # 3. Start demo script — but background `wait` so we don't block
        self.proc = subprocess.Popen(
            ["bash", str(DEMO_SCRIPT), "simple"],
            env=env,
            stdout=(self.log_dir / "run.log").open("w"),
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )

        # 4. Wait for all 5 ports to bind
        deadline = time.time() + 20
        while time.time() < deadline:
            all_up = True
            for p in [
                _DEMO_PORTS["CORE_SIP"],
                _DEMO_PORTS["CORE_UAC"],
                _DEMO_PORTS["AS_TRANS_API"],
                _DEMO_PORTS["GEN_HTTP"],
                _DEMO_PORTS["CONSOLE_HTTP"],
            ]:
                try:
                    s = urlrequest.urlopen(f"http://127.0.0.1:{p}/", timeout=0.5)
                    s.close()
                except Exception:
                    all_up = False
                    break
            if all_up:
                break
            time.sleep(0.5)

        # Give sippy event loop a moment to settle
        time.sleep(2)
        return {
            "as_api": f"http://127.0.0.1:{_DEMO_PORTS['AS_TRANS_API']}",
            "gen": f"http://127.0.0.1:{_DEMO_PORTS['GEN_HTTP']}",
            "console": f"http://127.0.0.1:{_DEMO_PORTS['CONSOLE_HTTP']}",
            "rules_port": _DEMO_PORTS["CORE_SIP"],
        }

    def __exit__(self, *exc):
        # Kill any processes spawned by the demo
        subprocess.run(
            ["pkill", "-9", "-f", "s_sbc_mock.main.*507"],
            capture_output=True,
        )
        subprocess.run(
            ["pkill", "-9", "-f", "as_app.main"],
            capture_output=True,
        )
        subprocess.run(
            ["pkill", "-9", "-f", f"call_load_generator.py.*{_DEMO_PORTS['GEN_HTTP']}"],
            capture_output=True,
        )
        subprocess.run(
            ["pkill", "-9", "-f", f"console.main.*{_DEMO_PORTS['CONSOLE_HTTP']}"],
            capture_output=True,
        )
        time.sleep(1)
        # Restore routing_rules.yaml
        if self.rules_backup is not None:
            RULES_FILE.write_bytes(self.rules_backup.read_bytes())


@pytest.fixture(scope="function")
def demo_stack_script(tmp_path):
    """Start phase3-demo.sh fresh for each test; tear down + restore files."""
    with DemoStack(tmp_path) as s:
        yield s


# ===========================================================================
# Test 1: demo script correctly rewrites routing_rules.yaml (port rewrite)
# ===========================================================================

def test_demo_rewrites_routing_rules_ports(demo_stack_script):
    """demo script 必须把 routing_rules.yaml 所有 next_hop port 改成 CORE_SIP.

    如果这个断言过不了 — 比如 demo 脚本有人删了 rewrite 逻辑 —
    conftest 仍然会绿（它有自己的 rewrite），但用户手动跑 demo
    就会看到 AS 往 unbound port 15061 发 INVITE。
    """
    import yaml

    with RULES_FILE.open() as f:
        doc = yaml.safe_load(f)
    ports = {nh["port"] for nh in doc["next_hops"]}
    expected = {demo_stack_script["rules_port"]}
    assert ports == expected, (
        f"routing_rules.yaml next_hop ports = {ports}, "
        f"expected all = {expected} (CORE_SIP). "
        f"If wrong, demo script's port-rewrite step is broken."
    )


# ===========================================================================
# Test 2: demo script 起的 generator → AS → metrics 有 calls_total > 0
# ===========================================================================

def test_demo_call_flow_reaches_as_metrics(demo_stack_script):
    """真实用户路径：Start generator → 等 15s → AS metrics calls_total > 0.

    这是最关键的测试——它直接暴露 "demo 脚本端口冲突导致 INVITE 不到 AS"
    这种 conftest 掩盖的 bug.
    """
    gen = demo_stack_script["gen"]
    as_api = demo_stack_script["as_api"]

    # Start generator via REST
    req = urlrequest.Request(f"{gen}/load/start", method="POST", data=b"")
    with urlrequest.urlopen(req, timeout=3) as r:
        _ = json.loads(r.read())

    # Wait for calls to flow through (15s should be plenty at rate=3.0)
    deadline = time.time() + 20
    metrics = {}
    while time.time() < deadline:
        try:
            metrics = _http_get(f"{as_api}/api/v1/metrics")
            total = metrics.get("calls_total", 0)
            if total > 0:
                break
        except (URLError, ConnectionError):
            pass
        time.sleep(1)

    total = metrics.get("calls_total", 0)
    rule_hits = metrics.get("rule_hits", {})
    assert total > 0 or rule_hits, (
        f"AS metrics show NO activity after 20s with generator running — "
        f"demo script port wiring is broken. "
        f"gen status = ???; see logs at /tmp/p3-demo/. "
        f"Last metrics: calls_total={total}, rule_hits={rule_hits}"
    )

    # calls_by_disposition may be empty on short runs (async increment),
    # but non-empty rule_hits proves INVITEs are reaching the AS.
    assert rule_hits, (
        f"calls_total={total} but rule_hits empty — INVITEs reach AS but "
        f"routing_rules may still have wrong ports. metrics: {metrics}"
    )


# ===========================================================================
# Test 3: generator /load/status reflects real activity (not self-reported)
# ===========================================================================

def test_demo_gen_status_has_real_activity(demo_stack_script):
    """generator /load/status.active_calls 必须曾 > 0（证明 INVITE 真发出了）."""
    gen = demo_stack_script["gen"]

    req = urlrequest.Request(f"{gen}/load/start", method="POST", data=b"")
    with urlrequest.urlopen(req, timeout=3) as r:
        _ = json.loads(r.read())

    deadline = time.time() + 15
    peak_active = 0
    while time.time() < deadline:
        try:
            s = _http_get(f"{gen}/load/status")
            peak_active = max(peak_active, s.get("active_calls", 0))
        except Exception:
            pass
        time.sleep(0.5)

    assert peak_active > 0, (
        f"generator /load/status.active_calls never rose above 0 in 15s — "
        f"generator may not be sending INVITEs, or SIP port is wrong."
    )
