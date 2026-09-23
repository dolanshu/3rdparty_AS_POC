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

"""Call control logic of the anti-fraud AS.

:class:`FraudCallMap` is the process-wide trunk entry point: it enforces the peer allowlist
and creates one :class:`FraudCallController` per call. The controller takes the verdict for
**this** call in :meth:`FraudCallController.decide` and hands the shared shell a
:class:`as_platform.call_controller.PolicyDecision`; the shell then either relays the INVITE
or answers it from the answering leg (reject). On the allow path the INVITE is relayed with
the pass-through header set and an unchanged SDP body, while the outbound leg gets its own
dialog ``Call-ID`` derived from the trunk one (``docs/architecture/lld.md`` section 2.3).

**The reject path is UAS behaviour, not B2BUA** (``docs/phase2-plan.md`` section 3, P8
"Known collisions"): no second leg is ever originated, so ``uaO`` stays ``None`` and the
``608`` goes out on ``uaA``. The reject does **not** depend on the UAC's ``Feature-Caps``
declaration: RFC 8688 section 3.4 forwards the 608 as the final response regardless, and the
declaration only decides whether the section 3.4 announcement obligation was met. That
difference is recorded as ``sip_608_declared`` so it is visible rather than silent
(ADR-0007 decision 5).

The relay mechanics, the timers, the trace, the log and the disposition recording live in
:class:`as_platform.call_controller.BaseCallController`; the one-leg invariant of
``docs/architecture/lld.md`` section 9.6 is a base invariant. This module supplies the
verdict — the calling party plus cross-call state — and the error family the verdict uses.
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

from as_platform.call_controller import (
    LEG_NEXT_HOP,
    LEG_TRUNK,
    BaseCallController,
    BaseCallMap,
    PolicyAction,
    PolicyDecision,
)
from as_platform.hop import NextHop
from as_platform.observability.logging import LogDirection, get_logger, log_event
from as_platform.route_header import parse_top_route_target
from as_platform.observability.metrics import CallDisposition, MetricsRegistry
from as_platform.observability.tracing import TraceRecorder
from as_platform.sip_adapter import outbound_call_id
from sippy.CCEvents import CCEventFail, CCEventTry
from sippy.SipCallId import SipCallId

from anti_fraud_as.caller_state import CallerStateStore
from anti_fraud_as.errors import AsError, FraudErrorCode, SkeletonErrorCode
from anti_fraud_as.screening import (
    ScreeningDecision,
    ScreeningPolicy,
    ScreeningSignals,
    ScreeningSource,
    ScreeningVerdict,
    screen,
)
from anti_fraud_as.screening_data import ListMatchResult, ScreeningDataStore

__all__ = ["FraudCallController", "FraudCallMap", "LEG_NEXT_HOP", "LEG_TRUNK"]

_LOGGER = get_logger(__name__)

#: The RFC 8688 section 3.3 capability token a 608-aware UAC declares in ``Feature-Caps``.
SIP_608_TOKEN = "sip.608"

#: Separator between feature tags in a ``Feature-Caps`` value (RFC 6809).
_FEATURE_CAPS_SEPARATOR = re.compile(r"[;,]\s*")

#: Name of the single next hop this AS relays towards. ``FRAUD_SBC_PEER_*`` supplies the
#: fallback wire destination when the trunk carries no ``Route``; when ``Route`` is present
#: the top entry wins (RFC 3261), same as the number-translation AS.
_NEXT_HOP_NAME = "fraud_sbc_peer"


def calling_number_of(request: Any) -> str | None:
    """Return the calling party asserted on the trunk, or ``None`` when it is absent.

    The screening input is the **calling** party. On an IMS trunk that is the
    ``P-Asserted-Identity`` (3GPP TS 24.229); the asserting node is the network, not this
    AS. ``countHFs`` guards the missing header because ``getHFBody`` raises ``IndexError``
    when the header is absent, and the header may carry a display name or parameters, so the
    URI user part is read from the parsed address rather than from the raw string.

    Args:
        request: The trunk INVITE.

    Returns:
        The calling party, or ``None`` when no usable identity is present.
    """
    if request.countHFs("p-asserted-identity") == 0:
        return None
    identity = request.getHFBody("p-asserted-identity")
    url = getattr(getattr(identity, "address", None), "url", None)
    username = getattr(url, "username", None)
    if username is None:
        return None
    value = str(username).strip()
    return value or None


def declares_sip_608(request: Any) -> bool:
    """Tell whether the INVITE declared the RFC 8688 ``sip.608`` capability.

    RFC 8688 section 3.3: a conforming UAC MUST include ``sip.608`` in its ``Feature-Caps``.
    The declaration selects **no** status code — section 3.4 forwards the 608 as the final
    response either way — it only says whether the section 3.4 announcement obligation was
    met. It is therefore recorded, never branched on (ADR-0007 decision 5).

    The match is on the **whole feature tag**, not on a substring: a ``Feature-Caps`` value
    is a list of comma or semicolon separated tags, each optionally prefixed with ``+``, so
    ``sip.6080`` or ``x-sip.608`` must not be read as ``sip.608``.

    Args:
        request: The trunk INVITE.

    Returns:
        ``True`` when a ``Feature-Caps`` header carries the ``sip.608`` feature tag.
    """
    for body in request.getHFBodys("feature-caps"):
        for part in _FEATURE_CAPS_SEPARATOR.split(str(body)):
            if part.strip().lstrip("+").lower() == SIP_608_TOKEN:
                return True
    return False


def _error_code_for(code: str | None) -> FraudErrorCode:
    """Resolve an internal error code string to its enum member.

    Args:
        code: A code such as ``AS-FRAUD-002``, or ``None``.

    Returns:
        The matching :class:`FraudErrorCode`, or ``FRAUD_NO_VERDICT`` when nothing matches.
    """
    for candidate in FraudErrorCode:
        if candidate.code == code:
            return candidate
    return FraudErrorCode.FRAUD_NO_VERDICT


class FraudCallController(BaseCallController):
    """One screened call: the verdict on top of the shared relay shell.

    The relay mechanics, the timers, the trace, the log, the disposition recording and the
    peer-status key are inherited from
    :class:`as_platform.call_controller.BaseCallController`; the one-leg invariant of
    ``docs/architecture/lld.md`` section 9.6 is a base invariant. This class adds the
    verdict (:meth:`decide`) and the vocabulary of the two rejections it can produce.

    Attributes:
        screening_data: Source of the active block/allow lists and thresholds.
        caller_state: The **process-level** cross-call state (ADR-0007 decision 8).
        metrics: Counter registry.
        tracer: Per-Call-ID trace recorder.
        global_config: sippy global configuration of the anti-fraud process.
        next_hop: ``(address, port)`` the allowed INVITE is relayed to.
        call_id: SIP Call-ID of the call, known once the INVITE has been terminated.
        uaA: Answering UA, the leg towards the S-SBC; the only leg of a rejected call.
        uaO: Originating UA, the leg towards the next hop; ``None`` for the whole lifetime
            of a rejected call.
    """

    def __init__(
        self,
        screening_data: ScreeningDataStore,
        caller_state: CallerStateStore,
        *,
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
        global_config: dict[str, Any] | None = None,
        next_hop: tuple[str, int] | None = None,
        app: Any | None = None,
    ) -> None:
        """Create a call controller.

        Args:
            screening_data: Holds and reloads the active screening data.
            caller_state: The process-level cross-call state, shared by every call.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            global_config: sippy global configuration; empty when exercised without a stack.
            next_hop: ``(address, port)`` the allowed INVITE is relayed to.
            app: FastAPI application for event emission (P12); ``None`` backward-compat.
        """
        super().__init__(
            metrics=metrics, tracer=tracer, global_config=global_config, next_hop=next_hop
        )
        self.screening_data = screening_data
        self.caller_state = caller_state
        self._emit_app = app
        if app is not None:
            self._emit_p12("call_started", {"direction": "trunk_in"})

    # ------------------------------------------------------------------
    # P12 per-call event emission (no as_platform changes — AS-local only)
    # ------------------------------------------------------------------

    _SOURCE: ClassVar[str] = "as_anti_fraud"

    def _emit_p12(self, event: str, attributes: dict[str, Any]) -> None:
        """Emit a per-call event via the internal_api WebSocket fanout.

        Uses the uvicorn daemon thread's event loop (``app.state._loop``) for
        thread-safe scheduling via ``run_coroutine_threadsafe``. No-op when
        the daemon loop has not started yet.
        """
        import asyncio as _asyncio
        import json as _json
        import time as _time

        if self._emit_app is None:
            return
        loop = getattr(self._emit_app.state, "_loop", None)
        if loop is None:
            return
        event_dict = {
            "timestamp": _time.time(),
            "source": self._SOURCE,
            "event": event,
            "call_id": getattr(self, "call_id", "unknown"),
            "attributes": attributes,
        }
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
                _asyncio.run_coroutine_threadsafe(self._emit_app.state.broadcast(msg), loop)
        except (RuntimeError, AttributeError):
            pass  # asyncio bridge not ready — drop silently

    # --- P12 apply_call_policy / record_disposition overrides ---------------

    def apply_call_policy(self, event: Any) -> PolicyDecision:
        """Override to emit call_allowed / call_rejected_608 after decide()."""
        decision = super().apply_call_policy(event)
        if decision.action is PolicyAction.RELAY:
            self._emit_p12(
                "call_allowed",
                {"verdict": "allow"},
            )
        elif decision.action is PolicyAction.REJECT:
            self._emit_p12(
                "call_rejected_608",
                {
                    "verdict": "reject",
                    "error_code": decision.error.code.code if decision.error else "",
                    "screen_source": decision.attributes.get("screen_source", ""),
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
        """Take the verdict for this call, then report the decision to the base.

        Args:
            event: The ``CCEventTry`` raised by the answering leg.

        Returns:
            A relay decision carrying the unchanged INVITE with its own outbound Call-ID
            and the single next hop, or a reject decision carrying the ``608`` error.
        """
        request = self._trunk_request
        calling_number = calling_number_of(request) if request is not None else None
        sip_608_declared = declares_sip_608(request) if request is not None else False
        caller = self.caller_state.observe(calling_number or "-")
        matches = (
            self.screening_data.current.match(calling_number)
            if calling_number is not None
            else ListMatchResult()
        )
        current = self.screening_data.current
        signals = ScreeningSignals(
            calling_number=calling_number or "",
            identity_present=calling_number is not None,
            allowlisted_by=matches.allowed_by.entry_id if matches.allowed_by else None,
            blocklisted_by=matches.blocked_by.entry_id if matches.blocked_by else None,
            effective_reputation=caller.effective_reputation,
            calls_in_window=caller.calls_in_window,
        )
        decision = screen(
            signals,
            ScreeningPolicy(
                reject_below_reputation=current.reject_below_reputation,
                reject_above_calls=current.reject_above_calls,
            ),
        )
        self._record_verdict(decision, signals, sip_608_declared)
        if decision.verdict is ScreeningVerdict.REJECT:
            self.caller_state.penalise(signals.calling_number)
            error = AsError(
                _error_code_for(decision.error_code),
                decision.reason,
                call_id=self.call_id,
                context={"screen_source": decision.source.value},
            )
            if not sip_608_declared:
                # RFC 8688 section 3.4: the call is answered 608 either way, but the
                # announcement obligation was not met. Counted **only** for
                # screening-driven rejects — a configuration failure is not a section 3.4
                # case and must not inflate this counter.
                self.metrics.record_counter("reject.sip_608_undeclared")
            self.metrics.record_error(error.code.code)
            return self._reject(
                error,
                attributes=self._reject_attributes(
                    decision.source, decision.list_entry, sip_608_declared
                ),
                reject_log_fields={"sip_608_declared": sip_608_declared},
            )
        if self.next_hop is None:
            error = AsError(
                SkeletonErrorCode.CFG_MISSING,
                "FRAUD_SBC_PEER_ADDRESS is required: the AS must know its next hop",
                call_id=self.call_id,
            )
            self.metrics.record_error(error.code.code)
            return self._reject(
                error,
                attributes=self._reject_attributes(ScreeningSource.NONE, None, None),
            )
        original = event.getData()
        # The second leg gets its own Call-ID: sippy regenerates ``From``, ``To`` and
        # ``CSeq`` for the outbound dialog, but copies a non-``None`` Call-ID verbatim
        # (``sippy/UacStateIdle.py``) and this AS runs a bare ``sippy.UA`` rather than
        # ``CCB2BUA`` (which would rewrite it itself, ``sippy/b2bua.py``). Derive a fresh
        # ``SipCallId`` from the trunk one with sippy's own ``-b2b_1`` suffix style; the
        # inbound object is never mutated because it is the trunk leg's dialog identity
        # (``docs/architecture/lld.md`` section 2.3). Every other element of the event, the
        # called number included, is passed through unchanged — screening does not rewrite
        # the Request-URI (ADR-0007 decision 6).
        outbound_call_id_value = SipCallId(outbound_call_id(str(original[0])))
        outbound_event = CCEventTry(
            (
                outbound_call_id_value,
                original[1],
                original[2],
                original[3],
                original[4],
                original[5],
            )
        )
        outbound_event.extra_headers = self._pass_through_headers(self._trunk_request)
        if event.max_forwards is not None:
            outbound_event.max_forwards = event.max_forwards
        hop = NextHop(name=_NEXT_HOP_NAME, address=self.next_hop[0], port=self.next_hop[1])
        return PolicyDecision(
            action=PolicyAction.RELAY,
            outbound_event=outbound_event,
            next_hops=[hop],
            relay_log_message="invite relayed towards the S-SBC (top Route)",
            relay_log_fields={"verdict": ScreeningVerdict.ALLOW.value},
        )

    def _originate_towards(self, hop: NextHop) -> None:
        """Send the outbound INVITE to the top Route target when the trunk carried one.

        ``FRAUD_SBC_PEER_*`` names the fallback hop when no ``Route`` is present; loose
        routing uses the trunk ``Route`` set the S-SBC inserted to choose the wire
        destination on the allow path.
        """
        route_target = parse_top_route_target(self._trunk_request)
        if route_target is not None:
            address, port = route_target
            hop = hop.model_copy(update={"address": address, "port": port})
        super()._originate_towards(hop)

    def _reject(
        self,
        error: AsError,
        *,
        attributes: dict[str, Any],
        reject_log_fields: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Build the reject decision that answers the trunk leg with ``error``.

        Args:
            error: The error carrying the SIP status, the phrase and the internal code.
            attributes: Extra trace fields beside ``leg`` and ``error_code``.
            reject_log_fields: Extra log fields beside ``error.as_log_fields()``.

        Returns:
            The reject decision the base applies.
        """
        return PolicyDecision(
            action=PolicyAction.REJECT,
            error=error,
            disposition=CallDisposition.REJECTED,
            attributes=attributes,
            reject_trace_summary=f"{error.sip_status} {error.sip_phrase} answered on the trunk leg",
            reject_log_message="call rejected by screening",
            reject_log_fields=reject_log_fields or {},
        )

    def _reject_attributes(
        self, source: ScreeningSource, list_entry: str | None, sip_608_declared: bool | None
    ) -> dict[str, Any]:
        """Build the trace attributes of a final answer on the trunk leg.

        Args:
            source: Signal that decided, for the trace.
            list_entry: Matched list entry identifier, when there is one.
            sip_608_declared: Whether the INVITE declared ``sip.608``; ``None`` when the AS
                did not get as far as screening (a configuration failure), in which case the
                field is omitted rather than reported as ``false``.

        Returns:
            The trace attributes, in the order the answer has always carried them.
        """
        attributes: dict[str, Any] = {"screen_source": source.value}
        if list_entry:
            attributes["list_entry"] = list_entry
        if sip_608_declared is not None:
            attributes["sip_608_declared"] = sip_608_declared
        return attributes

    def _record_verdict(
        self, decision: ScreeningDecision, signals: ScreeningSignals, sip_608_declared: bool
    ) -> None:
        """Count and trace one verdict (REQ-F-024).

        Args:
            decision: The verdict that was taken.
            signals: The signals it was taken from.
            sip_608_declared: Whether the INVITE declared ``sip.608``.
        """
        self.metrics.record_counter(f"verdict.{decision.verdict.value}")
        self.metrics.record_counter(f"screen.{decision.source.value}")
        attributes: dict[str, Any] = {
            "leg": LEG_TRUNK,
            "verdict": decision.verdict.value,
            "screen_source": decision.source.value,
            "screen_reason": decision.reason,
            "reputation": round(decision.score, 2),
            "calls_in_window": signals.calls_in_window,
            "identity_present": signals.identity_present,
            "sip_608_declared": sip_608_declared,
        }
        if decision.list_entry:
            attributes["list_entry"] = decision.list_entry
        self.tracer.record(
            self.call_id,
            LogDirection.INTERNAL,
            "verdict",
            f"{decision.verdict.value}: {decision.reason}",
            peer=self.trunk_peer,
            attributes=attributes,
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "screening verdict taken",
            call_id=self.call_id,
            direction=LogDirection.INTERNAL,
            peer=self.trunk_peer,
            verdict=decision.verdict.value,
            screen_source=decision.source.value,
            screen_reason=decision.reason,
            reputation=round(decision.score, 2),
            calls_in_window=signals.calls_in_window,
            identity_present=signals.identity_present,
            sip_608_declared=sip_608_declared,
            list_entry=decision.list_entry or "",
        )

    # --- the shell's overridable points -------------------------------------

    def _peer_status_key(self, hop: NextHop) -> str:
        """Render the hop as ``address:port`` for the peer-status counters.

        The anti-fraud hop is configured by address and port only, so its key is exactly the
        ``address:port`` it has always been, not the shell's default ``name:address:port``.

        Args:
            hop: The hop whose status is being recorded.

        Returns:
            The ``address:port`` of the hop.
        """
        return f"{hop.address}:{hop.port}"

    def _no_answer_hop_label(self) -> str:
        """Render the hop a no-answer warning names, as ``address:port``.

        Returns:
            The serving hop's address and port, or ``"-"`` when none is configured.
        """
        return self._next_hop_peer()


