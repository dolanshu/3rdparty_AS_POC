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
**this** call in :meth:`FraudCallController.apply_call_policy` and then either relays the
INVITE or answers it from the answering leg (reject). On the allow path the INVITE is relayed
with the pass-through header set and an unchanged SDP body, while the outbound leg gets its
own dialog ``Call-ID`` derived from the trunk one (``docs/architecture/lld.md`` section 2.3).

**The reject path is UAS behaviour, not B2BUA** (``docs/phase2-plan.md`` section 3, P8
"Known collisions"): no second leg is ever originated, so ``uaO`` stays ``None`` and the
``608`` goes out on ``uaA``. The reject does **not** depend on the UAC's ``Feature-Caps``
declaration: RFC 8688 section 3.4 forwards the 608 as the final response regardless, and the
declaration only decides whether the section 3.4 announcement obligation was met. That
difference is recorded as ``sip_608_declared`` so it is visible rather than silent
(ADR-0007 decision 5).

The shell mirrors ``as_app.call_controller`` rather than importing it: the decision input
(the calling party plus cross-call state), the log events and the error family all differ,
and the second AS is a concrete application, not a framework (ADR-0007 decision 9). The
duplication is friction for P10.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sippy.CCEvents import (
    CCEventConnect,
    CCEventDisconnect,
    CCEventFail,
    CCEventRing,
    CCEventTry,
    CCEventUpdate,
)
from sippy.SipAddress import SipAddress
from sippy.SipCallId import SipCallId
from sippy.SipConf import SipConf
from sippy.SipContact import SipContact
from sippy.SipHeader import SipHeader
from sippy.SipURL import SipURL
from sippy.UA import UA

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
from as_app.observability.logging import LogDirection, get_logger, log_event
from as_app.observability.metrics import (
    CallDisposition,
    MetricsRegistry,
    PeerStatus,
    get_metrics_registry,
)
from as_app.observability.tracing import TraceRecorder, get_trace_recorder
from as_app.sip_adapter import PASSTHROUGH_HEADERS, is_allowed_peer, outbound_call_id

__all__ = ["FraudCallController", "FraudCallMap", "LEG_NEXT_HOP", "LEG_TRUNK"]

_LOGGER = get_logger(__name__)

#: Leg names used in the trace: ``trunk`` is the leg towards the S-SBC, ``next_hop`` the leg
#: the AS originates when the verdict allows the call.
LEG_TRUNK = "trunk"
LEG_NEXT_HOP = "next_hop"

#: The RFC 8688 section 3.3 capability token a 608-aware UAC declares in ``Feature-Caps``.
SIP_608_TOKEN = "sip.608"

#: Separator between feature tags in a ``Feature-Caps`` value (RFC 6809).
_FEATURE_CAPS_SEPARATOR = re.compile(r"[;,]\s*")

#: How long the relayed INVITE is given to see any response before the originating leg is
#: torn down. Tuned for the loopback POC, mirroring the number-translation AS.
_DEFAULT_NEXT_HOP_EXPIRE = 3.0


@contextmanager
def _fraud_sip_identity(global_config: dict[str, Any]) -> Iterator[None]:
    """Pin the process-wide sippy identity to this AS while a message is generated.

    ``SipConf`` is a module-level singleton and sippy reads it while it builds a ``Via`` or
    a default ``Contact``. The two AS instances are separate processes in production but
    share one interpreter in the tests, so this side pins its own address, port and user
    agent name for the duration of one synchronous message generation.

    Args:
        global_config: sippy global configuration of the anti-fraud process.

    Yields:
        ``None``; the identity is in place for the body of the ``with`` block.
    """
    saved = (SipConf.my_address, SipConf.my_port, SipConf.my_uaname)
    SipConf.my_address = str(global_config.get("_sip_address", SipConf.my_address))
    SipConf.my_port = int(global_config.get("_sip_port", SipConf.my_port))
    SipConf.my_uaname = str(global_config.get("_sip_uaname", SipConf.my_uaname))
    try:
        yield
    finally:
        SipConf.my_address, SipConf.my_port, SipConf.my_uaname = saved


def _local_contact(global_config: dict[str, Any]) -> Any:
    """Build the Contact header this AS puts on its own messages.

    Args:
        global_config: sippy global configuration of the anti-fraud process.

    Returns:
        A ``SipContact`` pointing at the trunk address and port of this AS.
    """
    url = SipURL(
        host=str(global_config.get("_sip_address", SipConf.my_address)),
        port=int(global_config.get("_sip_port", SipConf.my_port)),
        transport=SipConf.my_transport,
    )
    return SipContact(address=SipAddress(url=url))


