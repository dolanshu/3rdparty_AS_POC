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

"""Integration tests for the M1 signalling path on localhost UDP.

What is exercised here:

- the AS terminates an INVITE from the trunk and originates a new one towards the next
  hop, with headers and SDP unchanged (:data:`as_app.sip_adapter.PASSTHROUGH_HEADERS`);
- a request from an address outside ``ALLOWED_PEERS`` is answered with ``403`` and
  ``AS-PEER-001`` before any call state is created (``AGENT.md`` section 9);
- the process exposes counters and a health endpoint and shuts down cleanly on
  ``SIGTERM``;
- stopping the stack leaves no per-transaction retransmission timer armed in the shared
  sippy loop (P8a: a pending retransmission used to outlive its transaction manager).

Ports are allocated dynamically; nothing here touches 5060.
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
from typing import Any

import pytest

from as_app.sip_adapter import PASSTHROUGH_HEADERS, TRANSACTION_TIMER_NAMES
from s_sbc_mock.uac import CallScenario

pytestmark = pytest.mark.integration

#: A second loopback address, used as a source the AS has not been told to trust.
#: ``127.0.0.0/8`` is loopback on Linux, so it needs no extra interface (RFC 6890).
FOREIGN_TRUNK_ADDRESS = "127.0.0.2"

#: A rule set whose first next hop is an unbound port and whose second hop is left for
#: the test to point at the mock. The call only completes because the controller fails
#: over, and the abandoned attempt towards the first hop is what leaves a transaction
#: retransmitting — the exact condition that used to survive a shutdown (P8a).
_FAILOVER_DOCUMENT = """
version: 1
name: shutdown-test
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

_HEADER_LINE = re.compile(r"^([A-Za-z0-9.\-]+):[ \t]*(.*)$")


def _free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def headers_of(message: str) -> dict[str, str]:
    """Parse the header block of a raw SIP message.

    Args:
        message: A complete SIP message.

    Returns:
        A mapping from lower case header name to value. A repeated header keeps the first
        occurrence, which is enough for the pass-through assertion.
    """
    parsed: dict[str, str] = {}
    head = message.split("\r\n\r\n", 1)[0]
    for line in head.split("\r\n")[1:]:
        match = _HEADER_LINE.match(line)
        if match is None:
            continue
        parsed.setdefault(match.group(1).lower(), match.group(2))
    return parsed


