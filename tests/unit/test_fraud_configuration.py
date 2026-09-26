# Copyright 2026 Dolan Shu <dolan.d.shu@gmail.com>.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the anti-fraud AS configuration and startup self-check.

The second AS is configured independently of the first: its instance-identifying knobs are
prefixed ``FRAUD_`` so one ``.env`` cannot point the wrong process at the wrong peer, and
**no default silently points at a real network** (``AGENT.md`` section 8). The self-check is
fail-fast: an unusable screening file or a taken signalling port aborts startup instead of
failing later on the call path (``AGENT.md`` section 4.3).

Covers ACC-P8-001 (REQ-F-016, REQ-NF-014).
"""

from __future__ import annotations

import ast
import re
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from anti_fraud_as.bootstrap import FraudAsSettings, run_startup_self_check
from anti_fraud_as.errors import AsError, FraudErrorCode, SkeletonErrorCode

pytestmark = pytest.mark.unit

#: Every environment variable the anti-fraud AS reads, as declared in ``.env.example``.
FRAUD_KNOBS = (
    "FRAUD_SIP_LISTEN_ADDRESS",
    "FRAUD_SIP_LISTEN_PORT",
    "FRAUD_SBC_PEER_ADDRESS",
    "FRAUD_SBC_PEER_PORT",
    "FRAUD_ALLOWED_PEERS",
    "FRAUD_SCREENING_FILE",
    "FRAUD_INTERNAL_API_ADDRESS",
    "FRAUD_INTERNAL_API_PORT",
)

#: Top-level modules the anti-fraud package may import: the standard library it uses, sippy,
#: the already-pinned configuration/API packages, the shared ``as_platform`` modules and
#: ``as_app`` (only for the repository version it re-exports).
ALLOWED_IMPORTS = frozenset(
    {
        "anti_fraud_as",
        "as_app",
        "as_platform",
        "sippy",
        "pydantic",
        "pydantic_settings",
        "yaml",
        "fastapi",
        "uvicorn",
        "_io",
        "__future__",
        "argparse",
        "asyncio",
        "collections",
        "contextlib",
        "dataclasses",
        "enum",
        "json",
        "logging",
        "math",
        "os",
        "pathlib",
        "re",
        "signal",
        "threading",
        "time",
        "typing",
    }
)


def settings_for(free_udp_port: int, screening_path: Path, **overrides: object) -> FraudAsSettings:
    """Build settings bound to a free port and a real screening file.

    Args:
        free_udp_port: Port the self-check will probe.
        screening_path: Screening data file to validate.
        **overrides: Extra settings fields.

    Returns:
        Settings that pass the self-check unless a test breaks one of them.
    """
    values: dict[str, object] = {
        "fraud_sip_listen_address": "127.0.0.1",
        "fraud_sip_listen_port": free_udp_port,
        "fraud_sbc_peer_address": "127.0.0.1",
        "fraud_sbc_peer_port": 15062,
        "fraud_allowed_peers": ["127.0.0.1"],
        "fraud_screening_file": screening_path,
        "fraud_internal_api_port": 8082,
    }
    values.update(overrides)
    return FraudAsSettings(_env_file=None, **values)


# ---------------------------------------------------------------------------
# Defaults and environment parsing
# ---------------------------------------------------------------------------


def test_defaults_are_loopback_and_do_not_collide_with_the_first_as(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both AS instances can run on one host: the second one is not on 5060/8080.

    The distinct default is the deliberate answer to the port-collision trap of
    ``docs/phase2-plan.md`` section 6, not an accident of the sample ``.env``.
    """
    for knob in FRAUD_KNOBS + ("LOG_LEVEL", "LOG_STRUCTURED", "LOG_PAYLOADS"):
        monkeypatch.delenv(knob, raising=False)

    settings = FraudAsSettings(_env_file=None)

    assert settings.fraud_sip_listen_address == "127.0.0.1"
    assert settings.fraud_sip_listen_port == 5062
    assert settings.fraud_internal_api_address == "127.0.0.1"
    assert settings.fraud_internal_api_port == 8082
    assert settings.fraud_sbc_peer_address == "127.0.0.1"
    assert settings.fraud_sbc_peer_port == 15062
    assert settings.fraud_allowed_peers == ["127.0.0.1"]
    assert str(settings.fraud_screening_file) == "config/caller_screening.yaml"
    # The first AS owns 5060/8080; sharing either would break a side-by-side run.
    assert settings.fraud_sip_listen_port != 5060
    assert settings.fraud_internal_api_port != 8080


