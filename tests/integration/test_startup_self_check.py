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

"""Integration tests for the AS startup path on localhost.

The signalling path itself is M1; what is exercised here is everything the process needs
before it can bind a socket: configuration from the environment, rules from disk, port
availability and the release of the probing socket.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from as_app.bootstrap import AsSettings, run_startup_self_check
from as_app.routing.rules import RuleSetStore

pytestmark = pytest.mark.integration


def test_self_check_binds_and_releases_the_signalling_port(
    free_udp_port: int, rules_file: Path
) -> None:
    """The port probe leaves the port free for the sippy stack."""
    settings = AsSettings(_env_file=None, sip_listen_port=free_udp_port, rules_file=rules_file)
    run_startup_self_check(settings)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", free_udp_port))
        assert probe.getsockname()[1] == free_udp_port


def test_self_check_accepts_a_reloaded_rule_set(
    free_udp_port: int, tmp_path: Path, rules_file: Path
) -> None:
    """A rule set edited on disk is picked up and re-validated."""
    working_copy = tmp_path / "routing_rules.yaml"
    working_copy.write_text(rules_file.read_text(encoding="utf-8"), encoding="utf-8")

    settings = AsSettings(_env_file=None, sip_listen_port=free_udp_port, rules_file=working_copy)
    run_startup_self_check(settings)

    store = RuleSetStore(working_copy)
    assert store.maybe_reload() is False
    edited = working_copy.read_text(encoding="utf-8").replace(
        "name: sample-office-routing", "name: sample-office-routing-reloaded"
    )
    working_copy.write_text(edited, encoding="utf-8")
    assert store.maybe_reload() is True
    assert store.current.document.name == "sample-office-routing-reloaded"


def test_sippy_is_installed_at_the_pinned_version() -> None:
    """Sippy 2.4.2 is importable and exposes the primitives the AS needs (ADR-0001)."""
    pytest.importorskip("sippy")
    from importlib.metadata import version

    from sippy.Core.EventDispatcher import ED2
    from sippy.SipTransactionManager import SipTransactionManager

    assert version("sippy") == "2.4.2"
    assert callable(SipTransactionManager)
    assert hasattr(ED2, "loop")