def _source_address(request: Any) -> str:
    """Return the source IP address of a SIP message received on the trunk.

    Args:
        request: A parsed sippy ``SipRequest``.

    Returns:
        The source address as a string, or ``"-"`` when the stack recorded none.
    """
    source = request.getSource()
    if source is None:
        return "-"
    return str(source[0])


def _source_peer(request: Any) -> str:
    """Return the source of a SIP message as ``address:port`` for log and trace fields.

    Args:
        request: A parsed sippy ``SipRequest``.

    Returns:
        The remote address and port, or ``"-"`` when the stack recorded none.
    """
    source = request.getSource()
    if source is None:
        return "-"
    return f"{source[0]}:{source[1]}"


def _describe_event(event: Any) -> tuple[str, str]:
    """Render a sippy call control event as ``(method, summary)`` for logs and traces.

    Args:
        event: A sippy ``CCEvent``.

    Returns:
        The SIP method or status code and a short lower case English summary.
    """
    if isinstance(event, CCEventTry):
        return ("INVITE", "invite received")
    if isinstance(event, (CCEventRing, CCEventConnect)):
        data = event.getData()
        if data is None:
            return ("180", "ringing")
        code, reason = str(data[0]), str(data[1])
        return (code, f"{code} {reason}".strip())
    if isinstance(event, CCEventFail):
        data = event.getData()
        if data is None:
            return ("500", "call failed")
        return (str(data[0]), f"{data[0]} {data[1]}".strip())
    if isinstance(event, CCEventDisconnect):
        return ("BYE", "call released")
    if isinstance(event, CCEventUpdate):
        return ("INVITE", "session update")
    return (type(event).__name__, "call control event")


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


