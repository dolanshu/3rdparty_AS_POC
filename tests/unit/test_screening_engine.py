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

"""Unit tests for the pure anti-fraud verdict (REQ-NF-011).

The engine is a function of plain values, so every case here is exercised with no socket,
no global state and no clock — the clock lives in the process-level store
(:mod:`tests.unit.test_caller_state`). What is asserted is the **decision order** the LLD
states once (section 9.3): allow list, then block list, then the call-rate window, then
reputation, with the first signal that fires naming itself in the decision.

Covers ACC-P8-003 (REQ-F-018, REQ-F-019) and ACC-P8-004 (REQ-NF-011).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from anti_fraud_as.errors import FraudErrorCode
from anti_fraud_as.screening import (
    ScreeningDecision,
    ScreeningPolicy,
    ScreeningSignals,
    ScreeningSource,
    ScreeningVerdict,
    screen,
)

pytestmark = pytest.mark.unit

#: Thresholds used by most cases: reject above three calls, below fifty points.
POLICY = ScreeningPolicy(reject_below_reputation=50.0, reject_above_calls=3)


def signals(**overrides: object) -> ScreeningSignals:
    """Build screening signals with healthy defaults.

    Args:
        **overrides: Fields to override on the defaults.

    Returns:
        Signals for a caller with an identity, no list match, a full score and one call.
    """
    base = ScreeningSignals(
        calling_number="+86216180001",
        identity_present=True,
        allowlisted_by=None,
        blocklisted_by=None,
        effective_reputation=100.0,
        calls_in_window=1,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_a_healthy_caller_is_allowed_with_no_signal_named() -> None:
    """Nothing firing is an allow, and the decision says so rather than guessing."""
    decision = screen(signals(), POLICY)

    assert decision.verdict is ScreeningVerdict.ALLOW
    assert decision.source is ScreeningSource.NONE
    assert decision.error_code is None
    assert decision.list_entry is None
    assert decision.reason == "no screening signal rejected the call"


def test_a_block_listed_caller_is_rejected_with_the_entry_identifier() -> None:
    """The block list rejects and names the entry, so the trace explains itself."""
    decision = screen(signals(blocklisted_by="BL-0001"), POLICY)

    assert decision.verdict is ScreeningVerdict.REJECT
    assert decision.source is ScreeningSource.BLOCK_LIST
    assert decision.list_entry == "BL-0001"
    assert decision.error_code == FraudErrorCode.FRAUD_CALLER_BLOCKED.code
    assert decision.reason == "calling party is on the block list"


def test_an_allow_listed_caller_is_allowed_and_named() -> None:
    """An operator exemption is an allow with its own source, not a silent pass."""
    decision = screen(signals(allowlisted_by="AL-0002"), POLICY)

    assert decision.verdict is ScreeningVerdict.ALLOW
    assert decision.source is ScreeningSource.ALLOW_LIST
    assert decision.list_entry == "AL-0002"
    assert decision.error_code is None
    assert decision.reason == "calling party is on the allow list"


def test_the_allow_list_wins_over_every_other_signal() -> None:
    """An exemption is absolute: block list, window and reputation cannot override it."""
    decision = screen(
        signals(
            allowlisted_by="AL-0001",
            blocklisted_by="BL-0001",
            calls_in_window=99,
            effective_reputation=0.0,
        ),
        POLICY,
    )

    assert decision.verdict is ScreeningVerdict.ALLOW
    assert decision.source is ScreeningSource.ALLOW_LIST


def test_the_block_list_wins_over_the_window_and_reputation() -> None:
    """A listed caller is rejected for being listed, whatever else is also true."""
    decision = screen(
        signals(blocklisted_by="BL-0001", calls_in_window=99, effective_reputation=0.0),
        POLICY,
    )

    assert decision.source is ScreeningSource.BLOCK_LIST
    assert decision.error_code == FraudErrorCode.FRAUD_CALLER_BLOCKED.code


def test_the_window_wins_over_reputation() -> None:
    """Both signals firing reports the window: the order is documented, not incidental."""
    decision = screen(signals(calls_in_window=4, effective_reputation=0.0), POLICY)

    assert decision.source is ScreeningSource.RATE_WINDOW
    assert decision.error_code == FraudErrorCode.FRAUD_RATE_EXCEEDED.code


@pytest.mark.parametrize("calls", [1, 3])
def test_calls_at_or_below_the_threshold_are_allowed(calls: int) -> None:
    """The threshold is a ceiling, not an off-by-one trigger (REQ-F-018)."""
    decision = screen(signals(calls_in_window=calls), POLICY)

    assert decision.verdict is ScreeningVerdict.ALLOW


@pytest.mark.parametrize("calls", [4, 5])
def test_calls_above_the_threshold_are_rejected(calls: int) -> None:
    """One call past ``reject_above_calls`` is the first rejection."""
    decision = screen(signals(calls_in_window=calls), POLICY)

    assert decision.verdict is ScreeningVerdict.REJECT
    assert decision.source is ScreeningSource.RATE_WINDOW
    assert decision.reason == "calling party exceeded the call-rate window"
    assert decision.error_code == FraudErrorCode.FRAUD_RATE_EXCEEDED.code


@pytest.mark.parametrize("score", [0.0, 30.0, 49.9])
def test_a_score_below_the_threshold_is_rejected(score: float) -> None:
    """Reputation rejects strictly below ``reject_below_reputation``."""
    decision = screen(signals(effective_reputation=score), POLICY)

    assert decision.verdict is ScreeningVerdict.REJECT
    assert decision.source is ScreeningSource.REPUTATION
    assert decision.reason == "calling party reputation is below the threshold"
    assert decision.error_code == FraudErrorCode.FRAUD_REPUTATION_LOW.code


@pytest.mark.parametrize("score", [50.0, 80.0, 100.0])
def test_a_score_at_or_above_the_threshold_is_allowed(score: float) -> None:
    """The reputation threshold is inclusive, so exactly 50 is still delivered."""
    decision = screen(signals(effective_reputation=score), POLICY)

    assert decision.verdict is ScreeningVerdict.ALLOW


def test_a_missing_calling_identity_fails_open() -> None:
    """No identity means no signal at all, so the call is allowed and the case recorded.

    This is the accepted gap of ADR-0007: STIR is out of scope, so rejecting on a missing
    optional header would break legitimate traffic. The decision carries ``source=none`` so
    the trace shows *why* nothing was screened.
    """
    decision = screen(signals(identity_present=False, effective_reputation=0.0), POLICY)

    assert decision.verdict is ScreeningVerdict.ALLOW
    assert decision.source is ScreeningSource.NONE
    assert decision.reason == "no calling identity available to screen"
    assert decision.error_code is None


def test_the_decision_carries_the_score_it_decided_on() -> None:
    """The score travels with the decision so the console needs no second lookup."""
    decision = screen(signals(effective_reputation=42.5), POLICY)

    assert decision.score == 42.5


def test_every_rejection_reason_is_lower_case_english() -> None:
    """Reasons are log and console text, so they are lower case English (AGENT.md 4.3)."""
    decisions = [
        screen(signals(blocklisted_by="BL-0001"), POLICY),
        screen(signals(calls_in_window=9), POLICY),
        screen(signals(effective_reputation=0.0), POLICY),
    ]

    for decision in decisions:
        assert decision.reason == decision.reason.lower()
        assert decision.reason.strip() != ""


def test_only_a_rejection_carries_an_error_code() -> None:
    """``error_code`` is how a rejection is traced; an allow never invents one."""
    allows = [
        screen(signals(), POLICY),
        screen(signals(allowlisted_by="AL-0001"), POLICY),
        screen(signals(identity_present=False), POLICY),
    ]
    rejects = [
        screen(signals(blocklisted_by="BL-0001"), POLICY),
        screen(signals(calls_in_window=9), POLICY),
        screen(signals(effective_reputation=0.0), POLICY),
    ]

    assert [decision.error_code for decision in allows] == [None, None, None]
    assert all(decision.error_code is not None for decision in rejects)


def test_the_same_inputs_always_produce_the_same_decision() -> None:
    """Purity: the engine holds no state between calls and returns plain data."""
    first = screen(signals(calls_in_window=7), POLICY)
    second = screen(signals(calls_in_window=7), POLICY)

    assert first == second
    assert isinstance(first, ScreeningDecision)


def test_the_engine_reads_no_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call to :func:`screen` must not consult the wall clock (REQ-NF-011).

    Time is injected into the process-level store, never read by the engine — so a clock
    that raises is a clock the engine never touched.
    """
    import time as time_module

    from anti_fraud_as import screening

    def boom() -> float:
        """Fail if anything reads the clock inside the engine."""
        raise AssertionError("the screening engine read a clock")

    monkeypatch.setattr(time_module, "monotonic", boom)
    monkeypatch.setattr(time_module, "time", boom)

    decision = screening.screen(signals(), POLICY)

    assert decision.verdict is ScreeningVerdict.ALLOW
