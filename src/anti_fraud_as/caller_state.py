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

"""Process-level cross-call state of the anti-fraud AS (ADR-0007 decision 8).

Two structures live here and nowhere else: the per-caller call-rate window and the
reputation ledger. They belong to the **process**, never to a per-call controller — a window
held on a controller would be created per call, always contain exactly one entry, and fail
silently while single-call unit tests still passed. The controller sees this store only
through already-computed plain values (:class:`CallerSignals`).

The store is the **only** place in this package that reads a clock, and the clock is
injected, so the verdict itself stays a pure function (REQ-NF-011). One lock guards both
structures, because sippy callbacks and the console feed run on different threads — the same
reason the metrics registry and the trace recorder are lock-guarded.

In-memory only: a restart loses the window and the reputation history. That is a registered
POC gap, closed in P11 by the pluggable state store (``docs/phase2-plan.md`` D9).
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "CallRateWindow",
    "CallerSignals",
    "CallerStateStore",
    "ReputationLedger",
    "WindowPolicy",
]


@dataclass(frozen=True)
class WindowPolicy:
    """Parameters of the cross-call state, resolved from the screening data file.

    Attributes:
        window_seconds: Length of the call-rate window.
        max_calls: A caller is rejected above this many calls inside the window.
        half_life_seconds: Half-life of the reputation decay.
        default_score: Score a caller starts at and decays back towards.
        reject_penalty: Score removed from a caller whose call was rejected.
        max_tracked_callers: Upper bound on the callers kept in memory.
    """

    window_seconds: float
    max_calls: int
    half_life_seconds: float
    default_score: float
    reject_penalty: float
    max_tracked_callers: int


@dataclass(frozen=True)
class CallerSignals:
    """The cross-call part of the screening input, as plain values.

    Attributes:
        calling_number: Calling party the signals belong to.
        effective_reputation: Reputation score after decay, at the observation instant.
        calls_in_window: Calls of this caller inside the window, this one included.
    """

    calling_number: str
    effective_reputation: float
    calls_in_window: int


class CallRateWindow:
    """Sliding window of call timestamps, one bounded deque per caller.

    The window is evaluated when a call arrives — the only moment its answer is needed — so
    nothing is scheduled and no timer is armed. Each caller's deque is bounded to
    ``max_calls + 1`` entries: once the threshold is passed, more detail is never needed.
    The number of tracked callers is bounded too, oldest caller first.
    """

    def __init__(self) -> None:
        """Create an empty window."""
        self._events: OrderedDict[str, deque[float]] = OrderedDict()

    def record(
        self,
        caller: str,
        at: float,
        *,
        window_seconds: float,
        max_calls: int,
        max_tracked_callers: int,
    ) -> int:
        """Record one call and return how many of the caller's calls fall in the window.

        Args:
            caller: Calling party the call belongs to.
            at: Monotonic instant the call was observed at.
            window_seconds: Length of the window to evaluate.
            max_calls: Threshold; each deque is bounded to ``max_calls + 1`` entries.
            max_tracked_callers: Upper bound on the number of callers kept in memory.

        Returns:
            Number of calls of this caller inside the window, this one included.
        """
        events = self._events.get(caller)
        if events is None:
            events = deque()
            self._events[caller] = events
        self._events.move_to_end(caller)
        events.append(at)
        oldest_allowed = at - window_seconds
        while events and events[0] <= oldest_allowed:
            events.popleft()
        while len(events) > max_calls + 1:
            events.popleft()
        while len(self._events) > max(1, max_tracked_callers):
            self._events.popitem(last=False)
        return len(events)


class ReputationLedger:
    """Per-caller reputation that decays exponentially towards the default score.

    Only ``(score, updated_at)`` is stored per caller; the decay and penalty parameters are
    read from the active policy on every access, so a reload can change them without
    discarding the history. A score decays towards ``default_score`` with the configured
    half-life, so a burst of suspicious calls fades instead of persisting forever.
    """

    def __init__(self) -> None:
        """Create an empty ledger."""
        self._entries: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def effective_score(
        self, caller: str, now: float, *, default_score: float, half_life_seconds: float
    ) -> float:
        """Return the caller's score at ``now``, decayed towards the default.

        Args:
            caller: Calling party the score belongs to.
            now: Monotonic instant to evaluate the score at.
            default_score: Score a caller starts at and decays back towards.
            half_life_seconds: Time in which a deviation from the default halves.

        Returns:
            The decayed score; the default score for an unknown caller.
        """
        entry = self._entries.get(caller)
        if entry is None:
            return default_score
        score, updated_at = entry
        self._entries.move_to_end(caller)
        return _decay(
            score,
            updated_at,
            now,
            default_score=default_score,
            half_life_seconds=half_life_seconds,
        )

    def penalise(
        self,
        caller: str,
        now: float,
        *,
        default_score: float,
        half_life_seconds: float,
        reject_penalty: float,
        max_tracked_callers: int,
    ) -> float:
        """Lower the caller's score by the configured penalty.

        Args:
            caller: Calling party the score belongs to.
            now: Monotonic instant of the call that caused the penalty.
            default_score: Score a caller starts at and decays back towards.
            half_life_seconds: Time in which a deviation from the default halves.
            reject_penalty: Score removed by one rejected call.
            max_tracked_callers: Upper bound on the number of callers kept in memory.

        Returns:
            The new stored score, before it decays further.
        """
        score = self.effective_score(
            caller, now, default_score=default_score, half_life_seconds=half_life_seconds
        )
        score -= reject_penalty
        self._entries[caller] = (score, now)
        self._entries.move_to_end(caller)
        while len(self._entries) > max(1, max_tracked_callers):
            self._entries.popitem(last=False)
        return score


def _decay(
    score: float,
    updated_at: float,
    now: float,
    *,
    default_score: float,
    half_life_seconds: float,
) -> float:
    """Decay a score towards a baseline with an exponential half-life.

    Args:
        score: Score as it was stored.
        updated_at: Monotonic instant the score was stored at.
        now: Monotonic instant to evaluate at.
        default_score: Baseline the score decays towards.
        half_life_seconds: Time in which the deviation from the baseline halves.

    Returns:
        The decayed score, equal to ``score`` when no time has passed.
    """
    elapsed = max(0.0, now - updated_at)
    # math.pow rather than ``0.5 ** x``: the operator form is typed as Any by mypy.
    factor = math.pow(0.5, elapsed / half_life_seconds)
    return default_score + (score - default_score) * factor


class CallerStateStore:
    """Process-level store of the anti-fraud cross-call state (ADR-0007 decision 8).

    One instance per process, created by the stack and shared by every call. The clock is
    injected so the window and the decay are testable without waiting, and so the engine
    itself never reads one (REQ-NF-011).

    Attributes:
        policy: The window and reputation parameters currently in force.
    """

    def __init__(
        self, policy: WindowPolicy, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        """Create the store for one process.

        Args:
            policy: Window and reputation parameters, from the screening data file.
            clock: Monotonic clock; injected so tests can advance time deterministically.
        """
        self._clock = clock
        self._lock = threading.Lock()
        self.policy = policy
        self._window = CallRateWindow()
        self._reputation = ReputationLedger()

    def reconfigure(self, policy: WindowPolicy) -> None:
        """Adopt new parameters after a screening-data reload.

        The recorded observations are kept: the window and the reputation history describe
        the callers, while the policy describes the thresholds. A caller's recorded calls
        are re-evaluated against the new window length on their next observation.

        Args:
            policy: The parameters that are now in force.
        """
        with self._lock:
            self.policy = policy

    def observe(self, calling_number: str) -> CallerSignals:
        """Record one call and return this caller's cross-call signals.

        Args:
            calling_number: Calling party of the call, or ``"-"`` when it is unknown.

        Returns:
            The caller's decayed reputation and their call count inside the window, this
            call included.
        """
        now = self._clock()
        with self._lock:
            policy = self.policy
            calls_in_window = self._window.record(
                calling_number,
                now,
                window_seconds=policy.window_seconds,
                max_calls=policy.max_calls,
                max_tracked_callers=policy.max_tracked_callers,
            )
            score = self._reputation.effective_score(
                calling_number,
                now,
                default_score=policy.default_score,
                half_life_seconds=policy.half_life_seconds,
            )
        return CallerSignals(
            calling_number=calling_number,
            effective_reputation=score,
            calls_in_window=calls_in_window,
        )

    def penalise(self, calling_number: str) -> float:
        """Lower a caller's reputation after a rejected call.

        Args:
            calling_number: Calling party of the rejected call.

        Returns:
            The caller's new stored score, before further decay.
        """
        now = self._clock()
        with self._lock:
            policy = self.policy
            return self._reputation.penalise(
                calling_number,
                now,
                default_score=policy.default_score,
                half_life_seconds=policy.half_life_seconds,
                reject_penalty=policy.reject_penalty,
                max_tracked_callers=policy.max_tracked_callers,
            )
