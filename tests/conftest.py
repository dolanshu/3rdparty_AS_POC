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

"""Shared fixtures for the unit, integration and e2e layers.

All UDP ports used by tests are allocated dynamically, so parallel runs and CI never
collide on 5060 (``AGENT.md`` section 11).

The signalling fixtures run the AS and the mock S-SBC in the test process on loopback.
sippy's ``ED2`` event dispatcher is a process-wide singleton and ``ED2.loop()`` has to run
on the main thread, so both sides share one loop instead of running two: the fixture binds
the sockets and the test drives the loop explicitly through
:meth:`TrunkPair.run_until`.
"""

from __future__ import annotations

import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = REPO_ROOT / "config" / "routing_rules.yaml"

#: Loopback address the trunk is exercised on.
TRUNK_ADDRESS = "127.0.0.1"

#: How often the loop-owned poller of :meth:`TrunkPair.run_until` runs, in seconds.
POLL_SECONDS = 0.02

#: Default time a call flow is given to complete, in seconds.
CALL_TIMEOUT_SECONDS = 10.0


def pytest_configure(config: pytest.Config) -> None:
    """Register the three test layers as markers.

    Args:
        config: The pytest configuration object.
    """
    config.addinivalue_line("markers", "unit: pure logic, no sockets")
    config.addinivalue_line("markers", "integration: AS and mock on localhost UDP")
    config.addinivalue_line("markers", "e2e: complete call flows including error branches")


@dataclass
class TrunkPair:
    """An AS and a mock S-SBC wired to each other over loopback UDP.

    Attributes:
        as_stack: The AS signalling stack, already bound.
        mock: The mock S-SBC, already bound.
        as_port: UDP port the AS receives the trunk on.
        core_port: UDP port of the core side of the mock, which is the AS next hop.
        trunk_port: UDP port the trunk side of the mock sends from.
    """

    as_stack: Any
    mock: Any
    as_port: int
    core_port: int
    trunk_port: int
    as_messages: Any = None
    _stopped: bool = field(default=False, repr=False)

    def place_call(self, scenario: Any) -> str:
        """Place one call towards the AS.

        Args:
            scenario: The :class:`~s_sbc_mock.uac.CallScenario` to place.

        Returns:
            The Call-ID of the call.
        """
        return str(self.mock.uac.place_call(scenario))

    def outcome_for(self, call_id: str) -> Any:
        """Return the outcome the trunk side observed for a call.

        Args:
            call_id: SIP Call-ID of the call.

        Returns:
            The :class:`~s_sbc_mock.uac.CallOutcome`, or ``None`` when unknown.
        """
        return self.mock.uac.outcome_for(call_id)

    def run_until(
        self, predicate: Callable[[], bool], timeout_seconds: float = CALL_TIMEOUT_SECONDS
    ) -> bool:
        """Drive the sippy event loop until a condition holds or the timeout expires.

        Args:
            predicate: Condition to wait for.
            timeout_seconds: How long to keep driving the loop.

        Returns:
            ``True`` when the condition became true, ``False`` on timeout.
        """
        from sippy.Core.EventDispatcher import ED2
        from sippy.Time.Timeout import Timeout

        deadline = time.monotonic() + timeout_seconds
        state = {"done": predicate()}

        def poll() -> None:
            if predicate() or time.monotonic() >= deadline:
                state["done"] = predicate()
                ED2.breakLoop()

        timer = Timeout(poll, POLL_SECONDS, -1)
        try:
            ED2.loop(timeout=timeout_seconds)
        finally:
            timer.cancel()
        return bool(state["done"])

    def stop(self) -> None:
        """Release every port the pair holds."""
        if self._stopped:
            return
        self.as_stack.stop()
        self.mock.stop()
        self._stopped = True


