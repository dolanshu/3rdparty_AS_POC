#!/usr/bin/env python3
# Copyright 2026 the 3rd-party AS POC authors.
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

"""Print the active routing rule set, or evaluate numbers against it.

This is the tool behind ``make rules``: it shows that the rule set is data, that it is
validated on load, and what the AS would do with a number. ``make demo`` no longer uses it
— the demo places a real call through ``tools/demo_call.py``.

Usage:
    python tools/show_rules.py --rules-file config/routing_rules.yaml
    python tools/show_rules.py --evaluate +8613800138000 --evaluate 110
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The packages live under src/; allow running the tool without an install.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from as_app.errors import AsError  # noqa: E402
from as_app.routing.engine import Disposition, decide  # noqa: E402
from as_app.routing.rules import load_rule_set  # noqa: E402

SAMPLE_NUMBERS = (
    "110",
    "10086",
    "6123",
    "+8613800138000",
    "02161234567",
    "0085212345678",
    "+861681234567",
)


def _print_next_hops(rule_set: object) -> None:
    """Print the next hop catalogue.

    Args:
        rule_set: The loaded rule set.
    """
    print("next hops")
    for hop in rule_set.document.next_hops:  # type: ignore[attr-defined]
        target = f"{hop.transport}://{hop.address}:{hop.port}"
        print(f"  {hop.priority:>2}  {hop.name:<22} {target:<32} {hop.description}")
    print()


def _print_rules(rule_set: object) -> None:
    """Print the rules in evaluation order.

    Args:
        rule_set: The loaded rule set.
    """
    print("rules (evaluation order)")
    for rule in rule_set.ordered_rules:  # type: ignore[attr-defined]
        condition = ", ".join(rule.match.called_numbers or rule.match.called_prefixes) or "*"
        action = (
            f"route -> {'|'.join(rule.action.next_hops)}"
            if rule.action.kind == "route"
            else f"reject {rule.action.status}"
        )
        print(f"  {rule.priority:>3}  {rule.rule_id:<16} {condition[:44]:<44} {action}")
    print()


def _print_evaluation(rule_set: object, numbers: tuple[str, ...]) -> None:
    """Evaluate numbers and print the decision for each.

    Args:
        rule_set: The loaded rule set.
        numbers: Numbers to evaluate.
    """
    print("decisions")
    for number in numbers:
        decision = decide(rule_set, number)  # type: ignore[arg-type]
        if decision.disposition is Disposition.ROUTE:
            hops = " -> ".join(hop.name for hop in decision.next_hops)
            print(
                f"  {number:<18} route    {decision.rule_id:<16} "
                f"{decision.called_number} -> {decision.translated_number}   {hops}"
            )
        else:
            print(
                f"  {number:<18} {decision.disposition.value:<8} {decision.rule_id or '-':<16} "
                f"{decision.sip_status} {decision.error_code}  {decision.reason}"
            )
    print()


def main(argv: list[str] | None = None) -> int:
    """Run the rule viewer.

    Args:
        argv: Command line arguments; ``sys.argv`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, ``1`` when the rule set is invalid.
    """
    parser = argparse.ArgumentParser(description="Show the active routing rule set")
    parser.add_argument(
        "--rules-file", type=Path, default=REPO_ROOT / "config" / "routing_rules.yaml"
    )
    parser.add_argument(
        "--evaluate", action="append", default=[], help="evaluate a number; repeatable"
    )
    args = parser.parse_args(argv)

    try:
        rule_set = load_rule_set(args.rules_file)
    except AsError as error:
        print(f"{error.code.code}: {error.detail}", file=sys.stderr)
        return 1

    print(f"rule set: {rule_set.document.name} ({rule_set.source})")
    print(f"          {rule_set.document.description.strip()}")
    print()
    _print_next_hops(rule_set)
    _print_rules(rule_set)
    _print_evaluation(rule_set, tuple(args.evaluate) or SAMPLE_NUMBERS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
