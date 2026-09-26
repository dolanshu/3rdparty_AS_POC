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

"""Run the iFC-orchestrated chained AS topology and narrate what every hop saw.

Topology (ADR-0014): ``S-SBC -> AS-1 -> S-CSCF -> S-SBC -> AS-2 -> P-CSCF -> UAS``.
AS instances never communicate directly; iFC #2 fires when AS-1's outbound INVITE is
透传 to the orchestrator.

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

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for path in (str(REPO_ROOT / "src"), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from chained_helpers import (  # noqa: E402
    _LABEL_WIDTH,
    build_chained_stack,
    decision_rule,
    draw_loop_until,
    received_invite_icid,
    verdict_attributes,
)

from as_app.observability.logging import configure_logging  # noqa: E402
from as_app.sip_adapter import outbound_call_id  # noqa: E402
from s_sbc_mock.uac import CallScenario  # noqa: E402

ALLOWED_CALLER = "+86216180001"
BLOCKED_CALLER = "+8613400000001"
CALLED_NUMBER = "+8613800138000"


def main(argv: list[str] | None = None) -> int:
    """Run the chained-topology demo and print the transcript."""
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

    configure_logging("ERROR", structured=False)
    rules_dir = Path(tempfile.mkdtemp(prefix="as-poc-chain-demo-"))
    stack = build_chained_stack(
        screening_file=args.screening_file,
        rules_file=args.rules_file,
        rules_dir=rules_dir,
    )

    print("chained AS POC - iFC-orchestrated chain (ADR-0014)")
    print(
        "topology   : S-SBC -> AS-1 anti-fraud -> S-CSCF/iFC -> S-SBC -> "
        "AS-2 translation -> P-CSCF -> terminating UAS"
    )
    print(
        f"ports      : AS-1 {stack.as1_port}, AS-2 {stack.as2_port}, "
        f"return {stack.return_port}, forward {stack.forward_port}, "
        f"terminating {stack.terminating_port}"
    )
    print("wiring     : chain order in ims_mock orchestrator; peer knobs -> S-SBC return only")
    print()

    results: list[bool] = []
    try:
        scenario = CallScenario(
            name="chained-allow", calling_number=args.allowed_caller, called_number=CALLED_NUMBER
        )
        term_before = len(stack.terminating.received_invites)
        uac_call_id = stack.place_call(scenario)
        outcome = stack.outcome_for(uac_call_id)
        if outcome is None:
            print("demo failed: the allowed call produced no outcome", file=sys.stderr)
            return 1

        draw_loop_until(
            lambda cid=uac_call_id, first=outcome: bool((stack.outcome_for(cid) or first).released)
        )
        final = stack.outcome_for(uac_call_id) or outcome

        as2_trunk = stack.as2.tracer.known_call_ids()[0]
        as1_out = [
            m
            for m in stack.as1_messages.messages
            if m.direction == "out" and m.text.startswith("INVITE ")
        ][0]
        as2_out = [
            m
            for m in stack.as2_messages.messages
            if m.direction == "out" and m.text.startswith("INVITE ")
        ][0]
        term_invites = stack.terminating.received_invites[term_before:]
        term_invite = term_invites[-1] if term_invites else None

        verdict = verdict_attributes(stack.as1, uac_call_id)
        print("[1/2] allowed call relayed through both AS instances")
        print(f"{'caller':<{_LABEL_WIDTH}}: {scenario.calling_number}")
        print(f"{'AS-1 verdict':<{_LABEL_WIDTH}}: {verdict.get('verdict', 'unknown')}")
        print(f"{'AS-2 rule':<{_LABEL_WIDTH}}: {decision_rule(stack.as2, as2_trunk)}")
        print(
            f"{'terminating called':<{_LABEL_WIDTH}}: "
            f"{term_invite.called_number if term_invite else '-'}"
        )
        print(f"{'final status':<{_LABEL_WIDTH}}: {final.status}")
        print()
        print("  four AS-leg Call-IDs (ADR-0014):")
        hop_ids = [
            uac_call_id,
            str(as1_out.call_id),
            as2_trunk,
            str(as2_out.call_id),
        ]
        for label, value in zip(
            ("AS-1 trunk", "AS-1 outbound", "AS-2 trunk", "AS-2 outbound"),
            hop_ids,
            strict=True,
        ):
            print(f"{label:<{_LABEL_WIDTH}}: {value}")
        per_leg_ok = str(as1_out.call_id) == outbound_call_id(uac_call_id) and str(
            as2_out.call_id
        ) == outbound_call_id(as2_trunk)
        distinct_ok = len(set(hop_ids)) == 4
        print(f"{'distinct Call-IDs':<{_LABEL_WIDTH}}: {len(set(hop_ids))}")
        print(f"{'Call-ID per leg':<{_LABEL_WIDTH}}: {per_leg_ok}")
        icids = [
            received_invite_icid(stack.as1_messages),
            received_invite_icid(stack.as2_messages),
        ]
        icid_preserved = icids[0] is not None and icids[0] == icids[1]
        print(f"{'ICID preserved':<{_LABEL_WIDTH}}: {icid_preserved}")
        print()

        allowed_ok = (
            final.released
            and final.status == 200
            and term_invite is not None
            and term_invite.called_number == "013800138000"
            and verdict.get("verdict") == "allow"
        )
        results.extend([allowed_ok, per_leg_ok, distinct_ok, icid_preserved])

        as2_before = len(stack.as2.tracer.known_call_ids())
        term_before = len(stack.terminating.received_invites)
        blocked = CallScenario(
            name="chained-reject", calling_number=args.blocked_caller, called_number=CALLED_NUMBER
        )
        rejected_call_id = stack.place_call(blocked)
        rejected_outcome = stack.outcome_for(rejected_call_id)
        if rejected_outcome is None:
            print("demo failed: the rejected call produced no outcome", file=sys.stderr)
            return 1
        draw_loop_until(
            lambda cid=rejected_call_id, first=rejected_outcome: bool(
                (stack.outcome_for(cid) or first).released
            )
        )
        rejected_final = stack.outcome_for(rejected_call_id) or rejected_outcome
        as2_delta = len(stack.as2.tracer.known_call_ids()) - as2_before
        term_delta = len(stack.terminating.received_invites) - term_before
        rejected_verdict = verdict_attributes(stack.as1, rejected_call_id).get("verdict", "unknown")

        print("[2/2] rejected call short-circuits at AS-1")
        print(f"{'AS-1 verdict':<{_LABEL_WIDTH}}: {rejected_verdict}")
        print(f"{'final status':<{_LABEL_WIDTH}}: {rejected_final.status}")
        print(f"{'AS-2 calls seen':<{_LABEL_WIDTH}}: {as2_delta}")
        print(f"{'terminating INVITEs':<{_LABEL_WIDTH}}: {term_delta}")
        print()

        rejected_ok = (
            rejected_final.status == 608
            and rejected_final.released
            and rejected_verdict == "reject"
            and as2_delta == 0
            and term_delta == 0
        )
        results.append(rejected_ok)
    finally:
        stack.stop()
        shutil.rmtree(rules_dir, ignore_errors=True)

    print("--- verdict --------------------------------------------------------")
    labels = [
        "allowed call completed through two B2BUAs",
        "Call-ID regenerated on every leg",
        "four distinct AS-leg Call-IDs",
        "ICID preserved across every leg",
        "608 reject short-circuited before AS-2",
    ]
    for label, ok in zip(labels, results, strict=True):
        print(f"{label:<45}: {'OK' if ok else 'FAILED'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
