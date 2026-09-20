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

"""Integration tests for the M2 number translation features.

Covers the branches that are impractical or less natural to drive through the e2e
complete-call fixture:

- **next-hop failover**: when the first next hop fails, the AS tries the second hop
  (``AS-PEER-002`` / ``503`` semantics, ``AGENT.md`` section 4.6).
- **hot reload**: editing the rules file at runtime activates a new rule set without a
  restart, with a log line naming the new rule set (ADR-0004).
- **480 / AS-ROUTE-003**: a route decision with no available next hop.
- **500 / AS-ROUTE-004**: a translation that produces an empty number.
"""

from __future__ import annotations

import contextlib
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from as_app.errors import AsError, AsErrorCode
from as_app.routing.engine import decide
from as_app.routing.rules import RuleSetStore, load_rule_set
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration

#: A rules document whose only route rule strips the whole called number, so the engine
#: raises ``AS-ROUTE-004`` ("translation produced an empty number") before it can decide.
_EMPTY_TRANSLATION_DOCUMENT = """
version: 1
name: empty-translation
next_hops:
  - name: hop-a
    address: 127.0.0.1
    port: 15061
rules:
  - rule_id: R-EMPTY
    priority: 10
    match:
      called_prefixes: ["123"]
    action:
      kind: route
      translate:
        to_format: national
        strip_prefix: "123"
      next_hops: [hop-a]
"""

#: A rules document with one routable rule; the 480 test drains the hop catalogue after
#: load, so resolving the matched rule's hop raises ``AS-ROUTE-003`` at runtime.
_ONE_HOP_DOCUMENT = """
version: 1
name: one-hop
next_hops:
  - name: hop-a
    address: 127.0.0.1
    port: 15061
rules:
  - rule_id: R-001
    priority: 10
    match:
      called_prefixes: ["0"]
    action:
      kind: route
      translate:
        to_format: national
      next_hops: [hop-a]
"""

#: A rules document where the primary hop points at an unbound port and the failover hop
#: is left for the test to rewrite to the mock core port. The primary hop will time out,
#: producing a ``CCEventFail`` that the controller turns into a failover attempt.
_FAILOVER_DOCUMENT = """
version: 1
name: failover-test
next_hops:
  - name: s-sbc-primary
    address: 127.0.0.1
    port: {unbound_port}
    priority: 1
  - name: s-sbc-failover
    address: 127.0.0.1
    port: {core_port}
    priority: 2
rules:
  - rule_id: R-MOB-40
    priority: 100
    description: China Mobile, failover to the second hop
    match:
      called_prefixes: ["+86138"]
      number_format: e164
    action:
      kind: route
      translate:
        to_format: national
        strip_prefix: "+86"
        prepend: "0"
      next_hops: [s-sbc-primary, s-sbc-failover]
"""