def body_of(message: str) -> str:
    """Return the body of a raw SIP message.

    Args:
        message: A complete SIP message.

    Returns:
        The body without trailing whitespace, empty when there is none.
    """
    parts = message.split("\r\n\r\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def start_line_of(message: str) -> str:
    """Return the start line of a raw SIP message.

    Args:
        message: A complete SIP message.

    Returns:
        The request or status line.
    """
    return message.split("\r\n", 1)[0]


def test_headers_and_sdp_pass_through(trunk_pair) -> None:
    """The outbound INVITE carries the same headers and body as the inbound one."""
    scenario = CallScenario(
        name="pass-through",
        calling_number="+86216180001",
        called_number="+8613800138000",
    )
    call_id = trunk_pair.place_call(scenario)
    outcome = trunk_pair.outcome_for(call_id)
    assert outcome is not None
    # Let the call finish before the fixture releases the ports: the core side of the mock
    # answers on loop-owned timers, which would otherwise fire after the teardown.
    finished = trunk_pair.run_until(lambda: (trunk_pair.outcome_for(call_id) or outcome).released)
    assert finished, "the call did not finish within the timeout"
    assert trunk_pair.mock.uas.received_invites, "no INVITE reached the core side"

    messages = trunk_pair.as_messages.messages_for(call_id)
    inbound = [m for m in messages if m.direction == "in" and m.text.startswith("INVITE ")]
    outbound = [m for m in messages if m.direction == "out" and m.text.startswith("INVITE ")]
    assert len(inbound) == 1, f"expected one inbound INVITE, got {len(inbound)}"
    assert len(outbound) == 1, f"expected one outbound INVITE, got {len(outbound)}"

    sent_headers = headers_of(inbound[0].text)
    forwarded_headers = headers_of(outbound[0].text)
    # Every pass-through header the trunk INVITE carries has to arrive unchanged. The
    # scenario does not carry all of them (a real IMS trigger sends the ones the network
    # uses), so the assertion is on what the mock put on the wire.
    exercised = [name for name in PASSTHROUGH_HEADERS if name in sent_headers]
    assert "p-asserted-identity" in exercised
    for name in exercised:
        assert forwarded_headers.get(name) == sent_headers[name], (
            f"header {name} changed across the B2BUA: "
            f"{sent_headers[name]!r} -> {forwarded_headers.get(name)!r}"
        )
    # Headers the AS owns or regenerates must not be copied from the trunk leg.
    assert forwarded_headers["user-agent"] != sent_headers["user-agent"]
    assert forwarded_headers["call-id"] == sent_headers["call-id"]

    assert body_of(outbound[0].text) == body_of(inbound[0].text), "SDP body changed"
    assert body_of(outbound[0].text) == scenario.sdp_offer.strip()

    # Only the Request-URI differs: it points at the next hop of the AS and carries the
    # translated called number. +8613800138000 is a China Mobile E.164 number; rule
    # R-MOB-CM-40 strips +86 and prepends 0, so the outbound Request-URI user part is
    # 013800138000 (M2 number translation).
    sent_ruri = start_line_of(inbound[0].text).split(" ")[1]
    forwarded_ruri = start_line_of(outbound[0].text).split(" ")[1]
    assert forwarded_ruri != sent_ruri
    assert forwarded_ruri.startswith("sip:013800138000@127.0.0.1:")


def test_request_from_an_unlisted_source_is_rejected(trunk_pair) -> None:
    """An INVITE from an address outside ALLOWED_PEERS is answered 403 / AS-PEER-001."""
    call_id = "peer-check-0001@example.invalid"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.bind((FOREIGN_TRUNK_ADDRESS, 0))
        client.settimeout(1.0)
        local_port = int(client.getsockname()[1])
        invite = (
            "INVITE sip:+8613800138000@127.0.0.1;user=phone SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {FOREIGN_TRUNK_ADDRESS}:{local_port}"
            ";branch=z9hG4bKpeercheck0001;rport\r\n"
            "Max-Forwards: 70\r\n"
            "From: <sip:+86216180001@127.0.0.1>;tag=peer-check-from\r\n"
            "To: <sip:+8613800138000@127.0.0.1>\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:{FOREIGN_TRUNK_ADDRESS}:{local_port}>\r\n"
            "Content-Length: 0\r\n"
            "\r\n"
        ).encode()
        client.sendto(invite, ("127.0.0.1", trunk_pair.as_port))

        responses: list[bytes] = []
        trunk_pair.run_until(lambda: _drain(client, responses), timeout_seconds=3.0)

    assert responses, "the AS did not answer the request from the unlisted source"
    status_line = responses[0].decode(errors="replace").split("\r\n", 1)[0]
    assert status_line.startswith("SIP/2.0 403"), status_line

    trace = trunk_pair.as_stack.tracer.trace_for(call_id)
    assert trace.events, "the rejection is not part of the Call-ID keyed trace"
    assert "403" in trace.events[0].summary
    counters = trunk_pair.as_stack.metrics.snapshot()
    assert counters.errors_by_code.get("AS-PEER-001") == 1


def _drain(client: socket.socket, responses: list[bytes]) -> bool:
    """Read pending datagrams from a socket into a list.

    Args:
        client: The socket to read from.
        responses: List the datagrams are appended to.

    Returns:
        ``True`` when at least one datagram has been collected.
    """
    try:
        data, _ = client.recvfrom(65535)
    except (TimeoutError, BlockingIOError):
        return bool(responses)
    responses.append(data)
    return True


def test_counters_health_endpoint_and_graceful_shutdown(
    rules_file: Path, repo_root: Path, tmp_path: Path
) -> None:
    """The AS process serves health and counters and exits 0 on SIGTERM."""
    as_port = _free_udp_port()
    api_port = _free_udp_port()
    environment = dict(os.environ)
    environment.update(
        {
            "SIP_LISTEN_ADDRESS": "127.0.0.1",
            "SIP_LISTEN_PORT": str(as_port),
            "SBC_PEER_ADDRESS": "127.0.0.1",
            "SBC_PEER_PORT": str(_free_udp_port()),
            "ALLOWED_PEERS": "127.0.0.1",
            "RULES_FILE": str(rules_file),
            "INTERNAL_API_ADDRESS": "127.0.0.1",
            "INTERNAL_API_PORT": str(api_port),
            "LOG_LEVEL": "INFO",
            "LOG_STRUCTURED": "true",
            "LOG_PAYLOADS": "false",
        }
    )
    log_path = tmp_path / "as.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "as_app.main"],
            cwd=repo_root,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            assert _wait_for_health(api_port), "the health endpoint never came up"
            with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/healthz", timeout=5) as page:
                health = json.loads(page.read().decode())
            assert health["status"] == "ok"
            assert health["rule_set_loaded"] is True
            assert health["uptime_seconds"] >= 0.0

            with urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/api/v1/metrics", timeout=5
            ) as page:
                metrics = json.loads(page.read().decode())
            assert metrics["calls_total"] == 0
            assert metrics["calls_by_disposition"] == {}

            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=15) == 0, "SIGTERM did not shut the process down cleanly"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    log_text = log_path.read_text(encoding="utf-8")
    assert "application server starting" in log_text
    assert "startup self-check passed" in log_text
    assert "shutdown complete" in log_text
    assert '"reason": "signal SIGTERM"' in log_text


