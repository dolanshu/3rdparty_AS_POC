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

"""Unit tests for the pure translation and routing functions."""

from __future__ import annotations

import pytest

from as_app.routing.engine import (
    Disposition,
    apply_translation,
    classify_number_format,
    decide,
    rule_matches,
    select_rule,
)
from as_app.routing.rules import NumberFormat, NumberTranslation

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("+8613800138000", NumberFormat.E164),
        ("02161234567", NumberFormat.NATIONAL),
        ("0085212345678", NumberFormat.INTERNATIONAL),
        ("110", NumberFormat.SHORT_CODE),
        ("10086", NumberFormat.SHORT_CODE),
    ],
)
def test_number_format_classification(number: str, expected: NumberFormat) -> None:
    """Each dialled form is classified as the format the rules use."""
    assert classify_number_format(number) is expected


def test_translation_strips_and_prepends() -> None:
    """A translation removes the configured prefix and prepends the new digits."""
    translation = NumberTranslation(
        to_format=NumberFormat.NATIONAL, strip_prefix="+86", prepend="0"
    )
    assert apply_translation("+8613800138000", translation) == "013800138000"


def test_translation_tolerates_a_missing_prefix() -> None:
    """A prefix that is not present leaves the number otherwise intact."""
    translation = NumberTranslation(to_format=NumberFormat.E164, strip_prefix="+86", prepend="+86")
    assert apply_translation("013800138000", translation) == "+86013800138000"


def test_mobile_e164_is_translated_to_national(rule_set) -> None:
    """A China Mobile E.164 number leaves the AS in national format."""
    decision = decide(rule_set, "+8613800138000")
    assert decision.disposition is Disposition.ROUTE
    assert decision.rule_id == "R-MOB-CM-40"
    assert decision.translated_number == "013800138000"
    assert decision.target_format is NumberFormat.NATIONAL


def test_international_prefix_is_normalised_to_e164(rule_set) -> None:
    """An 00-prefixed number is rewritten to E.164 and routed to the gateway."""
    decision = decide(rule_set, "0085212345678")
    assert decision.rule_id == "R-INTL-80"
    assert decision.translated_number == "+85212345678"
    assert [hop.name for hop in decision.next_hops] == [
        "intl-gateway-primary",
        "intl-gateway-secondary",
    ]


def test_office_extension_is_expanded_to_the_office_range(rule_set) -> None:
    """A four digit extension becomes an E.164 office number on the PBX trunk."""
    decision = decide(rule_set, "6123")
    assert decision.rule_id == "R-PBX-30"
    assert decision.translated_number == "+86216186123"
    assert [hop.name for hop in decision.next_hops][0] == "office-pbx-primary"


def test_emergency_short_code_is_not_translated(rule_set) -> None:
    """Emergency numbers keep their short code and take the primary trunk."""
    decision = decide(rule_set, "110")
    assert decision.rule_id == "R-EMG-01"
    assert decision.translated_number == "110"


def test_blocked_premium_rate_number_is_rejected_with_603(rule_set) -> None:
    """A premium-rate number is answered with 603 Decline and AS-ROUTE-002."""
    decision = decide(rule_set, "+861681234567")
    assert decision.disposition is Disposition.REJECT
    assert decision.sip_status == 603
    assert decision.error_code == "AS-ROUTE-002"


def test_number_without_matching_rule_yields_404(rule_set) -> None:
    """A number no rule accepts is answered with 404 and AS-ROUTE-001."""
    decision = decide(rule_set, "+9991234567")
    assert decision.disposition is Disposition.NO_MATCH
    assert decision.sip_status == 404
    assert decision.error_code == "AS-ROUTE-001"


def test_select_rule_prefers_lower_priority(rule_set) -> None:
    """Selection returns the highest priority rule that matches."""
    rule = select_rule(rule_set, "02161234567")
    assert rule is not None
    assert rule.rule_id == "R-FIX-NAT-70"


def test_select_rule_returns_none_for_unknown_number(rule_set) -> None:
    """Selection returns ``None`` when nothing matches."""
    assert select_rule(rule_set, "+9991234567") is None


def test_rule_matching_respects_the_format_filter(rule_set) -> None:
    """A rule that pins the number format does not match another format."""
    rule = next(rule for rule in rule_set.document.rules if rule.rule_id == "R-PBX-30")
    assert rule_matches(rule, "6123", NumberFormat.SHORT_CODE) is True
    assert rule_matches(rule, "6123", NumberFormat.NATIONAL) is False
