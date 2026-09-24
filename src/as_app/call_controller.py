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
from typing import Any, ClassVar

from as_platform.call_controller import (
    BaseCallController,
    BaseCallMap,
    PolicyAction,
    PolicyDecision,
)
from sippy.CCEvents import CCEventFail, CCEventTry
from sippy.SipCallId import SipCallId

from as_app.errors import AsError, AsErrorCode
from as_app.observability.logging import LogDirection, get_logger, log_event
from as_app.observability.metrics import CallDisposition, MetricsRegistry
from as_app.observability.tracing import TraceRecorder
from as_app.route_header import parse_top_route_target
from as_app.routing.engine import Disposition, RoutingDecision, decide
from as_app.routing.rules import NextHop, RuleSetStore
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
        app: Any | None = None,
    ) -> None:
        """Create a call controller.

        Args:
            rule_set_store: Holds and reloads the active rule set.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            global_config: sippy global configuration; empty when the controller is
                exercised without a stack (unit tests).
            next_hop: ``(address, port)`` of the next hop for the outbound INVITE.
            app: FastAPI application for event emission (P12); ``None`` when running
                without a console connection (backward-compatible default).
        """
        super().__init__(
            metrics=metrics, tracer=tracer, global_config=global_config, next_hop=next_hop
        )
        self.rule_set_store = rule_set_store
        self._emit_app = app
        # The routing decision of this call, kept so the failover attempts and the
        # rejection vocabulary reproduce the decision that produced them.
        self._decision: RoutingDecision | None = None

    def recv_request(self, request: Any, transaction: Any) -> Any:
        """Terminate the trunk INVITE, then emit ``call_started`` with the real Call-ID."""
        result = super().recv_request(request, transaction)
        if self._emit_app is not None:
            self._emit_p12("call_started", {"direction": "trunk_in"})
        return result

    # ------------------------------------------------------------------
    # P12 per-call event emission (no as_platform changes — AS-local only)
    # ------------------------------------------------------------------

    _SOURCE: ClassVar[str] = "as_translation"

    def _emit_p12(self, event: str, attributes: dict[str, Any]) -> None:
        """Emit a per-call event via the internal_api WebSocket fanout.

        Safe to call from any thread — uses the uvicorn daemon thread's event
        loop (captured in ``app.state._loop``) and bridges via
        ``run_coroutine_threadsafe``. No-op when :attr:`_emit_app` is ``None``
        or the daemon loop has not started yet.
        """
        import asyncio as _asyncio
        import json as _json
        import time as _time

        if self._emit_app is None:
            return
        loop = getattr(self._emit_app.state, "_loop", None)
        if loop is None:
            return  # daemon thread not ready yet — drop silently
        event_dict = {
            "timestamp": _time.time(),
            "source": self._SOURCE,
            "event": event,
            "call_id": getattr(self, "call_id", "unknown"),
            "attributes": attributes,
        }
        # JSON serialization errors are a real bug (non-serializable attribute);
        # they should log, not pass silently. Asyncio scheduling errors
        # (RuntimeError / AttributeError on the bridge path) are the intended
        # silent-drop case.
        try:
            msg = _json.dumps(event_dict, default=str)
        except (TypeError, ValueError) as exc:
            _LOGGER.warning(
                "P12 emit serialization failed",
                extra={"event": event, "call_id": event_dict["call_id"], "error": str(exc)},
            )
            return
        try:
            try:
                running = _asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                loop.create_task(self._emit_app.state.broadcast(msg))
            else:
                _asyncio.run_coroutine_threadsafe(
                    self._emit_app.state.broadcast(msg), loop
                )
        except (RuntimeError, AttributeError):
            pass  # asyncio bridge not ready — drop silently

    def _originate_towards(self, hop: NextHop) -> None:
        """Send the outbound INVITE to the top Route target when the trunk carried one.

        The routing catalogue names the operator S-SBC hop; RFC 3261 loose routing uses
        the trunk ``Route`` set the S-SBC inserted to choose the wire destination.
        """
        route_target = parse_top_route_target(self._trunk_request)
        if route_target is not None:
            address, port = route_target
            hop = hop.model_copy(update={"address": address, "port": port})
        super()._originate_towards(hop)

    # --- P12 apply_call_policy / record_disposition overrides ---------------

    def apply_call_policy(self, event: Any) -> PolicyDecision:
        """Override to emit call_routed / call_rejected after decide()."""
        decision = super().apply_call_policy(event)
        if decision.action is PolicyAction.RELAY:
            self._emit_p12(
                "call_routed",
                {
                    "rule_id": self._decision.rule_id if self._decision else "",
                    "next_hop": decision.next_hops[0].name if decision.next_hops else "",
                    "translated_number": (
                        self._decision.translated_number if self._decision else ""
                    ),
                },
            )
        elif decision.action is PolicyAction.REJECT:
            self._emit_p12(
                "call_rejected",
                {
                    "rule_id": decision.attributes.get("rule_id", ""),
                    "error_code": decision.error.code.code if decision.error else "",
                    "sip_status": decision.error.sip_status if decision.error else 0,
                },
            )
        return decision

    def _record_disposition(self, event: Any) -> None:
        """Override to emit call_ended with reason classification."""
        super()._record_disposition(event)
        if isinstance(event, CCEventFail):
            reason = "fail"
        elif self.uaA is not None and bool(self.uaA.isConnected()):
            reason = "bye"
        else:
            reason = "cancel"
        self._emit_p12("call_ended", {"reason": reason})

    # --- the application hook -----------------------------------------------

    def decide(self, event: Any) -> PolicyDecision:
        """Translate and route the call, then report the decision to the base.

        The application owns the conversion of a failure it cannot relay: a routing
        failure the engine raises (``AS-ROUTE-004``, ``AS-ROUTE-003``) becomes a reject
        decision here rather than an :class:`AsError` escaping to the base, because the
        base applies data and cannot build this application's reject vocabulary
        (ADR-0009 decision 4).

        Args:
            event: The ``CCEventTry`` raised by the answering leg.

        Returns:
            A relay decision carrying the translated event and the ordered next hops, or a
            reject decision carrying the :class:`AsError` of the routing decision.
        """
        original = event.getData()
        called_number = str(original[2])
        try:
            decision = self.route_call(self.call_id, called_number)
        except AsError as routing_error:
            # The engine could not produce a decision at all — an empty translation or a
            # hop it cannot resolve. ``self._decision`` stays ``None``, so the trunk answer
            # is the pre-P10 one: the error's own status, counted as ``REJECTED``, with no
            # rule id (the old ``reject_on_trunk`` fell back to ``REJECTED`` when the
            # decision was ``None``).
            return self._reject_decision(
                routing_error, disposition=CallDisposition.REJECTED, rule_id=None
            )
        self._decision = decision
        if decision.disposition is not Disposition.ROUTE:
            error = self.reject_error(decision, self.call_id)
            return self._reject_decision(
                error, disposition=self.disposition_for(decision), rule_id=decision.rule_id
            )
        if not decision.next_hops:
            return self._reject_decision(
                AsError(
                    AsErrorCode.ROUTE_NO_NEXT_HOP,
                    f"rule {decision.rule_id or '-'} selected no next hop",
                    call_id=self.call_id,
                ),
                disposition=CallDisposition.REJECTED,
                rule_id=decision.rule_id,
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
            relay_log_message="invite originated towards the S-SBC (top Route)",
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

    @staticmethod
    def _reject_decision(
        error: AsError, *, disposition: CallDisposition, rule_id: str | None
    ) -> PolicyDecision:
        """Build the reject decision that answers the trunk leg with ``error``.

        Both reject paths share this construction so their trace summary and log message
        cannot drift: a routing decision that is not a route, and a failure the engine
        raised before it could decide.

        Args:
            error: The :class:`AsError` carrying the SIP status and the internal code.
            disposition: Outcome to count for this call, supplied rather than derived.
            rule_id: Identifier of the deciding rule, or ``None`` when the engine raised
                before a rule could decide.

        Returns:
            The reject :class:`PolicyDecision`, with this AS's trace summary and log
            message.
        """
        return PolicyDecision(
            action=PolicyAction.REJECT,
            error=error,
            disposition=disposition,
            attributes={"rule_id": rule_id or ""},
            reject_trace_summary=(
                f"{error.sip_status} {error.sip_phrase} relayed to the trunk leg"
            ),
            reject_log_message="call rejected by routing policy",
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
        app: Any | None = None,
    ) -> None:
        """Create the trunk call map.

        Args:
            global_config: sippy global configuration; ``nh_addr`` carries the next hop.
            rule_set_store: Holds and reloads the active rule set.
            allowed_peers: Source addresses accepted on the trunk.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            app: FastAPI app for P12 event emission; ``None`` backward-compat.
        """
        super().__init__(global_config, allowed_peers=allowed_peers, metrics=metrics, tracer=tracer)
        self.rule_set_store = rule_set_store
        self.app = app

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
            app=self.app,
        )