def _wait_for_health(api_port: int, timeout_seconds: float = 15.0) -> bool:
    """Poll the health endpoint until it answers.

    Args:
        api_port: TCP port of the internal API.
        timeout_seconds: How long to keep polling.

    Returns:
        ``True`` when the endpoint answered, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/healthz", timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _armed_transaction_timers(manager: Any) -> list[Any]:
    """Return the per-transaction timers still armed on a transaction manager.

    Args:
        manager: A sippy ``SipTransactionManager``.

    Returns:
        One entry per transaction timer that has neither fired nor been cancelled.
        ``ED2`` nulls the callback of a timer once it has run, which is how a cancelled
        or already fired timer is told apart from a pending one.
    """
    armed: list[Any] = []
    for table_name in ("tclient", "tserver"):
        transactions = getattr(manager, table_name, None) or {}
        for transaction in transactions.values():
            for timer_name in TRANSACTION_TIMER_NAMES:
                timer = getattr(transaction, timer_name, None)
                if timer is not None and getattr(timer, "cb_func", None) is not None:
                    armed.append(timer)
    return armed


def _armed_loop_timers(manager: Any) -> list[Any]:
    """Return the shared-loop timers still owned by one transaction manager.

    Args:
        manager: A sippy ``SipTransactionManager``.

    Returns:
        The ``ED2`` listeners whose callback still belongs to that manager. This is the
        authoritative view: sippy's own shutdown clears its registries, so only the
        event loop can tell whether anything of the manager is still scheduled.
    """
    from sippy.Core.EventDispatcher import ED2

    return [
        listener
        for listener in ED2.tlisteners
        if listener.cb_func is not None and getattr(listener.cb_func, "__self__", None) is manager
    ]


def test_stopping_the_stack_leaves_no_transaction_timer_armed(tmp_path: Path) -> None:
    """Nothing owned by a stopped transaction manager stays scheduled (P8a).

    The call first fails over from an unreachable next hop, so the AS has an INVITE
    client transaction that nobody answered — one that keeps retransmitting for as long
    as RFC 3261 timer B allows. Stopping the stack has to cancel that retransmission:
    ``SipTransactionManager.shutdown()`` releases the UDP sockets and drops its own
    registries but cancels only its cache-purge timer, so any surviving timer fires into
    a manager whose ``global_config`` is ``None``. In the test suite, where one process
    shares one ``ED2`` loop, that stale timer is what made later tests fail at random.

    Args:
        tmp_path: Per-test temporary directory for the generated rules file.
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
    rules_path = tmp_path / "failover_rules.yaml"
    rules_path.write_text(
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
        rules_file=rules_path,
        internal_api_address="127.0.0.1",
        internal_api_port=api_port,
        log_payloads=False,
    )
    stack = AsStack(settings, sip_logger=SipMessageRecorder())
    stack.start()
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
        call_id = mock.uac.place_call(
            CallScenario(
                name="failover",
                calling_number="+86216180001",
                called_number="+8613800138000",
                ring_seconds=0.1,
                talk_seconds=0.1,
            )
        )
        outcome = mock.uac.outcome_for(call_id)
        assert outcome is not None
        state: dict[str, bool] = {"done": False}
        deadline = time.monotonic() + 15.0

        def poll() -> None:
            if (mock.uac.outcome_for(call_id) or outcome).released or time.monotonic() >= deadline:
                state["done"] = True
                ED2.breakLoop()

        call_timer = Timeout(poll, 0.02, -1)
        try:
            ED2.loop(timeout=15.0)
        finally:
            call_timer.cancel()
        assert state["done"], f"failover call {call_id} did not finish within the timeout"

        # Premise of the regression: the attempt towards the unreachable hop is still
        # retransmitting when the stack stops. Without it the test below would pass even
        # if the cancellation did nothing at all.
        manager = stack.transaction_manager
        assert manager is not None
        pending = _armed_transaction_timers(manager)
        assert pending, "the abandoned first-hop INVITE left no pending retransmission"

        stack.stop()
        armed_after_stop = _armed_loop_timers(manager)
        assert not armed_after_stop, (
            f"{len(armed_after_stop)} timer(s) still armed on a stopped transaction manager"
        )

        # Drive the shared loop past the instants at which the retransmission would have
        # fired, so nothing is left merely because it has not run yet.
        def settle() -> None:
            ED2.breakLoop()

        settle_timer = Timeout(settle, 1.5, 1)
        try:
            ED2.loop(timeout=4.0)
        finally:
            settle_timer.cancel()
        assert not _armed_loop_timers(manager), (
            "a transaction timer was re-armed after the manager had been shut down"
        )
    finally:
        stack.stop()
        mock.stop()
