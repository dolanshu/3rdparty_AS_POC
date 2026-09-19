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

"""Call counters and dispositions exposed to the console.

The registry is process-local and intentionally plain: total calls, calls by disposition,
error code distribution, rule hit distribution and peer status (``AGENT.md``
section 4.3). sippy uses no asyncio, so the counters are guarded by a lock and read from
the internal API process-independently through a snapshot.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "CallDisposition",
    "MetricsRegistry",
    "MetricsSnapshot",
    "PeerStatus",
    "get_metrics_registry",
]


class CallDisposition(Enum):
    """Final outcome of a call attempt."""

    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    NO_MATCH = "no_match"
    ABANDONED = "abandoned"


class PeerStatus(Enum):
    """Observed state of a trunk peer or next hop."""

    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    DEGRADED = "degraded"


@dataclass
class MetricsSnapshot:
    """Immutable view of the counters, safe to serialise for the console."""

    calls_total: int
    calls_by_disposition: dict[str, int]
    errors_by_code: dict[str, int]
    rule_hits: dict[str, int]
    peer_status: dict[str, str]
    counters: dict[str, int]


@dataclass
class MetricsRegistry:
    """Counters for calls, errors, rule hits and peer state.

    Attributes:
        calls_total: Number of call attempts seen since process start.
        calls_by_disposition: Count per :class:`CallDisposition` value.
        errors_by_code: Count per internal ``AS-*`` error code.
        rule_hits: Count per routing rule identifier.
        peer_status: Last observed status per peer name.
        counters: Named, application-specific counters — the bucket a use case adds to
            without the registry having to know what it counts.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    calls_total: int = 0
    calls_by_disposition: Counter[str] = field(default_factory=Counter)
    errors_by_code: Counter[str] = field(default_factory=Counter)
    rule_hits: Counter[str] = field(default_factory=Counter)
    peer_status: dict[str, PeerStatus] = field(default_factory=dict)
    counters: Counter[str] = field(default_factory=Counter)

    def record_call_started(self) -> None:
        """Count one new call attempt arriving on the trunk."""
        with self._lock:
            self.calls_total += 1

    def record_call_disposition(self, disposition: CallDisposition) -> None:
        """Record the final outcome of a call.

        Args:
            disposition: Outcome of the call attempt.
        """
        with self._lock:
            self.calls_by_disposition[disposition.value] += 1

    def record_error(self, error_code: str) -> None:
        """Record an internal error code occurrence.

        Args:
            error_code: Stable code from the error model, for example ``AS-ROUTE-001``.
        """
        with self._lock:
            self.errors_by_code[error_code] += 1

    def record_rule_hit(self, rule_id: str) -> None:
        """Record that a routing rule matched a call.

        Args:
            rule_id: Identifier of the rule, for example ``R-010``.
        """
        with self._lock:
            self.rule_hits[rule_id] += 1

    def record_counter(self, name: str, *, amount: int = 1) -> None:
        """Record one occurrence of a named, application-specific counter.

        This is the one generic bucket in the registry. A second AS use case needs to count
        things the first one has no concept of (for example screening verdicts), and the
        alternative — an interface, a registry of registries or a per-use-case counter type
        — is exactly the premature abstraction P8 must not build (ADR-0007 decision 9). The
        name is a plain convention: ``verdict.reject``, ``screen.block_list``.

        Args:
            name: Counter name, dot-separated lower case by convention.
            amount: Amount to add; ``1`` for a single occurrence.
        """
        with self._lock:
            self.counters[name] += amount

    def set_peer_status(self, peer_name: str, status: PeerStatus) -> None:
        """Set the observed status of a peer or next hop.

        Args:
            peer_name: Configuration name of the peer.
            status: Observed state.
        """
        with self._lock:
            self.peer_status[peer_name] = status

    def snapshot(self) -> MetricsSnapshot:
        """Return a consistent copy of all counters.

        Returns:
            A snapshot object with plain dictionaries, ready for serialisation.
        """
        with self._lock:
            return MetricsSnapshot(
                calls_total=self.calls_total,
                calls_by_disposition=dict(self.calls_by_disposition),
                errors_by_code=dict(self.errors_by_code),
                rule_hits=dict(self.rule_hits),
                peer_status={name: status.value for name, status in self.peer_status.items()},
                counters=dict(self.counters),
            )


_REGISTRY: MetricsRegistry | None = None


def get_metrics_registry() -> MetricsRegistry:
    """Return the process-wide metrics registry, creating it on first use.

    Returns:
        The shared :class:`MetricsRegistry` instance.
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = MetricsRegistry()
    return _REGISTRY
