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

"""The anti-fraud verdict — a pure function.

Screening decides, for one INVITE, whether the **calling** party is relayed or rejected. It
is deliberately a pure function of plain values: no sockets, no global state and no clock
access, so it is unit-testable without a network and without waiting (REQ-NF-011), matching
the ``as_app.routing.engine`` precedent (REQ-NF-004). Time enters through the process-level
store, which is given an injected clock (ADR-0007 decision 8).

**Decision order is fixed and stated once: allow list, block list, call-rate window,
reputation.** The first signal that fires decides, and the decision names it, so the trace
and the console can explain *why* without re-running the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from anti_fraud_as.errors import FraudErrorCode

__all__ = [
    "ScreeningDecision",
    "ScreeningPolicy",
    "ScreeningSignals",
    "ScreeningSource",
    "ScreeningVerdict",
    "screen",
]


class ScreeningVerdict(str, Enum):
    """Outcome of screening one call."""

    ALLOW = "allow"
    REJECT = "reject"


class ScreeningSource(str, Enum):
    """The signal that decided a call, for the trace, the counters and the console."""

    ALLOW_LIST = "allow_list"
    BLOCK_LIST = "block_list"
    RATE_WINDOW = "rate_window"
    REPUTATION = "reputation"
    NONE = "none"


@dataclass(frozen=True)
class ScreeningSignals:
    """Everything the verdict is computed from, as plain values.

    Attributes:
        calling_number: Calling party as received on the trunk.
        identity_present: Whether a calling identity was available at all.
        allowlisted_by: Identifier of the matched allow-list entry, when one matched.
        blocklisted_by: Identifier of the matched block-list entry, when one matched.
        effective_reputation: Decayed reputation score of the caller.
        calls_in_window: Calls of this caller inside the window, this one included.
    """

    calling_number: str
    identity_present: bool
    allowlisted_by: str | None = None
    blocklisted_by: str | None = None
    effective_reputation: float = 0.0
    calls_in_window: int = 0


@dataclass(frozen=True)
class ScreeningPolicy:
    """Thresholds the verdict compares the signals against.

    Attributes:
        reject_below_reputation: Reject when the effective score is below this value.
        reject_above_calls: Reject when the caller exceeds this many calls in the window.
    """

    reject_below_reputation: float
    reject_above_calls: int


@dataclass(frozen=True)
class ScreeningDecision:
    """The verdict and why it was reached.

    Attributes:
        verdict: Allow or reject.
        reason: Lower case English explanation, logged and shown in the console.
        source: The signal that decided.
        score: Effective reputation at the decision instant.
        list_entry: Identifier of the matched list entry, when one matched.
        error_code: ``AS-FRAUD-*`` code for a rejection, ``None`` on allow.
    """

    verdict: ScreeningVerdict
    reason: str
    source: ScreeningSource
    score: float
    list_entry: str | None = None
    error_code: str | None = None


def screen(signals: ScreeningSignals, policy: ScreeningPolicy) -> ScreeningDecision:
    """Decide whether a call is allowed or rejected.

    Pure: the same signals and policy always yield the same decision, with no clock, no
    socket and no global state involved (REQ-NF-011). See the module docstring for the
    signal order.

    Args:
        signals: Plain-value screening inputs, already computed by the caller.
        policy: Thresholds to compare them against.

    Returns:
        The verdict, the signal that decided, and on a rejection the ``AS-FRAUD-*`` code.
    """
    if not signals.identity_present:
        # Fail open: no attestation mechanism is in scope (STIR is out of scope, ADR-0007
        # decision 7) and rejecting on a missing optional header would break legitimate
        # traffic. The case is a registered gap and is recorded, not hidden.
        return ScreeningDecision(
            verdict=ScreeningVerdict.ALLOW,
            reason="no calling identity available to screen",
            source=ScreeningSource.NONE,
            score=signals.effective_reputation,
        )
    if signals.allowlisted_by is not None:
        # An operator exemption always wins, including over the window and the reputation.
        return ScreeningDecision(
            verdict=ScreeningVerdict.ALLOW,
            reason="calling party is on the allow list",
            source=ScreeningSource.ALLOW_LIST,
            score=signals.effective_reputation,
            list_entry=signals.allowlisted_by,
        )
    if signals.blocklisted_by is not None:
        return ScreeningDecision(
            verdict=ScreeningVerdict.REJECT,
            reason="calling party is on the block list",
            source=ScreeningSource.BLOCK_LIST,
            score=signals.effective_reputation,
            list_entry=signals.blocklisted_by,
            error_code=FraudErrorCode.FRAUD_CALLER_BLOCKED.code,
        )
    if signals.calls_in_window > policy.reject_above_calls:
        return ScreeningDecision(
            verdict=ScreeningVerdict.REJECT,
            reason="calling party exceeded the call-rate window",
            source=ScreeningSource.RATE_WINDOW,
            score=signals.effective_reputation,
            error_code=FraudErrorCode.FRAUD_RATE_EXCEEDED.code,
        )
    if signals.effective_reputation < policy.reject_below_reputation:
        return ScreeningDecision(
            verdict=ScreeningVerdict.REJECT,
            reason="calling party reputation is below the threshold",
            source=ScreeningSource.REPUTATION,
            score=signals.effective_reputation,
            error_code=FraudErrorCode.FRAUD_REPUTATION_LOW.code,
        )
    return ScreeningDecision(
        verdict=ScreeningVerdict.ALLOW,
        reason="no screening signal rejected the call",
        source=ScreeningSource.NONE,
        score=signals.effective_reputation,
    )
