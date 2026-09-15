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

"""Pure number translation and routing decisions.

Everything in this module is side-effect free: no sockets, no global state, no clock.
That is what makes the whole routing policy testable without a network and what keeps the
sippy callbacks in ``as_app.call_controller`` thin glue (``AGENT.md`` section 5 and 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from as_app.errors import AsError, AsErrorCode
from as_app.routing.rules import (
    NextHop,
    NumberFormat,
    NumberTranslation,
    RejectAction,
    RouteAction,
    RoutingRule,
    RuleSet,
)

__all__ = [
    "Disposition",
    "RoutingDecision",
    "apply_translation",
    "classify_number_format",
    "decide",
    "rule_matches",
    "select_rule",
]


class Disposition(Enum):
    """Outcome of a routing decision."""

    ROUTE = "route"
    REJECT = "reject"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class RoutingDecision:
    """Result of evaluating the rule set against one called number.

    Attributes:
        disposition: What the AS should do with the call.
        called_number: The number as it arrived on the trunk.
        translated_number: The number after translation, for the outbound Request-URI.
        rule_id: Identifier of the rule that decided, ``None`` when nothing matched.
        source_format: Format of the incoming number.
        target_format: Format of the translated number, when a translation was applied.
        next_hops: Next hops in selection order; empty for rejections.
        sip_status: Status code to report when the call is not routed.
        error_code: Internal error code, ``None`` when the call is routed.
        reason: Human readable reason shown in logs and in the console.
    """

    disposition: Disposition
    called_number: str
    translated_number: str | None = None
    rule_id: str | None = None
    source_format: NumberFormat | None = None
    target_format: NumberFormat | None = None
    next_hops: list[NextHop] = field(default_factory=list)
    sip_status: int | None = None
    error_code: str | None = None
    reason: str = ""


def classify_number_format(number: str) -> NumberFormat:
    """Classify the format of a dialled number.

    Args:
        number: The called number as received, digits only, optionally with a leading
            ``+``.

    Returns:
        The detected :class:`NumberFormat`.
    """
    if number.startswith("+"):
        return NumberFormat.E164
    if number.startswith("00"):
        return NumberFormat.INTERNATIONAL
    if number.startswith("0") and len(number) > 1:
        return NumberFormat.NATIONAL
    return NumberFormat.SHORT_CODE


def apply_translation(number: str, translation: NumberTranslation) -> str:
    """Rewrite a number according to a translation.

    Prefix stripping is best effort: a prefix that is not present is simply not removed,
    so a partially wrong configuration still produces a routable number rather than a
    hard failure.

    Args:
        number: The number to rewrite.
        translation: The translation to apply.

    Returns:
        The rewritten number.

    Raises:
        AsError: ``AS-ROUTE-004`` when the translation produces an empty number.
    """
    result = number
    if translation.strip_prefix and result.startswith(translation.strip_prefix):
        result = result[len(translation.strip_prefix) :]
    if translation.prepend:
        result = f"{translation.prepend}{result}"
    if not result:
        raise AsError(
            AsErrorCode.ROUTE_TRANSLATION_FAILED,
            f"translation produced an empty number for {number}",
            context={"called_number": number},
        )
    return result


def rule_matches(rule: RoutingRule, number: str, number_format: NumberFormat) -> bool:
    """Check whether a rule matches a called number.

    Args:
        rule: The rule to evaluate.
        number: The called number.
        number_format: Pre-classified format of the number.

    Returns:
        ``True`` when every condition of the rule holds.
    """
    if not rule.enabled:
        return False
    criteria = rule.match
    if criteria.number_format is not None and criteria.number_format != number_format:
        return False
    if criteria.called_numbers:
        return number in criteria.called_numbers
    if criteria.called_prefixes:
        return number.startswith(tuple(criteria.called_prefixes))
    return criteria.number_format == number_format


def select_rule(rule_set: RuleSet, number: str) -> RoutingRule | None:
    """Select the first matching rule in evaluation order.

    Args:
        rule_set: The active rule set.
        number: The called number.

    Returns:
        The matching rule, or ``None`` when no rule matches.
    """
    number_format = classify_number_format(number)
    for rule in rule_set.ordered_rules:
        if rule_matches(rule, number, number_format):
            return rule
    return None


def decide(rule_set: RuleSet, number: str) -> RoutingDecision:
    """Apply the rule set to one called number.

    Args:
        rule_set: The active rule set.
        number: The called number as received on the trunk.

    Returns:
        The routing decision. A number with no matching rule yields
        :attr:`Disposition.NO_MATCH` carrying SIP ``404`` and ``AS-ROUTE-001``; a
        matching reject rule yields :attr:`Disposition.REJECT` with the rule's status.
    """
    number_format = classify_number_format(number)
    rule = select_rule(rule_set, number)
    if rule is None:
        return RoutingDecision(
            disposition=Disposition.NO_MATCH,
            called_number=number,
            source_format=number_format,
            sip_status=AsErrorCode.ROUTE_NO_MATCH.sip_status,
            error_code=AsErrorCode.ROUTE_NO_MATCH.code,
            reason=AsErrorCode.ROUTE_NO_MATCH.message,
        )
    if isinstance(rule.action, RejectAction):
        return RoutingDecision(
            disposition=Disposition.REJECT,
            called_number=number,
            rule_id=rule.rule_id,
            source_format=number_format,
            sip_status=rule.action.status,
            error_code=rule.action.error_code,
            reason=rule.action.reason,
        )
    assert isinstance(rule.action, RouteAction)  # discriminated union, see rules.RuleAction
    translated = apply_translation(number, rule.action.translate)
    return RoutingDecision(
        disposition=Disposition.ROUTE,
        called_number=number,
        translated_number=translated,
        rule_id=rule.rule_id,
        source_format=number_format,
        target_format=rule.action.translate.to_format,
        next_hops=rule_set.next_hops_for(rule),
        reason=rule.description,
    )