def _free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_next_hop_failover_uses_the_second_hop(
    rules_file: Path, repo_root: Path, tmp_path: Path
) -> None:
    """When the first next hop fails, the AS tries the second (ACC-M2-002).

    The test writes a rules file where ``s-sbc-primary`` points at an unbound port
    (so the INVITE times out and sippy raises ``CCEventFail``) and ``s-sbc-failover``
    points at the mock core side. The call must complete via the failover hop.
    """
    from sippy.Core.EventDispatcher import ED2
    from sippy.Time.Timeout import Timeout

    from as_app.bootstrap import AsSettings
    from as_app.main import AsStack
    from as_app.observability.tracing import SipMessageRecorder
    from s_sbc_mock.main import MockConfig, SMockApplication

    unbound_port = _free_udp_port()
    as_port = _free_udp_port()
    core_port = _free_udp_port()
    trunk_port = _free_udp_port()
    api_port = _free_udp_port()

    failover_rules = tmp_path / "failover_rules.yaml"
    failover_rules.write_text(
        _FAILOVER_DOCUMENT.format(unbound_port=unbound_port, core_port=core_port),
        encoding="utf-8",
    )
    settings = AsSettings(
        _env_file=None,
        sip_listen_address="127.0.0.1",
        sip_listen_port=as_port,
        sbc_peer_address="127.0.0.1",
        sbc_peer_port=core_port,
        allowed_peers=["127.0.0.1"],
        rules_file=failover_rules,
        internal_api_address="127.0.0.1",
        internal_api_port=api_port,
        log_payloads=False,
    )
    as_messages = SipMessageRecorder()
    as_stack = AsStack(settings, sip_logger=as_messages)
    as_stack.start()
    mock = SMockApplication(
        MockConfig(
            listen_address="127.0.0.1",
            listen_port=core_port,
            as_address="127.0.0.1",
            as_port=as_port,
        ),
        sip_logger=SipMessageRecorder(),
        uac_local_port=trunk_port,
    )
    mock.start()
    try:
        scenario = CallScenario(
            name="failover",
            calling_number="+86216180001",
            called_number="+8613800138000",
            ring_seconds=0.1,
            talk_seconds=0.1,
        )
        call_id = mock.uac.place_call(scenario)
        outcome = mock.uac.outcome_for(call_id)
        assert outcome is not None

        # Drive the shared sippy loop until the call is released. sippy's INVITE
        # retransmission timer T1 is 0.5s; the unbound primary hop fails after a few
        # retransmissions, then the failover hop answers.
        deadline = time.monotonic() + 15.0
        state: dict[str, bool] = {"done": False}

        def poll() -> None:
            current = mock.uac.outcome_for(call_id) or outcome
            if current.released or time.monotonic() >= deadline:
                state["done"] = current.released
                ED2.breakLoop()

        timer = Timeout(poll, 0.02, -1)
        try:
            ED2.loop(timeout=15.0)
        finally:
            timer.cancel()
        outcome = mock.uac.outcome_for(call_id) or outcome
        assert state["done"], f"failover call {call_id} did not finish within the timeout"
        assert outcome.status == 200, (
            f"caller saw {outcome.status} instead of 200 OK after failover"
        )

        invites = list(mock.uas.received_invites)
        assert invites, "no INVITE reached the failover hop"
        assert invites[0].called_number == "013800138000", (
            f"expected translated number 013800138000, got {invites[0].called_number}"
        )
    finally:
        as_stack.stop()
        mock.stop()


def test_hot_reload_activates_a_new_rule_set_without_restart(
    rules_file: Path, tmp_path: Path
) -> None:
    """Editing the rules file at runtime activates a new rule set (ADR-0004).

    The test loads a rule set, writes a new version with a changed rule set name, polls
    for reload, and asserts the new name is active and the old one is gone.
    """
    # Start from a copy of the shipped rules file so the test does not mutate the
    # original.
    import shutil

    work = tmp_path / "rules.yaml"
    shutil.copy2(rules_file, work)
    store = RuleSetStore(work)
    assert store.current.document.name == "sample-office-routing"

    # Rewrite the name; the rest of the file stays valid.
    text = work.read_text(encoding="utf-8")
    work.write_text(
        text.replace("name: sample-office-routing", "name: sample-office-routing-v2"),
        encoding="utf-8",
    )
    # The reload is pull-based; simulate the loop poll.
    reloaded = store.maybe_reload()
    assert reloaded is True
    assert store.current.document.name == "sample-office-routing-v2"
    # A second poll with no change does nothing.
    assert store.maybe_reload() is False


def test_hot_reload_keeps_previous_rule_set_on_broken_edit(
    rules_file: Path, tmp_path: Path
) -> None:
    """A broken edit leaves the previous rule set active (ADR-0004 fail-safe reload)."""
    import shutil

    work = tmp_path / "rules.yaml"
    shutil.copy2(rules_file, work)
    store = RuleSetStore(work)
    assert store.current.document.name == "sample-office-routing"

    work.write_text("version: 1\nname: [", encoding="utf-8")
    with pytest.raises(AsError) as excinfo:
        store.maybe_reload()
    assert excinfo.value.code is AsErrorCode.RULE_PARSE_ERROR
    assert store.current.document.name == "sample-office-routing"


