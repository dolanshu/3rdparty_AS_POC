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

"""Probe the iFC-orchestrated chained AS topology (ADR-0014).

Design instrument — not collected by pytest. Exits non-zero on mismatch.

Usage:
    uv run python tools/chained_as_probe.py
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

from as_app.observability.logging import configure_logging  # noqa: E402
from as_app.sip_adapter import outbound_call_id  # noqa: E402
from chained_helpers import (  # noqa: E402
    _LABEL_WIDTH,
    build_chained_stack,
    draw_loop_until,
    received_invite_icid,
    verdict_attributes,
)
from s_sbc_mock.uac import CallScenario  # noqa: E402

ALLOWED_CALLER = "+86216180001"
BLOCKED_CALLER = "+8613400000001"
CALLED_NUMBER = "+8613800138000"


def main(argv: list[str] | None = None) -> int:
    """Run the chained-topology probe."""
    parser = argparse.ArgumentParser(description="Probe the chained AS topology")
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
    rules_dir = Path(tempfile.mkdtemp(prefix="as-poc-chain-"))
    stack = build_chained_stack(
        screening_file=args.screening_file,
        rules_file=args.rules_file,
        rules_dir=rules_dir,
    )

    print("chained AS probe - iFC-orchestrated chain (ADR-0014)")
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
            return 1
        draw_loop_until(
            lambda cid=uac_call_id, first=outcome: bool(
                (stack.outcome_for(cid) or first).released
            )
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
        hop_ids = [uac_call_id, str(as1_out.call_id), as2_trunk, str(as2_out.call_id)]
        per_leg_ok = (
            str(as1_out.call_id) == outbound_call_id(uac_call_id)
            and str(as2_out.call_id) == outbound_call_id(as2_trunk)
        )
        distinct_ok = len(set(hop_ids)) == 4
        icids = [
            received_invite_icid(stack.as1_messages),
            received_invite_icid(stack.as2_messages),
        ]
        icid_preserved = icids[0] is not None and icids[0] == icids[1]

        print(f"{'distinct Call-IDs':<{_LABEL_WIDTH}}: {len(set(hop_ids))}")
        print(f"{'Call-ID per leg':<{_LABEL_WIDTH}}: {per_leg_ok}")
        print(f"{'ICID preserved':<{_LABEL_WIDTH}}: {icid_preserved}")
        print(f"{'final status':<{_LABEL_WIDTH}}: {final.status}")
        print()

        term_invites = stack.terminating.received_invites[term_before:]
        allowed_ok = (
            final.released
            and final.status == 200
            and len(term_invites) == 1
            and term_invites[0].called_number == "013800138000"
        )
        results.extend([allowed_ok, per_leg_ok, distinct_ok, icid_preserved])

        as2_before = len(stack.as2.tracer.known_call_ids())
        term_before = len(stack.terminating.received_invites)
        blocked = CallScenario(
            name="chained-reject", calling_number=args.blocked_caller, called_number=CALLED_NUMBER
        )
        rejected_id = stack.place_call(blocked)
        rejected_outcome = stack.outcome_for(rejected_id)
        if rejected_outcome is None:
            return 1
        draw_loop_until(
            lambda cid=rejected_id, first=rejected_outcome: bool(
                (stack.outcome_for(cid) or first).released
            )
        )
        rejected_final = stack.outcome_for(rejected_id) or rejected_outcome
        rejected_ok = (
            rejected_final.status == 608
            and len(stack.as2.tracer.known_call_ids()) - as2_before == 0
            and len(stack.terminating.received_invites) - term_before == 0
        )
        results.append(rejected_ok)
    finally:
        stack.stop()
        shutil.rmtree(rules_dir, ignore_errors=True)

    print("--- verdict --------------------------------------------------------")
    print(f"allowed call completed through two B2BUAs : {'OK' if results[0] else 'FAILED'}")
    print(f"Call-ID regenerated on every leg           : {'OK' if results[1] else 'FAILED'}")
    print(f"four distinct AS-leg Call-IDs              : {'OK' if results[2] else 'FAILED'}")
    print(f"ICID preserved across every leg            : {'OK' if results[3] else 'FAILED'}")
    print(f"608 reject short-circuited before AS-2     : {'OK' if results[4] else 'FAILED'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
