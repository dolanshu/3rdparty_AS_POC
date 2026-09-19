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

"""Call Control Logic — the business hook between the two call legs.

The B2BUA relay mechanics — the relay of call control events between the answering UA
(trunk leg, ``uaA``) and the originating UA (next-hop leg, ``uaO``), the failover walk, the
no-answer timer, the trace, the log, the disposition recording and the peer-status key —
live in :class:`as_platform.call_controller.BaseCallController`. This module supplies the
one thing that is specific to the number-translation AS: :meth:`CallController.decide`,
which runs the routing engine and hands the base a
:class:`as_platform.call_controller.PolicyDecision` (ADR-0009 decision 4).

The decision itself stays a pure function in :mod:`as_app.routing.engine`, so the policy is
testable without a stack (``AGENT.md`` section 5).

**Translation seam.** :meth:`CallController.decide` is reached through
:meth:`as_platform.call_controller.BaseCallController.apply_call_policy`, the single place
where an inbound INVITE is decided on before it leaves on the outbound leg. It rewrites the
called number and the outbound dialog ``Call-ID``; no other place in the signalling path may
touch the number — that is what keeps the seam honest.

**Peer control.** :class:`TrunkCallMap` is the process-wide entry point for requests
arriving on the trunk. It rejects sources outside ``ALLOWED_PEERS`` with ``403`` and
``AS-PEER-001`` before any call state is created (``AGENT.md`` section 9).
"""

from __future__ import annotations

import logging
from typing import Any

from as_platform.call_controller import (
    BaseCallController,
    BaseCallMap,
    PolicyAction,
    PolicyDecision,
)
from sippy.CCEvents import CCEventTry
from sippy.SipCallId import SipCallId

from as_app.errors import AsError, AsErrorCode
from as_app.observability.logging import LogDirection, get_logger, log_event
from as_app.observability.metrics import CallDisposition, MetricsRegistry
from as_app.observability.tracing import TraceRecorder
from as_app.routing.engine import Disposition, RoutingDecision, decide
from as_app.routing.rules import RuleSetStore
from as_app.sip_adapter import extract_called_number, outbound_call_id

__all__ = ["CallController", "TrunkCallMap"]

_LOGGER = get_logger(__name__)


