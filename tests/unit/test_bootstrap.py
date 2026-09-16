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

"""Unit tests for the configuration model and the startup self-check."""

from __future__ import annotations

from pathlib import Path

import pytest

from as_app.bootstrap import AsSettings, check_port_available, run_startup_self_check
from as_app.errors import AsError, AsErrorCode

pytestmark = pytest.mark.unit


def test_settings_read_the_environment(
    monkeypatch: pytest.MonkeyPatch, rules_file: Path, free_udp_port: int
) -> None:
    """Configuration comes from environment variables (AGENT.md section 8)."""
    monkeypatch.setenv("SIP_LISTEN_PORT", str(free_udp_port))
    monkeypatch.setenv("SBC_PEER_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("SBC_PEER_PORT", "15061")
    monkeypatch.setenv("ALLOWED_PEERS", "127.0.0.1, 10.0.0.1")
    monkeypatch.setenv("RULES_FILE", str(rules_file))
    settings = AsSettings(_env_file=None)
    assert settings.sip_listen_port == free_udp_port
    assert settings.allowed_peers == ["127.0.0.1", "10.0.0.1"]
    assert settings.rules_file == rules_file


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown log level aborts startup rather than failing later."""
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="unsupported log level"):
        AsSettings(_env_file=None)


def test_port_availability_check_detects_a_busy_port(free_udp_port: int) -> None:
    """A UDP port that is already taken reports AS-CFG-003."""
    import socket

    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        blocker.bind(("127.0.0.1", free_udp_port))
        with pytest.raises(AsError) as excinfo:
            check_port_available("127.0.0.1", free_udp_port)
    finally:
        blocker.close()
    assert excinfo.value.code is AsErrorCode.CFG_PORT_UNAVAILABLE


def test_self_check_passes_with_a_valid_configuration(free_udp_port: int, rules_file: Path) -> None:
    """A consistent configuration and rule set pass the self-check."""
    settings = AsSettings(
        _env_file=None,
        sip_listen_port=free_udp_port,
        rules_file=rules_file,
    )
    run_startup_self_check(settings)


def test_self_check_fails_when_the_rules_file_is_absent(free_udp_port: int, tmp_path: Path) -> None:
    """A missing rules file aborts startup with AS-RULE-001."""
    settings = AsSettings(
        _env_file=None,
        sip_listen_port=free_udp_port,
        rules_file=tmp_path / "absent.yaml",
    )
    with pytest.raises(AsError) as excinfo:
        run_startup_self_check(settings)
    assert excinfo.value.code is AsErrorCode.RULE_FILE_UNREADABLE


def test_self_check_fails_without_a_peer(free_udp_port: int, rules_file: Path) -> None:
    """An empty next hop address aborts startup with AS-CFG-001."""
    settings = AsSettings(
        _env_file=None,
        sip_listen_port=free_udp_port,
        rules_file=rules_file,
        sbc_peer_address="  ",
    )
    with pytest.raises(AsError) as excinfo:
        run_startup_self_check(settings)
    assert excinfo.value.code is AsErrorCode.CFG_MISSING
