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

"""Per-Call-ID trace and console event feed.

Every event of both call legs is recorded under the SIP Call-ID, which is the
correlation key for logs, console and acceptance evidence (``AGENT.md`` section 4.3 and
4.8). The recorder is fed by the sippy glue and drained by the internal API.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = ["CallTrace", "TraceEvent", "TraceRecorder", "get_trace_recorder"]

#: Number of most recent calls kept in memory. The trace is a demo artefact, not a
#: persistence layer (see ``docs/production-gaps.md``).
DEFAULT_MAX_TRACED_CALLS = 200


@dataclass(frozen=True)
class TraceEvent:
    """One observable event on one call leg.

    Attributes:
        timestamp: UTC time when the event was recorded.
        call_id: SIP Call-ID of the call.
        direction: ``in`` for the trunk leg, ``out`` for the next-hop leg, ``internal``
            for decisions taken inside the AS.
        method: SIP method or status code, for example ``INVITE`` or ``200``.
        peer: Remote address of the message, when applicable.
        summary: Short human readable description of the event.
        rule_id: Routing rule that decided this call, when it is known.
        attributes: Additional structured details (headers, translated number).
    """

    timestamp: datetime
    call_id: str
    direction: str
    method: str
    summary: str
    peer: str = "-"
    rule_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallTrace:
    """Ordered list of events belonging to one Call-ID."""

    call_id: str
    events: list[TraceEvent] = field(default_factory=list)


class TraceRecorder:
    """Thread-safe, bounded store of call traces.

    Attributes:
        max_calls: How many calls are retained before the oldest is discarded.
    """

    def __init__(self, max_calls: int = DEFAULT_MAX_TRACED_CALLS) -> None:
        """Create a recorder.

        Args:
            max_calls: Maximum number of calls retained in memory.
        """
        self.max_calls = max_calls
        self._lock = threading.Lock()
        self._traces: OrderedDict[str, list[TraceEvent]] = OrderedDict()

    def record(
        self,
        call_id: str,
        direction: str,
        method: str,
        summary: str,
        *,
        peer: str = "-",
        rule_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Append one event to the trace of a call.

        Args:
            call_id: SIP Call-ID of the call.
            direction: ``in``, ``out`` or ``internal``.
            method: SIP method or status code.
            summary: Short description shown in the console.
            peer: Remote address of the message.
            rule_id: Routing rule that decided this call.
            attributes: Extra structured details.

        Returns:
            The event that was recorded.
        """
        event = TraceEvent(
            timestamp=datetime.now(tz=timezone.utc),
            call_id=call_id,
            direction=direction,
            method=method,
            summary=summary,
            peer=peer,
            rule_id=rule_id,
            attributes=dict(attributes or {}),
        )
        with self._lock:
            events = self._traces.setdefault(call_id, [])
            events.append(event)
            self._traces.move_to_end(call_id)
            while len(self._traces) > self.max_calls:
                self._traces.popitem(last=False)
        return event

    def trace_for(self, call_id: str) -> CallTrace:
        """Return the trace of one call.

        Args:
            call_id: SIP Call-ID of the call.

        Returns:
            The trace, empty when the Call-ID is unknown.
        """
        with self._lock:
            return CallTrace(call_id=call_id, events=list(self._traces.get(call_id, [])))

    def recent(self, limit: int = 20) -> list[CallTrace]:
        """Return the most recent traces, newest first.

        Args:
            limit: Maximum number of traces to return.

        Returns:
            A list of traces ordered from most to least recently updated.
        """
        with self._lock:
            items = list(self._traces.items())[::-1][:limit]
            return [CallTrace(call_id=call_id, events=list(events)) for call_id, events in items]

    def known_call_ids(self) -> list[str]:
        """Return the Call-IDs currently retained, newest first.

        Returns:
            The retained Call-IDs in recency order.
        """
        with self._lock:
            return list(self._traces.keys())[::-1]

    def clear(self) -> None:
        """Drop all retained traces."""
        with self._lock:
            self._traces.clear()


_RECORDER: TraceRecorder | None = None


def get_trace_recorder() -> TraceRecorder:
    """Return the process-wide trace recorder, creating it on first use.

    Returns:
        The shared :class:`TraceRecorder` instance.
    """
    global _RECORDER
    if _RECORDER is None:
        _RECORDER = TraceRecorder()
    return _RECORDER
