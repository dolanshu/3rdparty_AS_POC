#!/usr/bin/env python3
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

"""Place two real calls through the anti-fraud AS and narrate the verdicts.

This is the standalone demo of the second AS instance: the same mock S-SBC drives the
anti-fraud AS on its own ports, once with a caller the screening data allows and once with a
caller on the block list. The allowed call is relayed to the emulated core and answered; the
rejected call is answered by the AS itself with ``608 Rejected`` and never reaches the core,
because the reject path is UAS behaviour and originates no second leg (ADR-0007).

Nothing is written to the repository: the demo is a repeatable, read-only transcript. Ports
are allocated dynamically, so it never collides with a running process and never uses 5060.

Usage:
    uv run python tools/demo_fraud_call.py
    uv run python tools/demo_fraud_call.py --blocked-caller +8613400000002
    uv run python tools/demo_fraud_call.py --as-port 45062 --core-port 45061
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sippy.Core.EventDispatcher import ED2  # noqa: E402
from sippy.Time.Timeout import Timeout  # noqa: E402

from anti_fraud_as.bootstrap import FraudAsSettings  # noqa: E402
from anti_fraud_as.main import FraudAsStack  # noqa: E402
from as_app.observability.logging import configure_logging  # noqa: E402
from as_app.observability.tracing import SipMessageRecorder  # noqa: E402
from s_sbc_mock.main import MockConfig, SMockApplication  # noqa: E402
from s_sbc_mock.uac import CallOutcome, CallScenario  # noqa: E402

#: Width of the left column of the transcript, so every value lines up.
_LABEL_WIDTH = 13

#: A caller the shipped screening data allows (not on any list, healthy window).
ALLOWED_CALLER = "+86216180001"

#: A caller the shipped screening data blocks (first entry of the block list).
BLOCKED_CALLER = "+8613400000001"

#: Called number of both demo calls; the anti-fraud AS never rewrites it.
CALLED_NUMBER = "+8613800138000"

#: Seconds a call is given to finish before the demo gives up.
CALL_TIMEOUT_SECONDS = 15.0

#: Poll interval of the loop driver, in seconds.
POLL_SECONDS = 0.02


def free_udp_port() -> int:
    """Reserve a free UDP port on loopback.

    Returns:
        A port number that was free when the function ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def draw_loop_until(predicate: Any, timeout_seconds: float = CALL_TIMEOUT_SECONDS) -> bool:
    """Drive the sippy event loop until a condition holds or the timeout expires.

    Args:
        predicate: Condition that marks the end of the call.
        timeout_seconds: How long to keep driving the loop.

    Returns:
        ``True`` when the condition became true, ``False`` on timeout.
    """
    state = {"done": False}

    def poll() -> None:
        if predicate():
            state["done"] = True
            ED2.breakLoop()

    timer = Timeout(poll, POLL_SECONDS, -1)
    deadline = Timeout(ED2.breakLoop, timeout_seconds, 1)
    try:
        ED2.loop(timeout=timeout_seconds)
    finally:
        timer.cancel()
        deadline.cancel()
    return bool(state["done"] or predicate())


def verdict_attributes(stack: FraudAsStack, call_id: str) -> dict[str, Any]:
    """Return the trace attributes of the verdict event of one call.

    Args:
        stack: The running anti-fraud stack.
        call_id: SIP Call-ID of the call.

    Returns:
        The attributes of the ``verdict`` event, empty when the call has none.
    """
    for event in stack.tracer.trace_for(call_id).events:
        if event.method == "verdict":
            return dict(event.attributes)
    return {}


