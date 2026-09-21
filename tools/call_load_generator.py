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

"""Interactive SIP load generator — P12 Call Load capability.

Standalone Python process that does **not** import ``as_platform``,
``src/as_app`` or ``src/anti_fraud_as`` (REQ-NF-029). Talks to AS processes
via real SIP INVITEs on their configured listen port and observes via
WebSocket event streams. See ``docs/architecture/hld.md`` section 12 and
``docs/architecture/lld.md`` section 12 for the design.

This module contains the full generator: data models, pool management,
MockSipUac skeleton, and FastAPI REST/WebSocket surface.
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Final


# ======================================================================
# Call type model
# ======================================================================


class CallModel:
    """Weighted-random selection across the 10 call types.

    Every type has equal base weight; toggling is handled by passing the
    enabled subset to :meth:`pick`. All constants are ``Final`` class attrs
    so the values used in tests are the same values used in production
    (no magic numbers duplicated).
    """

    ALL_TYPES: Final[frozenset[str]] = frozenset(
        {f"T{i}" for i in range(1, 7)} | {f"F{i}" for i in range(1, 5)}
    )

    _base_weights: Final[dict[str, float]] = {t: 1.0 for t in ALL_TYPES}

    @classmethod
    def pick(cls, enabled_types: set[str]) -> str:
        """Return one call type from the enabled set via weighted random.

        Args:
            enabled_types: Subset of :attr:`ALL_TYPES` the caller has toggled on.

        Raises:
            ValueError: When ``enabled_types`` is empty or contains unknown keys.
        """
        if not enabled_types:
            raise ValueError("enabled_call_types must not be empty")
        unknown = enabled_types - cls.ALL_TYPES
        if unknown:
            raise ValueError(f"Unknown call types: {sorted(unknown)}")
        keys = sorted(enabled_types)
        weights = [cls._base_weights[t] for t in keys]
        return random.choices(keys, weights=weights, k=1)[0]


# ======================================================================
# Duration model
# ======================================================================


class DurationModel:
    """Fixed-weight duration classes (HLD §12.4, REQ-F-041)."""

    WEIGHTS: Final[dict[str, float]] = {
        "D1": 0.30,  # Fast: ~2 s conversation
        "D2": 0.50,  # Medium: ~8–15 s conversation
        "D3": 0.15,  # Long: ~20–30 s conversation
        "D4": 0.05,  # Timeout: AS tears down on 3 s timer
    }

    #: Midpoint BYE timing for each class (seconds after 200 OK).
    MIDPOINTS: Final[dict[str, float]] = {
        "D1": 2.5,
        "D2": 11.5,
        "D3": 25.0,
        "D4": 3.0,
    }

    #: Weight-derived average duration — used for Little's Law coupling.
    #: Design constant (ADR-0013), not a runtime measurement.
    AVG_DURATION_SECONDS: Final[float] = (
        0.30 * 2.5 + 0.50 * 11.5 + 0.15 * 25.0 + 0.05 * 3.0
    )  # = 9.5

    @classmethod
    def pick(cls) -> str:
        """Return one duration class via weighted random."""
        keys = sorted(cls.WEIGHTS.keys())
        weights = [cls.WEIGHTS[k] for k in keys]
        return random.choices(keys, weights=weights, k=1)[0]


# ======================================================================
# Configuration and per-call state
# ======================================================================


@dataclass(frozen=True)
class PoolConfig:
    """Immutable pool configuration — validated once at construction."""

    target_concurrency: int
    call_rate: float
    enabled_call_types: frozenset[str]

    def __post_init__(self) -> None:
        if not (1 <= self.target_concurrency <= 50):
            raise ValueError(
                f"target_concurrency must be 1..50, got {self.target_concurrency}"
            )
        if not (0.1 <= self.call_rate <= 10.0):
            raise ValueError(f"call_rate must be 0.1..10.0, got {self.call_rate}")
        if not self.enabled_call_types:
            raise ValueError("enabled_call_types must not be empty")
        unknown = self.enabled_call_types - CallModel.ALL_TYPES
        if unknown:
            raise ValueError(f"Unknown call types: {sorted(unknown)}")


@dataclass
class CallInstance:
    """One call being driven by the generator."""

    call_id: str
    call_type: str
    duration_class: str
    state: str
    far_end_behavior: str
    started_at: float
    ended_at: float | None = None