class CallController(BaseCallController):
    """The number-translation call: the routing decision on top of the shared shell.

    The relay mechanics, the failover walk, the timers, the trace, the log, the disposition
    recording and the peer-status key are inherited from
    :class:`as_platform.call_controller.BaseCallController`; the one-leg invariant of
    ``docs/architecture/lld.md`` section 9.6 is a base invariant. This class adds only the
    routing decision and the vocabulary of the rejection it can produce.

    Attributes:
        rule_set_store: Source of the currently active rule set (hot reload, ADR-0004).
        metrics: Counter registry.
        tracer: Per-Call-ID trace recorder.
        global_config: sippy global configuration of the AS process.
        next_hop: ``(address, port)`` of the S-SBC the outbound INVITE is sent to.
        call_id: SIP Call-ID of the call, known once the INVITE has been terminated.
        uaA: Answering UA, the leg towards the S-SBC; always present once the INVITE is
            terminated.
        uaO: Originating UA, the leg towards the next hop; ``None`` until the call is
            routed, and ``None`` for the whole lifetime of a UAS-only (rejected) call.
    """

    def __init__(
        self,
        rule_set_store: RuleSetStore,
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
        *,
        global_config: dict[str, Any] | None = None,
        next_hop: tuple[str, int] | None = None,
    ) -> None:
        """Create a call controller.

        Args:
            rule_set_store: Holds and reloads the active rule set.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            global_config: sippy global configuration; empty when the controller is
                exercised without a stack (unit tests).
            next_hop: ``(address, port)`` of the next hop for the outbound INVITE.
        """
        super().__init__(
            metrics=metrics, tracer=tracer, global_config=global_config, next_hop=next_hop
        )
        self.rule_set_store = rule_set_store
        # The routing decision of this call, kept so the failover attempts and the
        # rejection vocabulary reproduce the decision that produced them.
        self._decision: RoutingDecision | None = None

    # --- the application hook -----------------------------------------------

    def decide(self, event: Any) -> PolicyDecision:
        """Translate and route the call, then report the decision to the base.

        Args:
            event: The ``CCEventTry`` raised by the answering leg.

        Returns:
            A relay decision carrying the translated event and the ordered next hops, or a
            reject decision carrying the :class:`AsError` of the routing decision.
        """
        original = event.getData()
        called_number = str(original[2])
        decision = self.route_call(self.call_id, called_number)
        self._decision = decision
        if decision.disposition is not Disposition.ROUTE:
            error = self.reject_error(decision, self.call_id)
            return PolicyDecision(
                action=PolicyAction.REJECT,
                error=error,
                disposition=self.disposition_for(decision),
                attributes={"rule_id": decision.rule_id or ""},
                reject_trace_summary=(
                    f"{error.sip_status} {error.sip_phrase} relayed to the trunk leg"
                ),
                reject_log_message="call rejected by routing policy",
            )
        translated = decision.translated_number or called_number
        # The second leg gets its own Call-ID: sippy regenerates ``From``, ``To`` and
        # ``CSeq`` for the outbound dialog, but copies a non-``None`` Call-ID verbatim
        # (``sippy/UacStateIdle.py``) and this AS runs a bare ``sippy.UA`` rather than
        # ``CCB2BUA`` (which would rewrite it itself, ``sippy/b2bua.py``). Derive a fresh
        # ``SipCallId`` from the trunk one with sippy's own ``-b2b_1`` suffix style; the
        # inbound object is never mutated because it is the trunk leg's dialog identity
        # (``docs/architecture/lld.md`` section 2.3). Every failover hop reuses this same
        # event through ``_pending_event``, so one call has one outbound Call-ID.
        outbound_call_id_value = SipCallId(outbound_call_id(str(original[0])))
        rebuilt = CCEventTry(
            (
                outbound_call_id_value,
                original[1],
                translated,
                original[3],
                original[4],
                original[5],
            )
        )
        rebuilt.extra_headers = self._pass_through_headers(self._trunk_request)
        if event.max_forwards is not None:
            rebuilt.max_forwards = event.max_forwards
        log_event(
            _LOGGER,
            logging.INFO,
            "call translated",
            call_id=self.call_id,
            direction=LogDirection.INTERNAL,
            rule_id=decision.rule_id or "",
            called_number=called_number,
            translated_number=translated,
            target_format=decision.target_format.value if decision.target_format else "",
            next_hops=",".join(hop.name for hop in decision.next_hops),
        )
        return PolicyDecision(
            action=PolicyAction.RELAY,
            outbound_event=rebuilt,
            next_hops=list(decision.next_hops),
            # The relay line's trace attributes and log fields name the called number and
            # the hop of the attempt; the base resolves both, so the values here are the
            # first attempt's and the base overwrites them on a failover attempt.
            attributes={"called_number": translated, "next_hop": decision.next_hops[0].name},
            relay_log_message="invite originated towards the next hop",
            relay_log_fields={
                "called_number": translated,
                "next_hop": decision.next_hops[0].name,
                "rule_id": self._decision.rule_id if self._decision else "",
            },
        )

    def _inbound_fields(self, request: Any) -> dict[str, Any]:
        """Return the called number the inbound INVITE carries.

        The number-translation AS reads the called number off the Request-URI when the
        INVITE arrives, so it is on the inbound trace and log line.

        Args:
            request: The trunk INVITE.

        Returns:
            ``{"called_number": ...}``.

        Raises:
            AsError: ``AS-PEER-003`` when the Request-URI carries no called number.
        """
        return {"called_number": extract_called_number(str(request.getRURI()))}

    # --- decisions, counters and traces -------------------------------------

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


class TrunkCallMap(BaseCallMap):
    """Process-wide entry point for requests arriving on the SIP trunk.

    The trunk is untrusted: a request from an address outside ``ALLOWED_PEERS`` is answered
    with ``403`` and ``AS-PEER-001`` before any call state is created (``AGENT.md``
    section 9). Everything else is handed to a fresh :class:`CallController`, which owns the
    two legs of that one call. The allowlist check and the request dispatch are inherited
    from :class:`as_platform.call_controller.BaseCallMap`; this class supplies the rule set
    the controller needs.

    Attributes:
        global_config: sippy global configuration of the AS process.
        rule_set_store: Source of the currently active rule set.
        allowed_peers: Source addresses accepted on the trunk.
        metrics: Counter registry.
        tracer: Trace recorder.
        controllers: The calls currently known to the AS, in creation order.
    """

    def __init__(
        self,
        global_config: dict[str, Any],
        rule_set_store: RuleSetStore,
        *,
        allowed_peers: tuple[str, ...] = (),
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
    ) -> None:
        """Create the trunk call map.

        Args:
            global_config: sippy global configuration; ``nh_addr`` carries the next hop.
            rule_set_store: Holds and reloads the active rule set.
            allowed_peers: Source addresses accepted on the trunk.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
        """
        super().__init__(global_config, allowed_peers=allowed_peers, metrics=metrics, tracer=tracer)
        self.rule_set_store = rule_set_store

    def _build_controller(self, next_hop: tuple[str, int] | None) -> CallController:
        """Create a call controller bound to this process configuration.

        Args:
            next_hop: ``(address, port)`` of the configured next hop, or ``None``.

        Returns:
            A controller wired to the trunk call map's stack and next hop.
        """
        return CallController(
            self.rule_set_store,
            self.metrics,
            self.tracer,
            global_config=self.global_config,
            next_hop=next_hop,
        )