def narrate_call(
    index: int,
    total: int,
    title: str,
    stack: FraudAsStack,
    scenario: CallScenario,
    call_id: str,
    outcome: CallOutcome,
) -> None:
    """Print the transcript of one screened call.

    Args:
        index: One-based position of the call in the demo.
        total: Number of calls in the demo.
        title: Short description of what this call should demonstrate.
        stack: The running anti-fraud stack.
        scenario: The call that was placed.
        call_id: SIP Call-ID of the call.
        outcome: What the trunk side observed.
    """
    attributes = verdict_attributes(stack, call_id)
    declared = attributes.get("sip_608_declared")
    print(f"[{index}/{total}] {title}")
    print(f"{'caller':<{_LABEL_WIDTH}}: {scenario.calling_number}")
    print(f"{'called':<{_LABEL_WIDTH}}: {scenario.called_number}")
    print(f"{'Call-ID':<{_LABEL_WIDTH}}: {call_id}")
    print(f"{'verdict':<{_LABEL_WIDTH}}: {attributes.get('verdict', 'unknown')}")
    print(f"{'signal':<{_LABEL_WIDTH}}: {attributes.get('screen_source', '-')}")
    print(f"{'reason':<{_LABEL_WIDTH}}: {attributes.get('screen_reason', '-')}")
    if "list_entry" in attributes:
        print(f"{'list entry':<{_LABEL_WIDTH}}: {attributes['list_entry']}")
    print(f"{'reputation':<{_LABEL_WIDTH}}: {attributes.get('reputation', '-')}")
    print(f"{'calls in window':<{_LABEL_WIDTH}}: {attributes.get('calls_in_window', '-')}")
    print(f"{'sip.608 declared':<{_LABEL_WIDTH}}: {declared}")
    print(f"{'final status':<{_LABEL_WIDTH}}: {outcome.status}")
    print(f"{'released':<{_LABEL_WIDTH}}: {outcome.released}")
    if outcome.status == 608:
        print(
            f"{'second leg':<{_LABEL_WIDTH}}: none - the AS answered from the UAS side "
            "(RFC 8688, no Call-Info)"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    """Run the anti-fraud screening demo.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` when both calls behaved as intended, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description="Run the anti-fraud AS screening demo")
    parser.add_argument("--as-port", type=int, default=None, help="UDP port of the AS")
    parser.add_argument(
        "--core-port", type=int, default=None, help="UDP port of the mock core side"
    )
    parser.add_argument(
        "--trunk-port", type=int, default=None, help="UDP port of the mock trunk side"
    )
    parser.add_argument(
        "--screening-file",
        type=Path,
        default=REPO_ROOT / "config" / "caller_screening.yaml",
    )
    parser.add_argument("--allowed-caller", default=ALLOWED_CALLER)
    parser.add_argument("--blocked-caller", default=BLOCKED_CALLER)
    args = parser.parse_args(argv)

    # The demo prints its own transcript; the AS's structured event log is for the operator,
    # not for the transcript. With no handler installed, the reject path's WARNING record
    # reached ``logging.lastResort`` and leaked a bare ``call rejected by screening`` line into
    # the demo output. Configuring the root logger at ERROR keeps routine events off the
    # transcript while a genuine failure still prints.
    configure_logging("ERROR", structured=False)

    as_port = args.as_port or free_udp_port()
    core_port = args.core_port or free_udp_port()
    trunk_port = args.trunk_port or free_udp_port()

    settings = FraudAsSettings(
        _env_file=None,
        fraud_sip_listen_address="127.0.0.1",
        fraud_sip_listen_port=as_port,
        fraud_sbc_peer_address="127.0.0.1",
        fraud_sbc_peer_port=core_port,
        fraud_allowed_peers=["127.0.0.1"],
        fraud_screening_file=args.screening_file,
        log_payloads=False,
    )
    recorder = SipMessageRecorder()
    stack = FraudAsStack(settings, sip_logger=recorder)
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

    print("anti-fraud AS POC - screening demo")
    print(
        "topology   : emulated S-CSCF --UDP--> anti-fraud AS (608 Rejected) --UDP--> "
        "emulated core network"
    )
    print(f"ports      : anti-fraud-as 127.0.0.1:{as_port}, trunk {trunk_port}, core {core_port}")
    try:
        shown = Path(args.screening_file).expanduser().resolve().relative_to(REPO_ROOT)
    except ValueError:
        shown = Path(args.screening_file)
    print(f"screening  : {shown}")
    print("verdict    : allow list -> block list -> call-rate window -> reputation")
    print()

    results: list[bool] = []
    try:
        for position, (title, caller) in enumerate(
            (
                ("call allowed and relayed", args.allowed_caller),
                ("call rejected with 608", args.blocked_caller),
            ),
            start=1,
        ):
            scenario = CallScenario(
                name=f"screen-{position}", calling_number=caller, called_number=CALLED_NUMBER
            )
            before = len(mock.uas.received_invites)
            call_id = mock.uac.place_call(scenario)
            outcome = mock.uac.outcome_for(call_id)
            if outcome is None:
                print(f"demo failed: call {call_id} produced no outcome", file=sys.stderr)
                return 1

            def released(call_id: str = call_id, outcome: CallOutcome = outcome) -> bool:
                return bool((mock.uac.outcome_for(call_id) or outcome).released)

            draw_loop_until(released)
            final = mock.uac.outcome_for(call_id) or outcome
            narrate_call(position, 2, title, stack, scenario, call_id, final)
            expected = 200 if position == 1 else 608
            results.append(final.status == expected)
            print(
                f"      expected SIP {expected}, observed {final.status}; core INVITE delta "
                f"{len(mock.uas.received_invites) - before}"
            )
            print()
    finally:
        stack.stop()
        mock.stop()

    if all(results):
        print("demo result: allow relayed to the core, reject answered 608 by the AS alone")
        return 0
    print("demo result: at least one call did not behave as the screening data says it should")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