def test_route_decision_with_no_next_hop_yields_480(tmp_path: Path) -> None:
    """A route decision with no next hop is answered with 480 / AS-ROUTE-003.

    The schema validation at load time rejects a rule that references an unknown next
    hop, so this branch is defended by ``AS-RULE-003`` in normal operation. The 480
    path is still exercised here by removing every next hop from the catalogue after
    loading, simulating a runtime where all hops are down.
    """
    document = """
version: 1
name: no-hop
next_hops:
  - name: hop-a
    address: 127.0.0.1
    port: 15061
rules:
  - rule_id: R-001
    priority: 10
    match:
      called_prefixes: ["0"]
    action:
      kind: route
      translate:
        to_format: national
      next_hops: [hop-a]
"""
    path = tmp_path / "rules.yaml"
    path.write_text(document, encoding="utf-8")
    rule_set = load_rule_set(path)
    # Simulate every next hop being down by clearing the catalogue; the decision then
    # has next hops, but resolving one at runtime would raise AS-ROUTE-003. The pure
    # ``decide`` function still returns the hops from the rule, so we test the resolver
    # directly: a hop that cannot be resolved reports AS-ROUTE-003.
    rule = rule_set.ordered_rules[0]
    # The rule's hops resolve normally; remove the catalogue entry to simulate the hop
    # being unavailable at runtime.
    rule_set._next_hops.clear()  # noqa: SLF001 — test-only simulation of a drained catalogue
    with pytest.raises(AsError) as excinfo:
        rule_set.next_hops_for(rule)
    assert excinfo.value.code is AsErrorCode.ROUTE_NO_NEXT_HOP


def test_translation_to_empty_yields_500(tmp_path: Path) -> None:
    """A translation that strips the entire number and prepends nothing yields 500.

    The routing engine raises ``AS-ROUTE-004`` with a ``500`` status. That the controller
    turns the failure into a ``500`` on the trunk is asserted by
    :func:`test_translation_to_empty_is_answered_500_on_the_trunk`, which drives the stack.
    """
    document = """
version: 1
name: empty-translation
next_hops:
  - name: hop-a
    address: 127.0.0.1
    port: 15061
rules:
  - rule_id: R-EMPTY
    priority: 10
    match:
      called_prefixes: ["123"]
    action:
      kind: route
      translate:
        to_format: national
        strip_prefix: "123"
      next_hops: [hop-a]
"""
    path = tmp_path / "rules.yaml"
    path.write_text(document, encoding="utf-8")
    rule_set = load_rule_set(path)
    with pytest.raises(AsError) as excinfo:
        decide(rule_set, "123")
    assert excinfo.value.code is AsErrorCode.ROUTE_TRANSLATION_FAILED
    assert excinfo.value.sip_status == 500


# ---------------------------------------------------------------------------
# The engine's raises, driven through the real controller and observed on the wire
# ---------------------------------------------------------------------------


def _start_translation_as(rules_path: Path) -> tuple[Any, int, RuleSetStore]:
    """Bind a number-translation AS on loopback UDP with the given rules file.

    Args:
        rules_path: Rules file the AS loads.

    Returns:
        The started stack, the UDP port it listens on, and the rule set store it holds
        (so a test can change the active rule set at runtime).
    """
    from as_app.bootstrap import AsSettings
    from as_app.main import AsStack
    from as_app.observability.tracing import SipMessageRecorder

    as_port = _free_udp_port()
    store = RuleSetStore(rules_path)
    settings = AsSettings(
        _env_file=None,
        sip_listen_address="127.0.0.1",
        sip_listen_port=as_port,
        sbc_peer_address="127.0.0.1",
        sbc_peer_port=_free_udp_port(),
        allowed_peers=["127.0.0.1"],
        rules_file=rules_path,
        internal_api_address="127.0.0.1",
        internal_api_port=_free_udp_port(),
        log_payloads=False,
    )
    stack = AsStack(settings, rule_set_store=store, sip_logger=SipMessageRecorder())
    stack.start()
    return stack, as_port, store