def test_every_knob_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented variable names are the ones pydantic-settings reads."""
    monkeypatch.setenv("FRAUD_SIP_LISTEN_ADDRESS", "127.0.0.2")
    monkeypatch.setenv("FRAUD_SIP_LISTEN_PORT", "5099")
    monkeypatch.setenv("FRAUD_SBC_PEER_ADDRESS", "127.0.0.3")
    monkeypatch.setenv("FRAUD_SBC_PEER_PORT", "16061")
    monkeypatch.setenv("FRAUD_ALLOWED_PEERS", "127.0.0.2, 127.0.0.3")
    monkeypatch.setenv("FRAUD_SCREENING_FILE", "/tmp/elsewhere.yaml")
    monkeypatch.setenv("FRAUD_INTERNAL_API_ADDRESS", "127.0.0.4")
    monkeypatch.setenv("FRAUD_INTERNAL_API_PORT", "8099")

    settings = FraudAsSettings(_env_file=None)

    assert settings.fraud_sip_listen_address == "127.0.0.2"
    assert settings.fraud_sip_listen_port == 5099
    assert settings.fraud_sbc_peer_address == "127.0.0.3"
    assert settings.fraud_sbc_peer_port == 16061
    assert settings.fraud_allowed_peers == ["127.0.0.2", "127.0.0.3"]
    assert str(settings.fraud_screening_file) == "/tmp/elsewhere.yaml"
    assert settings.fraud_internal_api_address == "127.0.0.4"
    assert settings.fraud_internal_api_port == 8099


def test_allowed_peers_accept_a_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators edit ``.env`` by hand, so the list is a plain comma separated value."""
    monkeypatch.setenv("FRAUD_ALLOWED_PEERS", "127.0.0.1, 127.0.0.2 ,")

    settings = FraudAsSettings(_env_file=None)

    assert settings.fraud_allowed_peers == ["127.0.0.1", "127.0.0.2"]


def test_the_log_level_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in ``LOG_LEVEL`` fails at startup rather than being ignored."""
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        FraudAsSettings(_env_file=None)


@pytest.mark.parametrize("port", [0, 70000])
def test_a_port_outside_the_valid_range_is_rejected(
    monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    """Ports are validated by the settings model, not left to the socket layer."""
    monkeypatch.setenv("FRAUD_SIP_LISTEN_PORT", str(port))

    with pytest.raises(ValidationError):
        FraudAsSettings(_env_file=None)


# ---------------------------------------------------------------------------
# Startup self-check
# ---------------------------------------------------------------------------


def test_the_self_check_passes_for_a_valid_configuration(
    free_udp_port: int, screening_file: Path
) -> None:
    """The happy path, and the port is released again for the sippy stack."""
    run_startup_self_check(settings_for(free_udp_port, screening_file))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", free_udp_port))
        assert probe.getsockname()[1] == free_udp_port


def test_the_self_check_rejects_a_missing_screening_file(
    free_udp_port: int, tmp_path: Path
) -> None:
    """A screening file that is not there is AS-FRAUD-004, before the port is bound."""
    settings = settings_for(free_udp_port, tmp_path / "absent.yaml")

    with pytest.raises(AsError) as raised:
        run_startup_self_check(settings)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_UNREADABLE


def test_the_self_check_rejects_an_invalid_screening_file(
    free_udp_port: int, tmp_path: Path
) -> None:
    """A screening file that does not validate is AS-FRAUD-005."""
    broken = tmp_path / "caller_screening.yaml"
    broken.write_text("window: [unclosed\n", encoding="utf-8")

    with pytest.raises(AsError) as raised:
        run_startup_self_check(settings_for(free_udp_port, broken))

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR


def test_the_self_check_requires_a_next_hop(free_udp_port: int, screening_file: Path) -> None:
    """Without a next hop an allowed call cannot be relayed, so startup stops."""
    settings = settings_for(free_udp_port, screening_file, fraud_sbc_peer_address="   ")

    with pytest.raises(AsError) as raised:
        run_startup_self_check(settings)

    assert raised.value.code is SkeletonErrorCode.CFG_MISSING


def test_the_self_check_requires_at_least_one_allowed_peer(
    free_udp_port: int, screening_file: Path
) -> None:
    """An empty allowlist would reject every call, which is a configuration error."""
    settings = settings_for(free_udp_port, screening_file, fraud_allowed_peers=[])

    with pytest.raises(AsError) as raised:
        run_startup_self_check(settings)

    assert raised.value.code is SkeletonErrorCode.CFG_PEER_INVALID


def test_the_self_check_fails_fast_when_the_port_is_taken(screening_file: Path) -> None:
    """A taken trunk port aborts startup instead of stealing traffic from the other AS."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as holder:
        holder.bind(("127.0.0.1", 0))
        taken_port = int(holder.getsockname()[1])

        with pytest.raises(AsError) as raised:
            run_startup_self_check(settings_for(taken_port, screening_file))

    assert raised.value.code is SkeletonErrorCode.CFG_PORT_UNAVAILABLE


