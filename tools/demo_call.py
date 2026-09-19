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

"""Place one real trunk call and narrate what the AS did with it.

This is the ``make demo`` entry point (``AGENT.md`` section 4.4). It runs a real call over
loopback UDP between the emulated S-CSCF, the AS and the emulated core network, and prints
the routing decision, the Request-URI before and after number translation, the message
flow and the final outcome. Nothing is written to the repository: the demo is a
repeatable, read-only transcript a reviewer can run while reading the code.

The call plumbing is shared with ``tools/capture_call.py`` (``run_call``); only the
narration differs, so the demo and the captured samples can never disagree about what the
stack does. Ports are allocated dynamically, so the demo never collides with a running
process and never uses 5060 by accident (``AGENT.md`` section 11).

Usage:
    uv run python tools/demo_call.py
    uv run python tools/demo_call.py --called +8613800138000
    uv run python tools/demo_call.py --as-port 45060 --core-port 45061
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for path in (str(REPO_ROOT / "src"), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from capture_call import (  # noqa: E402
    DEFAULT_SCENARIO,
    CallRun,
    free_udp_port,
    message_token,
    run_call,
)

from as_app.sip_adapter import outbound_call_id  # noqa: E402
from s_sbc_mock.uac import CallScenario  # noqa: E402

#: Width of the left column of the transcript, so every value lines up.
_LABEL_WIDTH = 12


def first_line(text: str) -> str:
    """Return the start line of a raw SIP message.

    Args:
        text: A complete SIP message.

    Returns:
        The first line, without the trailing CRLF.
    """
    return text.split("\r\n", 1)[0]


def request_uri(text: str) -> str:
    """Return the Request-URI of a raw SIP request.

    Args:
        text: A complete SIP message.

    Returns:
        The Request-URI, or the start line when it cannot be isolated.
    """
    fields = first_line(text).split(" ")
    return fields[1] if len(fields) > 1 else first_line(text)


def leg_of(peer: str, core_port: int) -> str:
    """Name the leg a captured message travelled on.

    Args:
        peer: Remote address the stack reported, for example ``127.0.0.1:15061``.
        core_port: UDP port of the mock core side, the AS next hop.

    Returns:
        ``core`` for the next-hop leg, ``trunk`` otherwise.
    """
    return "core" if peer.endswith(f":{core_port}") else "trunk"


def trace_attribute(run: CallRun, key: str) -> Any | None:
    """Return the first trace attribute with a given name.

    Args:
        run: The completed call.
        key: Attribute name, for example ``translated_number``.

    Returns:
        The raw attribute value, or ``None`` when no event carries it.
    """
    for event in run.trace.trace_for(run.call_id).events:
        if key in event.attributes:
            return event.attributes[key]
    return None


def decision_event_summary(run: CallRun) -> str | None:
    """Return the summary of the first trace event that carries a routing decision.

    Args:
        run: The completed call.

    Returns:
        For example ``route: matched R-MOB-CM-40``, or ``None`` when the call was never
        routed.
    """
    for event in run.trace.trace_for(run.call_id).events:
        if event.rule_id:
            return event.summary
    return None


def narrate(run: CallRun, *, rules_file: Path, as_port: int, scenario: CallScenario) -> int:
    """Print the transcript of one call.

    Args:
        run: The completed call.
        rules_file: Rules file the AS loaded.
        as_port: UDP port the AS received the trunk on.
        scenario: The call that was placed.

    Returns:
        ``0`` when the call was answered and released normally, ``1`` otherwise.
    """
    # Both legs of the call: the trunk Call-ID and the derived one the AS originates with.
    messages = run.recorder.messages_for_any((run.call_id, outbound_call_id(run.call_id)))
    decision_summary = decision_event_summary(run)
    disposition = decision_summary.split(":", 1)[0].strip() if decision_summary else None
    events = run.trace.trace_for(run.call_id).events
    rule_id_text = next((event.rule_id for event in events if event.rule_id), None)
    translated = trace_attribute(run, "translated_number")
    next_hops = trace_attribute(run, "next_hops")
    served_by = trace_attribute(run, "next_hop")

    trunk_invite = next(
        (
            message
            for message in messages
            if message.direction == "in"
            and message_token(message.text) == "invite"
            and leg_of(message.peer, run.core_port) == "trunk"
        ),
        None,
    )
    core_invite = next(
        (
            message
            for message in messages
            if message.direction == "out"
            and message_token(message.text) == "invite"
            and leg_of(message.peer, run.core_port) == "core"
        ),
        None,
    )

    print("3rd-party AS POC - trunk call demo")
    print("topology   : emulated S-CSCF --UDP--> AS (B2BUA) --UDP--> emulated core network")
    print(f"ports      : as 127.0.0.1:{as_port}, trunk {run.trunk_port}, core {run.core_port}")
    resolved_rules = Path(rules_file).expanduser().resolve()
    try:
        shown_rules = resolved_rules.relative_to(REPO_ROOT)
    except ValueError:
        shown_rules = resolved_rules
    print(f"rules      : {shown_rules}")
    print()
    print("[1/5] call placed")
    print(f"{'scenario':<{_LABEL_WIDTH}}: {scenario.name}")
    print(f"{'caller':<{_LABEL_WIDTH}}: {scenario.calling_number}")
    print(f"{'called':<{_LABEL_WIDTH}}: {scenario.called_number}")
    print(f"{'Call-ID':<{_LABEL_WIDTH}}: {run.call_id}")
    if trunk_invite is not None:
        print(f"{'trunk INVITE':<{_LABEL_WIDTH}}: {first_line(trunk_invite.text)}")
    print()
    print("[2/5] routing decision")
    print(f"{'rule':<{_LABEL_WIDTH}}: {rule_id_text}")
    print(f"{'disposition':<{_LABEL_WIDTH}}: {disposition}")
    if translated:
        print(f"{'translation':<{_LABEL_WIDTH}}: called number -> {translated}")
    if isinstance(next_hops, list) and next_hops:
        ordered_hops = " -> ".join(str(hop) for hop in next_hops)
        print(f"{'next hops':<{_LABEL_WIDTH}}: {ordered_hops}")
    print(f"{'served by':<{_LABEL_WIDTH}}: {served_by or '-'}")
    print()
    print("[3/5] next-hop side (after translation)")
    if core_invite is not None:
        print(f"{'core INVITE':<{_LABEL_WIDTH}}: {first_line(core_invite.text)}")
    print()
    print(f"[4/5] message flow ({len(messages)} messages on the wire)")
    for index, message in enumerate(messages, start=1):
        leg = leg_of(message.peer, run.core_port)
        arrow = "->" if message.direction == "out" else "<-"
        print(
            f"      {index:02d} {leg:<5} {arrow} "
            f"{message_token(message.text):<6} {first_line(message.text)}"
        )
    print()
    print("[5/5] outcome")
    status = run.outcome.status if run.outcome.status is not None else "abandoned"
    print(f"{'status':<{_LABEL_WIDTH}}: {status}")
    print(f"{'released':<{_LABEL_WIDTH}}: {run.outcome.released}")
    print(f"{'cancelled':<{_LABEL_WIDTH}}: {run.outcome.cancelled}")
    print()
    accepted = run.outcome.released and run.outcome.status == 200
    if accepted:
        print("demo result: call answered and released; number translation applied on the wire")
        return 0
    if run.outcome.released and run.outcome.status is not None and run.outcome.status >= 400:
        print(
            f"demo result: call rejected with SIP {run.outcome.status} - "
            "the configured policy decision for this number"
        )
        return 1
    print("demo result: call did not complete normally - see the outcome above")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Run the demo.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` when the call completed, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description="Run one real trunk call and narrate it")
    parser.add_argument("--as-port", type=int, default=None, help="UDP port of the AS")
    parser.add_argument(
        "--core-port", type=int, default=None, help="UDP port of the mock core side"
    )
    parser.add_argument(
        "--trunk-port", type=int, default=None, help="UDP port of the mock trunk side"
    )
    parser.add_argument(
        "--rules-file", type=Path, default=REPO_ROOT / "config" / "routing_rules.yaml"
    )
    parser.add_argument("--caller", default=DEFAULT_SCENARIO.calling_number)
    parser.add_argument("--called", default=DEFAULT_SCENARIO.called_number)
    args = parser.parse_args(argv)

    as_port = args.as_port or free_udp_port()
    core_port = args.core_port or free_udp_port()
    trunk_port = args.trunk_port or free_udp_port()
    scenario = CallScenario(
        name=DEFAULT_SCENARIO.name, calling_number=args.caller, called_number=args.called
    )
    try:
        run = run_call(
            as_port=as_port,
            core_port=core_port,
            trunk_port=trunk_port,
            rules_file=args.rules_file,
            scenario=scenario,
        )
    except TimeoutError as error:
        print(f"demo failed: {error}", file=sys.stderr)
        return 1
    return narrate(run, rules_file=args.rules_file, as_port=as_port, scenario=scenario)


if __name__ == "__main__":
    raise SystemExit(main())