class FraudCallController:
    """One screened call: the verdict seam, the allow relay and the UAS-only reject.

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
    ) -> None:
        """Create a call controller.

        Args:
            screening_data: Holds and reloads the active screening data.
            caller_state: The process-level cross-call state, shared by every call.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
            global_config: sippy global configuration; empty when exercised without a stack.
            next_hop: ``(address, port)`` the allowed INVITE is relayed to.
        """
        self.screening_data = screening_data
        self.caller_state = caller_state
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()
        self.global_config: dict[str, Any] = dict(global_config or {})
        self.next_hop = next_hop
        self.call_id: str = "-"
        self.trunk_peer: str = "-"
        self.uaA: Any = None
        self.uaO: Any = None
        self._trunk_request: Any = None
        self._verdict: ScreeningDecision | None = None
        self._no_answer_timer: Any = None

    # --- trunk side ---------------------------------------------------------

    def recv_request(self, request: Any, transaction: Any) -> Any:
        """Terminate an INVITE arriving on the trunk and create the answering leg.

        Args:
            request: The parsed SIP request.
            transaction: The sippy server transaction of the request.

        Returns:
            The sippy callback triple ``(response, cancel_cb, noack_cb)``.
        """
        self.call_id = str(request.getHFBody("call-id"))
        self.trunk_peer = _source_peer(request)
        self.metrics.record_call_started()
        self.metrics.set_peer_status(f"{self.trunk_peer}:trunk", PeerStatus.REACHABLE)
        self._record(
            LogDirection.INBOUND,
            LEG_TRUNK,
            "INVITE",
            "invite received from the trunk",
            peer=self.trunk_peer,
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "invite received on the trunk",
            call_id=self.call_id,
            direction=LogDirection.INBOUND,
            peer=self.trunk_peer,
            method="INVITE",
        )
        self.uaA = UA(self.global_config, self.recv_event)
        self.uaA.local_ua = str(self.global_config.get("_sip_uaname", ""))
        self.uaA.lContact = _local_contact(self.global_config)
        with _fraud_sip_identity(self.global_config):
            return self.uaA.recvRequest(request, transaction)

    def capture_trunk_request(self, request: Any) -> None:
        """Remember the trunk INVITE, the source of the screening input.

        Args:
            request: The inbound INVITE.
        """
        self._trunk_request = request

    # --- sippy event hook ---------------------------------------------------

    def recv_event(self, event: Any, ua: Any) -> None:
        """Relay one call control event between the trunk leg and the next-hop leg.

        Args:
            event: A sippy ``CCEvent``.
            ua: The sippy UA the event came from.
        """
        if ua is self.uaA:
            self._relay_from_trunk(event)
            return
        if ua is not self.uaO:
            return
        self._relay_from_next_hop(event)

    def _relay_from_trunk(self, event: Any) -> None:
        """Handle an event raised by the answering (trunk) leg.

        ``uaO`` is ``None`` until the verdict allowed the call; for a rejected call it stays
        ``None`` and this method is the whole lifetime of the call.

        Args:
            event: A sippy ``CCEvent``.
        """
        method, summary = _describe_event(event)
        if self.uaO is None:
            if not isinstance(event, CCEventTry):
                # Nothing has been originated and the caller already gave up: there is
                # nothing to relay, so the call is torn down on the trunk leg only.
                self.uaA.recvEvent(CCEventDisconnect())
                return
            self.apply_call_policy(event)
            return
        self._record(
            LogDirection.INBOUND,
            LEG_TRUNK,
            method,
            f"{summary} on the trunk leg",
            peer=self.trunk_peer,
        )
        self.uaO.recvEvent(event)

    def _relay_from_next_hop(self, event: Any) -> None:
        """Handle an event raised by the originating (next-hop) leg.

        Args:
            event: A sippy ``CCEvent``.
        """
        method, summary = _describe_event(event)
        if isinstance(event, (CCEventRing, CCEventConnect)):
            self._cancel_no_answer_timer()
        self._record(
            LogDirection.INBOUND,
            LEG_NEXT_HOP,
            method,
            f"{summary} on the next-hop leg",
            peer=self._next_hop_peer(),
        )
        if isinstance(event, (CCEventFail, CCEventDisconnect)):
            self._cancel_no_answer_timer()
            self._record_disposition(event)
        if self.uaA is not None:
            self.uaA.recvEvent(event)
        if isinstance(event, (CCEventRing, CCEventConnect)) and method != "ACK":
            # The relay above makes the answering leg send the response on the trunk.
            self._record(
                LogDirection.OUTBOUND,
                LEG_TRUNK,
                method,
                f"{summary} relayed to the trunk leg",
                peer=self.trunk_peer,
            )

    # --- the verdict seam ---------------------------------------------------

    def apply_call_policy(self, event: Any) -> None:
        """Take the verdict for this call and act on it.

        This is the **single seam** of the anti-fraud AS, the mirror of the number
        translation seam in ``as_app``: the calling party is read off the captured trunk
        INVITE, combined with the process-level cross-call state and the block/allow lists,
        and handed to the pure engine. An allow relays the INVITE unchanged; a reject
        answers it on the trunk.

        Args:
            event: The ``CCEventTry`` raised by the answering leg.
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
        self._verdict = decision
        self._record_verdict(decision, signals, sip_608_declared)
        if decision.verdict is ScreeningVerdict.REJECT:
            self.caller_state.penalise(signals.calling_number)
            self._reject_on_trunk(decision, sip_608_declared)
            return
        self._originate_allowed(event)

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

    def _reject_on_trunk(self, decision: ScreeningDecision, sip_608_declared: bool) -> None:
        """Answer the trunk leg with ``608 Rejected`` — UAS only, no second leg.

        Unconditional in the sense of ADR-0007 decision 5: the UAC's ``Feature-Caps``
        declaration selects no status code, it only decides whether RFC 8688 section 3.4's
        announcement obligation was met. A rejected call whose INVITE did not declare
        ``sip.608`` is counted separately so that gap is observable.

        Args:
            decision: The rejecting verdict.
            sip_608_declared: Whether the INVITE declared ``sip.608``.
        """
        error = AsError(
            _error_code_for(decision.error_code),
            decision.reason,
            call_id=self.call_id,
            context={"screen_source": decision.source.value},
        )
        if not sip_608_declared:
            # RFC 8688 section 3.4: the call is answered 608 either way, but the
            # announcement obligation was not met. Counted **only** for screening-driven
            # rejects — a configuration failure is not a section 3.4 case and must not
            # inflate this counter.
            self.metrics.record_counter("reject.sip_608_undeclared")
        self._answer_trunk(
            error,
            screen_source=decision.source,
            list_entry=decision.list_entry,
            sip_608_declared=sip_608_declared,
        )

    def _answer_trunk(
        self,
        error: AsError,
        *,
        screen_source: ScreeningSource,
        list_entry: str | None,
        sip_608_declared: bool | None,
    ) -> None:
        """Emit a final answer on the trunk leg — the decision-free reject.

        Args:
            error: The error carrying the SIP status, the phrase and the internal code.
            screen_source: Signal that decided, for the trace.
            list_entry: Matched list entry identifier, when there is one.
            sip_608_declared: Whether the INVITE declared ``sip.608``; ``None`` when the AS
                did not get as far as screening (a configuration failure), in which case the
                field is omitted rather than reported as ``false``.
        """
        self._cancel_no_answer_timer()
        self.metrics.record_error(error.code.code)
        self.metrics.record_call_disposition(CallDisposition.REJECTED)
        attributes: dict[str, Any] = {
            "leg": LEG_TRUNK,
            "error_code": error.code.code,
            "screen_source": screen_source.value,
        }
        if list_entry:
            attributes["list_entry"] = list_entry
        declared_fields: dict[str, Any] = {}
        if sip_608_declared is not None:
            attributes["sip_608_declared"] = sip_608_declared
            declared_fields["sip_608_declared"] = sip_608_declared
        self.tracer.record(
            self.call_id,
            LogDirection.OUTBOUND,
            str(error.sip_status),
            f"{error.sip_status} {error.sip_phrase} answered on the trunk leg",
            peer=self.trunk_peer,
            attributes=attributes,
        )
        log_event(
            _LOGGER,
            logging.WARNING,
            "call rejected by screening",
            call_id=self.call_id,
            direction=LogDirection.OUTBOUND,
            peer=self.trunk_peer,
            method=str(error.sip_status),
            # ``error.as_log_fields()`` already carries ``screen_source`` through the error
            # context, so it is not repeated here (a duplicate keyword argument raises).
            **declared_fields,
            **error.as_log_fields(),
        )
        if self.uaA is not None:
            self.uaA.recvEvent(CCEventFail((error.sip_status, error.sip_phrase, None)))

    # --- the allow path -----------------------------------------------------

    def _originate_allowed(self, event: Any) -> None:
        """Relay the allowed INVITE towards the single configured next hop.

        What crosses the AS unchanged is exactly the **pass-through header set**
        (:data:`as_app.sip_adapter.PASSTHROUGH_HEADERS`) plus the SDP body; the Request-URI
        and the called number are not rewritten, everything else is regenerated by the stack
        or owned by the AS, and **no header is added** (ADR-0007 decision 6). The one
        exception is the outbound ``Call-ID``: the controller derives a fresh one rather
        than letting sippy copy the trunk value (``docs/architecture/lld.md`` section 2.3).
        ``Feature-Caps`` is **not** in that set, so the UAC's ``sip.608`` declaration does
        not reach the next hop — a registered gap, not a hidden one.

        Args:
            event: The ``CCEventTry`` raised by the answering leg.
        """
        from sippy.Time.Timeout import Timeout

        if self.next_hop is None:
            error = AsError(
                SkeletonErrorCode.CFG_MISSING,
                "FRAUD_SBC_PEER_ADDRESS is required: the AS must know its next hop",
                call_id=self.call_id,
            )
            self._answer_trunk(
                error,
                screen_source=ScreeningSource.NONE,
                list_entry=None,
                sip_608_declared=None,
            )
            return
        original = event.getData()
        # The second leg gets its own Call-ID: sippy regenerates ``From``, ``To`` and
        # ``CSeq`` for the outbound dialog, but copies a non-``None`` Call-ID verbatim
        # (``sippy/UacStateIdle.py``) and this AS runs a bare ``sippy.UA`` rather than
        # ``CCB2BUA`` (which would rewrite it itself, ``sippy/b2bua.py``). Derive a fresh
        # ``SipCallId`` from the trunk one with sippy's own ``-b2b_1`` suffix style; the
        # inbound object is never mutated because it is the trunk leg's dialog identity
        # (``docs/architecture/lld.md`` section 2.3). Every other element of the event,
        # the called number included, is passed through unchanged — screening does not
        # rewrite the Request-URI (ADR-0007 decision 6).
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
        self.uaO = UA(self.global_config, event_cb=self.recv_event, nh_address=self.next_hop)
        self.uaO.local_ua = str(self.global_config.get("_sip_uaname", ""))
        self.uaO.lContact = _local_contact(self.global_config)
        expire_seconds = float(
            self.global_config.get("_next_hop_expire_seconds", _DEFAULT_NEXT_HOP_EXPIRE)
        )
        self._no_answer_timer = Timeout(self._on_next_hop_no_answer, expire_seconds, 1)
        self.metrics.set_peer_status(f"{self._next_hop_peer()}", PeerStatus.REACHABLE)
        self._record(
            LogDirection.OUTBOUND,
            LEG_NEXT_HOP,
            "INVITE",
            "invite relayed towards the next hop",
            peer=self._next_hop_peer(),
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "invite relayed towards the next hop",
            call_id=self.call_id,
            direction=LogDirection.OUTBOUND,
            peer=self._next_hop_peer(),
            method="INVITE",
            verdict=ScreeningVerdict.ALLOW.value,
        )
        with _fraud_sip_identity(self.global_config):
            self.uaO.recvEvent(outbound_event)

    def _pass_through_headers(self, request: Any) -> tuple[Any, ...]:
        """Copy the pass-through headers of the trunk INVITE for the relayed INVITE.

        Args:
            request: The inbound INVITE, or ``None`` when it is not available.

        Returns:
            Copies of the headers listed in :data:`as_app.sip_adapter.PASSTHROUGH_HEADERS`,
            in wire order.
        """
        if request is None:
            return ()
        headers: list[Any] = []
        for name in PASSTHROUGH_HEADERS:
            for body in request.getHFBodys(name):
                headers.append(SipHeader(name=name, body=body.getCopy()))
        return tuple(headers)

    def _on_next_hop_no_answer(self) -> None:
        """Tear the relayed leg down when the next hop did not answer in time.

        The controller-owned timer injects a disconnect on the originating leg, which sippy
        turns into a failure event that :meth:`_relay_from_next_hop` forwards to the trunk.
        It is armed here so that it can be cancelled from :meth:`dispose` on the stop path
        (P8a lesson 5).
        """
        if self.uaO is None:
            return
        if self.uaA is not None and bool(self.uaA.isConnected()):
            return
        log_event(
            _LOGGER,
            logging.WARNING,
            "next hop did not answer in time",
            call_id=self.call_id,
            direction=LogDirection.INTERNAL,
            next_hop=self._next_hop_peer(),
            error_code=SkeletonErrorCode.PEER_UNREACHABLE.code,
        )
        self.uaO.disconnect()

    def _cancel_no_answer_timer(self) -> None:
        """Cancel the no-answer timer when the relayed leg has responded."""
        if self._no_answer_timer is not None:
            self._no_answer_timer.cancel()
            self._no_answer_timer = None

    def dispose(self) -> None:
        """Drop the controller-owned timers so they cannot outlive the stack.

        A call still waiting for its next hop when the process stops would otherwise have
        its timer fire into a transaction manager that has already been shut down, whose
        ``global_config['_sip_tm']`` is ``None`` (P8a).
        """
        self._cancel_no_answer_timer()

    def _record_disposition(self, event: Any) -> None:
        """Count the final outcome of the call.

        Args:
            event: The ``CCEventFail`` or ``CCEventDisconnect`` that ended the call.
        """
        if isinstance(event, CCEventFail):
            disposition = CallDisposition.FAILED
        elif self.uaA is not None and bool(self.uaA.isConnected()):
            disposition = CallDisposition.COMPLETED
        else:
            disposition = CallDisposition.ABANDONED
        self.metrics.record_call_disposition(disposition)
        log_event(
            _LOGGER,
            logging.INFO,
            "call finished",
            call_id=self.call_id,
            direction=LogDirection.INTERNAL,
            disposition=disposition.value,
        )

    def _record(
        self,
        direction: str,
        leg: str,
        method: str,
        summary: str,
        *,
        peer: str = "-",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Write one event into the Call-ID keyed trace and the debug log.

        Args:
            direction: One of :class:`LogDirection` values.
            leg: ``trunk`` or ``next_hop``.
            method: SIP method or status code.
            summary: Short human readable description.
            peer: Remote address of the message.
            attributes: Additional structured details.
        """
        merged = {"leg": leg}
        merged.update(attributes or {})
        self.tracer.record(self.call_id, direction, method, summary, peer=peer, attributes=merged)
        log_event(
            _LOGGER,
            logging.DEBUG,
            summary,
            call_id=self.call_id,
            direction=direction,
            peer=peer,
            method=method,
            leg=leg,
        )

    def _next_hop_peer(self) -> str:
        """Render the next hop as ``address:port`` for log and trace fields.

        Returns:
            The next hop address, or ``"-"`` when none is configured.
        """
        if self.next_hop is None:
            return "-"
        return f"{self.next_hop[0]}:{self.next_hop[1]}"


class FraudCallMap:
    """Process-wide entry point for requests arriving on the anti-fraud trunk.

    The trunk is untrusted: a request from an address outside ``FRAUD_ALLOWED_PEERS`` is
    answered with ``403`` and ``AS-PEER-001`` before any call state is created
    (``AGENT.md`` section 9). Everything else is handed to a fresh
    :class:`FraudCallController`, which owns the verdict for that one call.

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
    ) -> None:
        """Create the trunk call map.

        Args:
            global_config: sippy global configuration; ``nh_addr`` carries the next hop.
            screening_data: Holds and reloads the active screening data.
            caller_state: The process-level cross-call state.
            allowed_peers: Source addresses accepted on the trunk.
            metrics: Counter registry; the process-wide one is used when omitted.
            tracer: Trace recorder; the process-wide one is used when omitted.
        """
        self.global_config = global_config
        self.screening_data = screening_data
        self.caller_state = caller_state
        self.allowed_peers = allowed_peers
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()
        self.controllers: list[FraudCallController] = []

    def recv_request(self, request: Any, transaction: Any) -> Any:
        """Handle a request arriving on the anti-fraud trunk.

        Args:
            request: The parsed SIP request.
            transaction: The sippy server transaction of the request.

        Returns:
            The sippy callback triple ``(response, cancel_cb, noack_cb)``.
        """
        source = _source_address(request)
        if not is_allowed_peer(source, list(self.allowed_peers)):
            return self._reject_peer(request, source, _source_peer(request))
        if request.getHFBody("to").getTag() is not None:
            return (request.genResponse(481, "Call Leg/Transaction Does Not Exist"), None, None)
        if request.getMethod() != "INVITE":
            return (request.genResponse(501, "Not Implemented"), None, None)
        controller = self._new_controller()
        controller.capture_trunk_request(request)
        return controller.recv_request(request, transaction)

    def _new_controller(self) -> FraudCallController:
        """Create a call controller bound to this process configuration.

        Returns:
            A controller wired to the trunk call map's stack, state and next hop.
        """
        next_hop: tuple[str, int] | None = None
        configured_hop = self.global_config.get("nh_addr")
        if configured_hop is not None:
            next_hop = (str(configured_hop[0]), int(configured_hop[1]))
        controller = FraudCallController(
            self.screening_data,
            self.caller_state,
            metrics=self.metrics,
            tracer=self.tracer,
            global_config=self.global_config,
            next_hop=next_hop,
        )
        self.controllers.append(controller)
        return controller

    def dispose(self) -> None:
        """Cancel the timers of every call this map still knows about.

        Called when the signalling stack stops: a controller still waiting for its next hop
        owns a loop timer that would otherwise fire into a transaction manager that has
        already been shut down (P8a lesson 5).
        """
        for controller in self.controllers:
            controller.dispose()

    def _reject_peer(self, request: Any, source: str, peer: str) -> Any:
        """Answer a request from an address that is not an allowed trunk peer.

        Args:
            request: The parsed SIP request.
            source: Source address of the request, as checked against the allowlist.
            peer: Source address and port, for the ``peer`` log and trace field.

        Returns:
            The sippy callback triple carrying the ``403`` response.
        """
        error = AsError(
            SkeletonErrorCode.PEER_NOT_ALLOWED,
            f"source address {source} is not an allowed trunk peer",
            context={"source": source, "sip_method": str(request.getMethod())},
        )
        call_id = str(request.getHFBody("call-id"))
        self.metrics.record_error(SkeletonErrorCode.PEER_NOT_ALLOWED.code)
        self.tracer.record(
            call_id,
            LogDirection.INBOUND,
            str(request.getMethod()),
            "403 forbidden: source is not an allowed trunk peer",
            peer=peer,
            attributes={"leg": LEG_TRUNK},
        )
        log_event(
            _LOGGER,
            logging.WARNING,
            "request rejected: source address is not an allowed trunk peer",
            call_id=call_id,
            direction=LogDirection.INBOUND,
            peer=peer,
            method=str(request.getMethod()),
            **error.as_log_fields(),
        )
        return (request.genResponse(403, "Forbidden"), None, None)