class FraudCallMap(BaseCallMap):
    """Process-wide entry point for requests arriving on the anti-fraud trunk.

    The trunk is untrusted: a request from an address outside ``FRAUD_ALLOWED_PEERS`` is
    answered with ``403`` and ``AS-PEER-001`` before any call state is created
    (``AGENT.md`` section 9). Everything else is handed to a fresh
    :class:`FraudCallController`, which owns the verdict for that one call. The allowlist
    check and the request dispatch are inherited from
    :class:`as_platform.call_controller.BaseCallMap`; this class supplies the screening data
    and the process-level caller state the controller needs.

    Attributes:
        global_config: sippy global configuration of the process.
        screening_data: Source of the active block/allow lists and thresholds.
        caller_state: The process-level cross-call state.
        allowed_peers: Source addresses accepted on the trunk.
        metrics: Counter registry.
        tracer: Trace recorder.
        controllers: The calls currently known to the AS, in creation order.
    """

    def __init__(
        self,
        global_config: dict[str, Any],
        screening_data: ScreeningDataStore,
        caller_state: CallerStateStore,
        *,
        allowed_peers: tuple[str, ...] = (),
        metrics: MetricsRegistry | None = None,
        tracer: TraceRecorder | None = None,
        app: Any | None = None,
    ) -> None:
        """Create the trunk call map.

        Args:
            global_config: sippy global configuration; ``nh_addr`` carries the next hop.
            screening_data: Holds and reloads the active screening data.
            caller_state: The process-level cross-call state.
            allowed_peers: Source addresses accepted on the trunk.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            app: FastAPI app for P12 event emission; ``None`` backward-compat.
        """
        super().__init__(global_config, allowed_peers=allowed_peers, metrics=metrics, tracer=tracer)
        self.screening_data = screening_data
        self.caller_state = caller_state
        self.app = app

    def _build_controller(self, next_hop: tuple[str, int] | None) -> FraudCallController:
        """Create a call controller bound to this process configuration.

        Args:
            next_hop: ``(address, port)`` of the configured next hop, or ``None``.

        Returns:
            A controller wired to the trunk call map's stack, state and next hop.
        """
        return FraudCallController(
            self.screening_data,
            self.caller_state,
            metrics=self.metrics,
            tracer=self.tracer,
            global_config=self.global_config,
            next_hop=next_hop,
            app=self.app,
        )