def _free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind((TRUNK_ADDRESS, 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root.

    Returns:
        Absolute path of the repository root.
    """
    return REPO_ROOT


@pytest.fixture(scope="session")
def rules_file() -> Path:
    """Return the path of the shipped sample rule set.

    Returns:
        Path of ``config/routing_rules.yaml``.
    """
    return RULES_FILE


@pytest.fixture
def rule_set(rules_file: Path):
    """Load the shipped sample rule set.

    Args:
        rules_file: Path of the rules file.

    Returns:
        The loaded :class:`~as_app.routing.rules.RuleSet`.
    """
    from as_app.routing.rules import load_rule_set

    return load_rule_set(rules_file)


@pytest.fixture
def free_udp_port() -> int:
    """Reserve a free UDP port for the duration of a test.

    Returns:
        A port number that was free when the fixture ran.
    """
    return _free_udp_port()


@pytest.fixture
def trunk_pair(rules_file: Path, tmp_path: Path):
    """Run the AS and the mock S-SBC on loopback UDP with ephemeral ports.

    The shipped rule set pins next hops to demo ports (15061, 15062, ...). The tests run
    on ephemeral ports, so the fixture rewrites the next hop addresses of
    ``s-sbc-primary`` (and the PBX / international hops when a test asks for them) to the
    dynamically allocated core port of the mock. This keeps the rule engine pure: the
    rule decides *which* hop, and the hop's address is real data that just happens to be
    generated for the test.

    Args:
        rules_file: Path of the shipped sample rule set.
        tmp_path: Per-test temporary directory for the rewritten rules file.

    Yields:
        A bound :class:`TrunkPair`; both sides are stopped after the test.
    """
    from as_app.bootstrap import AsSettings
    from as_app.main import AsStack
    from as_app.observability.tracing import SipMessageRecorder
    from s_sbc_mock.main import MockConfig, SMockApplication

    as_port, core_port, trunk_port, api_port = (
        _free_udp_port(),
        _free_udp_port(),
        _free_udp_port(),
        _free_udp_port(),
    )
    test_rules = _rewrite_next_hops(rules_file, tmp_path, core_port)
    settings = AsSettings(
        _env_file=None,
        sip_listen_address=TRUNK_ADDRESS,
        sip_listen_port=as_port,
        sbc_peer_address=TRUNK_ADDRESS,
        sbc_peer_port=core_port,
        allowed_peers=[TRUNK_ADDRESS],
        rules_file=test_rules,
        internal_api_address=TRUNK_ADDRESS,
        internal_api_port=api_port,
        log_payloads=False,
    )
    # The stack writes its SIP messages through a recorder instead of a SipLogger: the
    # sippy message log is a separate channel from the structured application log and
    # would otherwise drown the test output, while the recorder lets a test assert on the
    # bytes that actually went over the wire.
    as_messages = SipMessageRecorder()
    as_stack = AsStack(settings, sip_logger=as_messages)
    as_stack.start()
    mock = SMockApplication(
        MockConfig(
            listen_address=TRUNK_ADDRESS,
            listen_port=core_port,
            as_address=TRUNK_ADDRESS,
            as_port=as_port,
        ),
        sip_logger=SipMessageRecorder(),
        uac_local_port=trunk_port,
    )
    mock.start()
    pair = TrunkPair(as_stack, mock, as_port, core_port, trunk_port, as_messages)
    try:
        yield pair
    finally:
        pair.stop()


def _rewrite_next_hops(source: Path, tmp_path: Path, core_port: int) -> Path:
    """Return a copy of the rules file with the primary next hops on the test port.

    The shipped rules file pins next hops to demo ports. The rewrite maps every next hop
    address/port to the mock's dynamically allocated core port, so a rule-selected hop
    always reaches the mock regardless of which hop the rule chooses. Tests that need a
    hop to fail can use :func:`_rewrite_next_hops_with_failover` instead.

    Args:
        source: Path of the shipped rules file.
        tmp_path: Temporary directory for the rewritten file.
        core_port: UDP port the mock core side listens on.

    Returns:
        Path of the rewritten rules file.
    """
    text = source.read_text(encoding="utf-8")
    # Rewrite every ``address: 127.0.0.1`` + ``port: <n>`` pair inside a next hop to the
    # test core port, so every hop the rules select reaches the mock. A real deployment
    # keeps the original addresses; the rewrite is a test-only convenience.
    rewritten = _replace_next_hop_ports(text, core_port)
    target = tmp_path / "routing_rules.yaml"
    target.write_text(rewritten, encoding="utf-8")
    return target


_NEXT_HOP_PORT_LINE = re.compile(r"^(\s+port:\s+)\d+(\s.*)?$", re.MULTILINE)


def _replace_next_hop_ports(text: str, port: int) -> str:
    """Rewrite every ``port:`` line that sits under a next hop to one value.

    The next hop block is the only place a ``port:`` line appears in the rules file, so a
    global replace is safe and keeps the rewrite trivial.

    Args:
        text: The rules file content.
        port: The port to substitute.

    Returns:
        The rules file content with every next hop port replaced.
    """
    return _NEXT_HOP_PORT_LINE.sub(rf"\g<1>{port}\g<2>", text)
