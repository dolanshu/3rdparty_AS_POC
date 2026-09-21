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

# OCR-R10 TODO: ~120 lines of helpers (draw_loop_until, verdict_attributes,
# decision_rule, _icid_of, _header_value, received_invite_icid, chain setup) are
# duplicated in tools/chained_as_probe.py. Extract to a shared module under
# tools/ (like capture_call already does) before the two drift further.

"""Run the chained AS topology and narrate what every hop saw.

This is the demo of P9's chain of ``docs/architecture/lld.md`` section 10: two B2BUAs in
series, ``emulated S-CSCF -> AS-1 (anti-fraud) -> AS-2 (number translation) -> emulated
core``, wired **by configuration only** — AS-1's allowed-relay next hop points at AS-2's
listen address, and AS-2's next hop is the routing catalogue (ADR-0008 decision 1). It runs
the real stacks in one interpreter, as ``tools/demo_call.py`` and ``tools/demo_fraud_call.py``
do, and places two calls:

1. an **allowed** call, driven to ``200 OK`` through both B2BUA instances — it prints AS-1's
   verdict, AS-2's matched rule, the translated number the core received and the outcome;
2. a **rejected** call, answered ``608 Rejected`` by AS-1 — it shows that **no** call reached
   AS-2 and **no** INVITE reached the core (the short-circuit asserted as an absence, not as a
   status code).

It also makes the cross-AS correlation question visible rather than papered over:

- the dialog ``Call-ID`` each hop saw — the S-CSCF's, AS-2's trunk one and the core's — is
  **three different values**, because every leg derives its own from the previous one
  (``outbound_call_id()``). The demo asserts each transition is exactly that derivation.
- the ``P-Charging-Vector``'s **ICID** each hop saw is the **same** value, because both AS
  instances forward it verbatim (``PASSTHROUGH_HEADERS``). The demo asserts the equality.

Those two halves are the measured form of ``REQ-NF-016`` / ``REQ-F-028`` and ADR-0008
decision 4: the dialog identity is regenerated per leg, while the standard end-to-end key
is passed through and no observability surface is keyed on it.

**It is a guard, not a printout**: it exits non-zero when any of those properties fails.
It writes nothing to the repository, and every port is allocated dynamically, so it never
collides with a running process and never uses 5060 (``AGENT.md`` section 11).

Usage:
    uv run python tools/demo_chained_call.py
    uv run python tools/demo_chained_call.py --blocked-caller +8613400000002
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for path in (str(REPO_ROOT / "src"), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from capture_call import free_udp_port, rewrite_next_hop_ports  # noqa: E402
from sippy.Core.EventDispatcher import ED2  # noqa: E402
from sippy.Time.Timeout import Timeout  # noqa: E402

from anti_fraud_as.bootstrap import FraudAsSettings  # noqa: E402
from anti_fraud_as.main import FraudAsStack  # noqa: E402
from as_app.bootstrap import AsSettings  # noqa: E402
from as_app.main import AsStack  # noqa: E402
from as_app.observability.logging import configure_logging  # noqa: E402
from as_app.observability.metrics import MetricsRegistry  # noqa: E402
from as_app.observability.tracing import SipMessageRecorder, TraceRecorder  # noqa: E402
from as_app.sip_adapter import outbound_call_id  # noqa: E402
from s_sbc_mock.main import MockConfig, SMockApplication  # noqa: E402
from s_sbc_mock.uac import CallOutcome, CallScenario  # noqa: E402

#: Width of the left column of the transcript, so every value lines up.
_LABEL_WIDTH = 18

#: A caller the shipped screening data allows (not on any list, healthy window).
ALLOWED_CALLER = "+86216180001"

#: A caller the shipped screening data blocks (first entry of the block list).
BLOCKED_CALLER = "+8613400000001"

#: Called number of both demo calls; AS-1 never rewrites it, AS-2 translates it.
CALLED_NUMBER = "+8613800138000"

#: Seconds a call is given to finish before the demo gives up.
CALL_TIMEOUT_SECONDS = 15.0

#: Poll interval of the loop driver, in seconds.
POLL_SECONDS = 0.02

#: The header whose ``icid-value`` is the standard end-to-end correlation key on an IMS
#: trunk (3GPP TS 24.229). It is in ``PASSTHROUGH_HEADERS``, so both AS instances forward it.
_CHARGING_VECTOR_HEADER = "p-charging-vector"


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


def decision_rule(stack: AsStack, call_id: str) -> str | None:
    """Return the routing rule the number-translation AS applied to a call.

    Args:
        stack: The running number-translation stack.
        call_id: SIP Call-ID of the call as AS-2 saw it on its trunk leg.

    Returns:
        The matched rule identifier, or ``None`` when the call was never routed.
    """
    for event in stack.tracer.trace_for(call_id).events:
        if event.rule_id:
            return event.rule_id
    return None


def _icid_of(value: str | None) -> str | None:
    """Return the ``icid-value`` parameter of a ``P-Charging-Vector`` header value.

    Args:
        value: The header value, for example ``icid-value=poc-x;icid-generated-at=y``.

    Returns:
        The ``icid-value``, or ``None`` when the parameter is absent.
    """
    if not value:
        return None
    for parameter in value.split(";"):
        key, _, parameter_value = parameter.partition("=")
        if key.strip().lower() == "icid-value":
            return parameter_value.strip()
    return None


def _header_value(headers: dict[str, str] | None, name: str) -> str | None:
    """Return a header value by case-insensitive name.

    Args:
        headers: The captured header mapping.
        name: Header name to look up, compared lower-cased.

    Returns:
        The header value, or ``None`` when the header is absent.
    """
    for header_name, header_value in (headers or {}).items():
        if header_name.lower() == name:
            return header_value
    return None


def received_invite_icid(recorder: SipMessageRecorder) -> str | None:
    """Return the ICID of the INVITE an AS received on its trunk leg.

    Reads the header case-insensitively off the raw message text, because sippy renders an
    unknown header name with only its first letter capitalised (``SipGenericHF``), so the
    wire spelling is ``P-charging-vector``.

    Args:
        recorder: The SIP message recorder given to that AS.

    Returns:
        The ICID, or ``None`` when the recorder holds no received INVITE.
    """
    for message in recorder.messages:
        if message.direction != "in" or not message.text.upper().startswith("INVITE"):
            continue
        for line in message.text.splitlines():
            header_name, _, header_value = line.partition(":")
            if header_name.strip().lower() == _CHARGING_VECTOR_HEADER:
                return _icid_of(header_value)
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the chained-topology demo and print the transcript.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` when every property held, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description="Run the chained AS topology demo")
    parser.add_argument("--allowed-caller", default=ALLOWED_CALLER)
    parser.add_argument("--blocked-caller", default=BLOCKED_CALLER)
    parser.add_argument(
        "--rules-file", type=Path, default=REPO_ROOT / "config" / "routing_rules.yaml"
    )
    parser.add_argument(
        "--screening-file",
        type=Path,
        default=REPO_ROOT / "config" / "caller_screening.yaml",
    )
    args = parser.parse_args(argv)

    # The demo prints its own transcript; the AS's structured event log is for the operator.
    configure_logging("ERROR", structured=False)

    as1_port = free_udp_port()  # AS-1: the anti-fraud instance
    as2_port = free_udp_port()  # AS-2: the number-translation instance
    core_port = free_udp_port()  # the emulated core network, AS-2's next hop
    trunk_port = free_udp_port()  # the emulated S-CSCF trigger, AS-1's trunk peer

    # AS-2 selects its next hop from the rule set, so the shipped catalogue ports have to be
    # rewritten to the dynamically allocated core port — the same convenience the capture
    # tool uses. Nothing is left behind: the copy lives in a temporary directory.
    rules_dir = Path(tempfile.mkdtemp(prefix="as-poc-chain-demo-"))
    chained_rules = rewrite_next_hop_ports(args.rules_file, core_port, rules_dir)

    # Each stack gets its own trace recorder and metrics registry, because both default to
    # process-wide singletons and a shared recorder would mix the two instances' traces. The
    # SIP message recorders are held by name so the ICID each hop saw can be read back.
    as1_recorder = SipMessageRecorder()
    as2_recorder = SipMessageRecorder()
    as1 = FraudAsStack(
        FraudAsSettings(
            _env_file=None,
            fraud_sip_listen_address="127.0.0.1",
            fraud_sip_listen_port=as1_port,
            fraud_sbc_peer_address="127.0.0.1",
            fraud_sbc_peer_port=as2_port,
            fraud_allowed_peers=["127.0.0.1"],
            fraud_screening_file=args.screening_file,
            log_payloads=False,
        ),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
        sip_logger=as1_recorder,
    )
    as2 = AsStack(
        AsSettings(
            _env_file=None,
            sip_listen_address="127.0.0.1",
            sip_listen_port=as2_port,
            sbc_peer_address="127.0.0.1",
            sbc_peer_port=core_port,
            allowed_peers=["127.0.0.1"],
            rules_file=chained_rules,
            log_payloads=False,
        ),
        metrics=MetricsRegistry(),
        tracer=TraceRecorder(),
        sip_logger=as2_recorder,
    )
    mock = SMockApplication(
        MockConfig(
            listen_address="127.0.0.1",
            listen_port=core_port,
            as_address="127.0.0.1",
            as_port=as1_port,
        ),
        sip_logger=SipMessageRecorder(),
        uac_local_port=trunk_port,
    )

    as1.start()
    as2.start()
    mock.start()

    print("chained AS POC - two B2BUAs in series, wired by configuration only")
    print(
        "topology   : emulated S-CSCF --UDP--> AS-1 anti-fraud --UDP--> AS-2 number "
        "translation --UDP--> emulated core"
    )
    print(
        f"ports      : AS-1 127.0.0.1:{as1_port}, AS-2 127.0.0.1:{as2_port}, "
        f"trunk {trunk_port}, core {core_port}"
    )
    print("wiring     : AS-1 next hop = AS-2 listen address; AS-2 next hop = the rule set")
    print()

    results: list[bool] = []
    try:
        # ---- 1. allowed call: relayed by AS-1, translated by AS-2, answered by the core ----
        scenario = CallScenario(
            name="chained-allow", calling_number=args.allowed_caller, called_number=CALLED_NUMBER
        )
        core_before = len(mock.uas.received_invites)
        uac_call_id = mock.uac.place_call(scenario)
        outcome = mock.uac.outcome_for(uac_call_id)
        if outcome is None:
            print("demo failed: the allowed call produced no outcome", file=sys.stderr)
            return 1

        def released(call_id: str = uac_call_id, first: CallOutcome = outcome) -> bool:
            return bool((mock.uac.outcome_for(call_id) or first).released)

        draw_loop_until(released)
        final = mock.uac.outcome_for(uac_call_id) or outcome

        verdict = verdict_attributes(as1, uac_call_id)
        as2_call_ids = as2.tracer.known_call_ids()
        as2_trunk_call_id = as2_call_ids[0] if as2_call_ids else "-"
        core_invites = mock.uas.received_invites[core_before:]
        core_invite = core_invites[-1] if core_invites else None
        core_call_id = core_invite.call_id if core_invite is not None else "-"

        print("[1/2] allowed call relayed through both AS instances")
        print(f"{'caller':<{_LABEL_WIDTH}}: {scenario.calling_number}")
        print(f"{'called':<{_LABEL_WIDTH}}: {scenario.called_number}")
        print(f"{'AS-1 verdict':<{_LABEL_WIDTH}}: {verdict.get('verdict', 'unknown')}")
        print(f"{'AS-1 signal':<{_LABEL_WIDTH}}: {verdict.get('screen_source', '-')}")
        print(f"{'AS-2 rule':<{_LABEL_WIDTH}}: {decision_rule(as2, as2_trunk_call_id)}")
        print(
            f"{'core called number':<{_LABEL_WIDTH}}: "
            f"{core_invite.called_number if core_invite else '-'}"
        )
        print(f"{'final status':<{_LABEL_WIDTH}}: {final.status}")
        print(f"{'released':<{_LABEL_WIDTH}}: {final.released}")
        print()
        print("  the dialog Call-ID is regenerated on every leg (three distinct values):")
        print(f"{'S-CSCF Call-ID':<{_LABEL_WIDTH}}: {uac_call_id}")
        print(f"{'AS-2 trunk Call-ID':<{_LABEL_WIDTH}}: {as2_trunk_call_id}")
        print(f"{'core Call-ID':<{_LABEL_WIDTH}}: {core_call_id}")
        hop_call_ids = [uac_call_id, as2_trunk_call_id, core_call_id]
        per_leg_ok = as2_trunk_call_id == outbound_call_id(
            uac_call_id
        ) and core_call_id == outbound_call_id(as2_trunk_call_id)
        distinct_ok = len(set(hop_call_ids)) == len(hop_call_ids)
        print(f"{'distinct Call-IDs':<{_LABEL_WIDTH}}: {len(set(hop_call_ids))}")
        print(
            f"{'Call-ID per leg':<{_LABEL_WIDTH}}: {per_leg_ok} "
            "(each transition is outbound_call_id of the previous one)"
        )
        print()
        print("  the end-to-end ICID survives the whole chain (one value at every hop):")
        core_icid = _icid_of(
            _header_value(core_invite.headers, _CHARGING_VECTOR_HEADER) if core_invite else None
        )
        icids = [received_invite_icid(as1_recorder), received_invite_icid(as2_recorder), core_icid]
        icid_preserved = all(icid is not None for icid in icids) and len(set(icids)) == 1
        print(f"{'S-CSCF ICID':<{_LABEL_WIDTH}}: {icids[0]}")
        print(f"{'AS-2 ICID':<{_LABEL_WIDTH}}: {icids[1]}")
        print(f"{'core ICID':<{_LABEL_WIDTH}}: {icids[2]}")
        print(f"{'ICID preserved':<{_LABEL_WIDTH}}: {icid_preserved}")
        print()

        allowed_ok = (
            final.released
            and final.status == 200
            and len(core_invites) == 1
            and core_invite is not None
            and core_invite.called_number == "013800138000"
            and verdict.get("verdict") == "allow"
        )
        results.append(allowed_ok)

        # ---- 2. rejected call: answered 608 by AS-1, never reaches AS-2 or the core ----
        as2_before = len(as2.tracer.known_call_ids())
        core_before = len(mock.uas.received_invites)
        blocked = CallScenario(
            name="chained-reject", calling_number=args.blocked_caller, called_number=CALLED_NUMBER
        )
        rejected_call_id = mock.uac.place_call(blocked)
        rejected_outcome = mock.uac.outcome_for(rejected_call_id)
        if rejected_outcome is None:
            print("demo failed: the rejected call produced no outcome", file=sys.stderr)
            return 1
        draw_loop_until(
            lambda call_id=rejected_call_id, first=rejected_outcome: bool(
                (mock.uac.outcome_for(call_id) or first).released
            )
        )
        rejected_final = mock.uac.outcome_for(rejected_call_id) or rejected_outcome
        as2_delta = len(as2.tracer.known_call_ids()) - as2_before
        core_delta = len(mock.uas.received_invites) - core_before
        rejected_verdict = verdict_attributes(as1, rejected_call_id).get("verdict", "unknown")

        print("[2/2] rejected call short-circuits at AS-1")
        print(f"{'caller':<{_LABEL_WIDTH}}: {blocked.calling_number}")
        print(f"{'AS-1 verdict':<{_LABEL_WIDTH}}: {rejected_verdict}")
        print(
            f"{'final status':<{_LABEL_WIDTH}}: {rejected_final.status} "
            "(608 Rejected, no second leg)"
        )
        print(f"{'AS-2 calls seen':<{_LABEL_WIDTH}}: {as2_delta} (the absence is the assertion)")
        print(f"{'core INVITEs seen':<{_LABEL_WIDTH}}: {core_delta} (the absence is the assertion)")
        print()

        rejected_ok = (
            rejected_final.status == 608
            and rejected_final.released
            and rejected_verdict == "reject"
            and as2_delta == 0
            and core_delta == 0
        )
        results.append(rejected_ok)
        results.append(per_leg_ok)
        results.append(distinct_ok)
        results.append(icid_preserved)
    finally:
        as1.stop()
        as2.stop()
        mock.stop()
        shutil.rmtree(rules_dir, ignore_errors=True)

    print("--- verdict --------------------------------------------------------")
    print(f"allowed call completed through two B2BUAs : {'OK' if results[0] else 'FAILED'}")
    print(f"608 reject short-circuited before AS-2     : {'OK' if results[1] else 'FAILED'}")
    print(f"Call-ID regenerated on every leg           : {'OK' if results[2] else 'FAILED'}")
    print(f"three distinct Call-IDs across the chain   : {'OK' if results[3] else 'FAILED'}")
    print(f"ICID preserved across every leg            : {'OK' if results[4] else 'FAILED'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