# ---------------------------------------------------------------------------
# The configuration surface itself (REQ-NF-014)
# ---------------------------------------------------------------------------


def test_env_example_declares_every_fraud_knob(repo_root: Path) -> None:
    """Every variable of the second AS is declared in ``.env.example``.

    REQ-NF-014: configuration is through environment variables only, and AGENT.md section 8
    requires the example to list them.
    """
    content = (repo_root / ".env.example").read_text(encoding="utf-8")

    for knob in FRAUD_KNOBS:
        assert knob in content, f"{knob} is not declared in .env.example"


def test_the_fraud_package_adds_no_third_party_dependency(repo_root: Path) -> None:
    """REQ-NF-014: P8 imports nothing outside the standard library and the pinned set.

    Checked against the real imports rather than the manifest, so a new import fails here
    even if someone forgets the dependency list.
    """
    package = repo_root / "src" / "anti_fraud_as"
    imported: set[str] = set()
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])

    unexpected = sorted(imported - ALLOWED_IMPORTS)
    assert not unexpected, (
        f"the anti-fraud AS imports packages outside the pinned set: {unexpected}"
    )


def test_the_runtime_dependency_pin_is_unchanged(repo_root: Path) -> None:
    """The sippy pin is unchanged; ``as-platform`` is the only other runtime dependency.

    The SIP stack stays pinned at exactly ``sippy==2.4.2`` (``AGENT.md`` section 6), and it
    is the only pinned third-party runtime dependency. The sole other mandatory runtime
    dependency is this project's own platform library ``as-platform``, consumed from the
    sibling checkout ``../as_platform`` (ADR-0009 decision 6) — not a third-party package
    and not a version pin.
    """
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    runtime = re.search(r"^dependencies = \[(.*?)^\]", text, re.DOTALL | re.MULTILINE)
    assert runtime is not None, "the runtime dependencies are missing from pyproject.toml"
    runtime_dependencies = re.findall(r'"([^"]+)"', runtime.group(1))
    assert "sippy==2.4.2" in runtime_dependencies
    assert set(runtime_dependencies) - {"sippy==2.4.2"} == {"as-platform"}

    # The block ends at a line that is only ``]``: an item like ``uvicorn[standard]``
    # contains a ``]`` of its own, so the delimiter cannot be the first one seen.
    block = re.search(r"^as = \[(.*?)^\]", text, re.DOTALL | re.MULTILINE)
    assert block is not None, "the 'as' extra is missing from pyproject.toml"
    names = {
        re.split(r"[><=\[]", item, maxsplit=1)[0]
        for item in re.findall(r'"([^"]+)"', block.group(1))
    }
    assert names == {"pydantic", "pydantic-settings", "pyyaml", "fastapi", "uvicorn"}
