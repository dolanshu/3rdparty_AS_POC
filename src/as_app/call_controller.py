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

"""Call Control Logic — the business hook between the two call legs.

sippy calls ``recvEvent(event, ua)`` on the controller; the controller relays events
between the answering UA (trunk leg) and the originating UA (next-hop leg) and applies
the routing decision where the event passes between them (ADR-0001).

This class stays thin: the decision itself is a pure function in
:mod:`as_app.routing.engine`, so the policy is testable without a stack
(``AGENT.md`` section 5). The sippy event plumbing is wired in M1.
"""

from __future__ import annotations

import logging
from typing import Any

from as_app.errors import AsError, AsErrorCode
from as_app.observability.logging import LogDirection, get_logger, log_event
from as_app.observability.metrics import CallDisposition, MetricsRegistry, get_metrics_registry
from as_app.observability.tracing import TraceRecorder, get_trace_recorder
from as_app.routing.engine import Disposition, RoutingDecision, decide
from as_app.routing.rules import RuleSetStore

__all__ = ["CallController"]

_LOGGER = get_logger(__name__)


class CallController:
    """Applies the routing decision to a call and records it.

    Attributes:
        rule_set_store: Source of the currently active rule set (hot reload, ADR-0004).
        metrics: Counter registry.
        tracer: Per-Call-ID trace recorder.
    """

    def __init__(
        self,
        rule_set_store: RuleSetStore,
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
    ) -> None:
        """Create a call controller.

        Args:
            rule_set_store: Holds and reloads the active rule set.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
        """
        self.rule_set_store = rule_set_store
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()

    def route_call(self, call_id: str, called_number: str) -> RoutingDecision:
        """Translate and route a called number, and record the decision.

        Args:
            call_id: SIP Call-ID of the call.
            called_number: Called number as received on the trunk.

        Returns:
            The routing decision to apply on the outbound leg.

        Raises:
            AsError: Propagated from the routing engine.
        """
        decision = decide(self.rule_set_store.current, called_number)
        if decision.rule_id is not None:
            self.metrics.record_rule_hit(decision.rule_id)
        if decision.error_code is not None:
            self.metrics.record_error(decision.error_code)
        self.tracer.record(
            call_id,
            LogDirection.INTERNAL,
            "decision",
            f"{decision.disposition.value}: {decision.reason or 'no reason'}",
            rule_id=decision.rule_id,
            attributes={
                "called_number": called_number,
                "translated_number": decision.translated_number or "",
                "next_hops": [hop.name for hop in decision.next_hops],
            },
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "routing decision taken",
            call_id=call_id,
            direction=LogDirection.INTERNAL,
            rule_id=decision.rule_id or "",
            disposition=decision.disposition.value,
            called_number=called_number,
            translated_number=decision.translated_number or "",
        )
        return decision

    @staticmethod
    def disposition_for(decision: RoutingDecision) -> CallDisposition:
        """Map a routing decision to the call disposition used by the counters.

        Args:
            decision: The routing decision of a call.

        Returns:
            The disposition that is counted when the call ends.
        """
        if decision.disposition is Disposition.NO_MATCH:
            return CallDisposition.NO_MATCH
        if decision.disposition is Disposition.REJECT:
            return CallDisposition.REJECTED
        return CallDisposition.COMPLETED

    def reject_error(self, decision: RoutingDecision, call_id: str) -> AsError:
        """Build the error that reports a rejected or unroutable call.

        Args:
            decision: A decision whose disposition is not :attr:`Disposition.ROUTE`.
            call_id: SIP Call-ID of the call.

        Returns:
            An :class:`AsError` carrying the SIP status and the internal error code.

        Raises:
            AsError: ``AS-ROUTE-004`` when the decision is not a rejection at all.
        """
        if decision.disposition is Disposition.ROUTE:
            raise AsError(
                AsErrorCode.ROUTE_TRANSLATION_FAILED,
                f"decision for rule {decision.rule_id} is routable and cannot be rejected",
                call_id=call_id,
            )
        code = AsErrorCode.ROUTE_REJECTED
        for candidate in AsErrorCode:
            if candidate.code == decision.error_code:
                code = candidate
                break
        return AsError(
            code, decision.reason, call_id=call_id, context={"rule_id": decision.rule_id or ""}
        )

    def recv_event(self, event: Any, ua: Any) -> None:  # noqa: ANN401
        """Sippy event hook; relays events between the two legs.

        The sippy primitives are wired in M1 (signalling path). The hook is declared here
        so that the boundary between the stack and the business logic is visible.

        Args:
            event: A sippy ``CCEvent``.
            ua: The sippy UA the event came from.

        Raises:
            AsError: ``AS-INT-001`` until the signalling path is implemented in M1.
        """
        raise AsError(
            AsErrorCode.INTERNAL_ERROR,
            "sippy event plumbing is implemented in M1 (signalling path)",
            context={"event": type(event).__name__, "ua": type(ua).__name__},
        )