def _final_status_line(responses: list[bytes]) -> str | None:
    """Return the status line of the first final response collected.

    Args:
        responses: Raw SIP datagrams received on the trunk side.

    Returns:
        The status line (status code 200 or above), or ``None`` when none arrived yet.
    """
    for data in responses:
        line = data.decode(errors="replace").split("\r\n", 1)[0]
        if not line.startswith("SIP/2.0 "):
            continue
        try:
            status = int(line.split(" ", 2)[1])
        except (IndexError, ValueError):
            continue
        if status >= 200:
            return line
    return None


def _answer_for_invite(as_port: int, call_id: str, called_number: str) -> str:
    """Place one raw INVITE and return the final response's status line.

    Drives the shared sippy loop until the AS answers with a final response, so the
    assertion is on the bytes the AS put on the trunk rather than on an intermediate
    object.

    Args:
        as_port: UDP port the AS listens on.
        call_id: Call-ID to put on the INVITE.
        called_number: User part of the Request-URI, the number the rules match on.

    Returns:
        The status line of the first final response, or ``""`` when none arrived.
    """
    from sippy.Core.EventDispatcher import ED2
    from sippy.Time.Timeout import Timeout

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind(("127.0.0.1", 0))
        client.setblocking(False)
        local_port = int(client.getsockname()[1])
        invite = (
            f"INVITE sip:{called_number}@127.0.0.1;user=phone SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{local_port};branch=z9hG4bK{call_id};rport\r\n"
            "Max-Forwards: 70\r\n"
            "From: <sip:+86216180001@127.0.0.1>;tag=translation-reject\r\n"
            f"To: <sip:{called_number}@127.0.0.1>\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:127.0.0.1:{local_port}>\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode()
        client.sendto(invite, ("127.0.0.1", as_port))
        responses: list[bytes] = []
        deadline = time.monotonic() + 5.0

        def poll() -> None:
            with contextlib.suppress(TimeoutError, BlockingIOError):
                responses.append(client.recvfrom(65535)[0])
            if _final_status_line(responses) is not None or time.monotonic() >= deadline:
                ED2.breakLoop()

        timer = Timeout(poll, 0.02, -1)
        try:
            ED2.loop(timeout=5.0)
        finally:
            timer.cancel()
        return _final_status_line(responses) or ""


def test_translation_to_empty_is_answered_500_on_the_trunk(tmp_path: Path) -> None:
    """The engine's ``AS-ROUTE-004`` becomes a ``500`` on the trunk leg.

    The pure raise is asserted by ``test_translation_to_empty_yields_500``; this drives the
    real controller so the seam that turns the failure into the trunk answer is exercised.
    The application hook owns that conversion — an ``AsError`` must not escape it
    (ADR-0009 decision 4) — and the caller still sees the pre-P10 ``500``.
    """
    rules_path = tmp_path / "empty_translation_rules.yaml"
    rules_path.write_text(_EMPTY_TRANSLATION_DOCUMENT, encoding="utf-8")
    stack, as_port, _store = _start_translation_as(rules_path)
    try:
        status_line = _answer_for_invite(as_port, "empty-translation-0001", "123")
    finally:
        stack.stop()
    assert status_line == "SIP/2.0 500 Server Internal Error", status_line


def test_unresolvable_hop_is_answered_480_on_the_trunk(tmp_path: Path) -> None:
    """The engine's ``AS-ROUTE-003`` becomes a ``480`` on the trunk leg.

    The schema rejects an unknown hop reference at load, so the runtime failure is
    simulated the way ``test_route_decision_with_no_next_hop_yields_480`` does — the
    catalogue is drained after load — and then driven through the real controller.
    """
    rules_path = tmp_path / "one_hop_rules.yaml"
    rules_path.write_text(_ONE_HOP_DOCUMENT, encoding="utf-8")
    stack, as_port, store = _start_translation_as(rules_path)
    try:
        # Drain the catalogue the controller resolves the matched rule's hop from, so
        # ``next_hops_for`` raises ``AS-ROUTE-003`` for this call.
        store.current._next_hops.clear()  # noqa: SLF001 — test-only drained catalogue
        status_line = _answer_for_invite(as_port, "no-hop-0001", "0")
    finally:
        stack.stop()
    assert status_line == "SIP/2.0 480 Temporarily Unavailable", status_line
