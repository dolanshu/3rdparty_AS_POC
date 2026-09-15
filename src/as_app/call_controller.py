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

sippy calls ``recv_event(event, ua)`` on the controller; the controller relays events
between the answering UA (trunk leg, ``uaA``) and the originating UA (next-hop leg,
``uaO``) and applies the routing decision where the event passes between them
(ADR-0001).

This class stays thin: the decision itself is a pure function in
:mod:`as_app.routing.engine`, so the policy is testable without a stack
(``AGENT.md`` section 5).

**Translation seam.** :meth:`CallController.apply_call_policy` is the single place where
an inbound INVITE is modified before it leaves on the outbound leg. In **M1** it relays
the call verbatim and records that it did so; **M2** replaces its body with a call to
:func:`as_app.routing.engine.decide` and rewrites the called number. No other place in
the signalling path may touch the number — that is what keeps the seam honest.

**Peer control.** :class:`TrunkCallMap` is the process-wide entry point for requests
arriving on the trunk. It rejects sources outside ``ALLOWED_PEERS`` with ``403`` and
``AS-PEER-001`` before any call state is created (``AGENT.md`` section 9).
"""

from __future__ import annotations

import logging
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
from sippy.SipConf import SipConf
from sippy.SipContact import SipContact
from sippy.SipHeader import SipHeader
from sippy.SipURL import SipURL
from sippy.UA import UA

from as_app.errors import AsError, AsErrorCode
from as_app.observability.logging import LogDirection, get_logger, log_event
from as_app.observability.metrics import (
    CallDisposition,
    MetricsRegistry,
    PeerStatus,
    get_metrics_registry,
)
from as_app.observability.tracing import TraceRecorder, get_trace_recorder
from as_app.routing.engine import Disposition, RoutingDecision, decide
from as_app.routing.rules import NextHop, RuleSetStore
from as_app.sip_adapter import PASSTHROUGH_HEADERS, extract_called_number, is_allowed_peer

__all__ = ["CallController", "TrunkCallMap"]

_LOGGER = get_logger(__name__)

#: Leg names used in the ``leg`` trace attribute: ``trunk`` is the leg towards the
#: S-SBC, ``next_hop`` the leg the AS originates (see :class:`as_app.sip_adapter.CallLeg`).
LEG_TRUNK = "trunk"
LEG_NEXT_HOP = "next_hop"

#: How many seconds the outbound INVITE is given to see any response before the
#: originating leg is torn down and the next failover hop is tried. Tuned for the
#: loopback POC; a real deployment sets this per next hop or via configuration.
_DEFAULT_NEXT_HOP_EXPIRE = 3.0


@contextmanager
def _as_sip_identity(global_config: dict[str, Any]) -> Iterator[None]:
    """Pin the process-wide sippy identity to the AS while a message is generated.

    ``SipConf`` is a module-level singleton and sippy reads it while it builds a ``Via``
    or a default ``Contact``. The AS and the mock S-SBC are separate processes in
    production (ADR-0002) but share one interpreter in the integration and e2e tests, so
    the AS pins its own address, port and user agent name for the duration of one
    synchronous message generation and puts the previous values back afterwards.

    Args:
        global_config: sippy global configuration of the AS process.

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
    """Build the Contact header the AS puts on its own messages.

    Args:
        global_config: sippy global configuration of the AS process.

    Returns:
        A ``SipContact`` pointing at the trunk address and port of the AS.
    """
    url = SipURL(
        host=str(global_config.get("_sip_address", SipConf.my_address)),
        port=int(global_config.get("_sip_port", SipConf.my_port)),
        transport=SipConf.my_transport,
    )
    return SipContact(address=SipAddress(url=url))


def _source_address(request: Any) -> str:
    """Return the source IP address of a SIP message received on the trunk.

    This is the value the peer allowlist compares against (``AGENT.md`` section 9); the
    ``peer`` log field carries the port as well, see :func:`_source_peer`.

    Args:
        request: A parsed sippy ``SipRequest``.

    Returns:
        The source address as a string, or ``"-"`` when the stack did not record one.
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
        The remote address and port, or ``"-"`` when the stack did not record one.
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


class CallController:
    """One B2BUA call: relays events between the trunk leg and the next-hop leg.

    Attributes:
        rule_set_store: Source of the currently active rule set (hot reload, ADR-0004).
        metrics: Counter registry.
        tracer: Per-Call-ID trace recorder.
        global_config: sippy global configuration of the AS process.
        next_hop: ``(address, port)`` of the S-SBC the outbound INVITE is sent to.
        call_id: SIP Call-ID of the call, known once the INVITE has been terminated.
        uaA: Answering UA, the leg towards the S-SBC.
        uaO: Originating UA, the leg towards the next hop.
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
        self.rule_set_store = rule_set_store
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()
        self.global_config: dict[str, Any] = dict(global_config or {})
        self.next_hop = next_hop
        self.call_id: str = "-"
        self.trunk_peer: str = "-"
        self.uaA: Any = None
        self.uaO: Any = None
        self._trunk_request: Any = None
        # M2 translation seam state: the routing decision and the next hops still
        # available for failover. ``_pending_event`` holds the translated ``CCEventTry``
        # so a failover attempt can re-originate it towards a different next hop.
        self._decision: RoutingDecision | None = None
        self._pending_event: Any = None
        self._failover_hops: list[NextHop] = []
        self._serving_hop: NextHop | None = None
        self._no_answer_timer: Any = None

    # --- trunk side ---------------------------------------------------------

    def recv_request(self, request: Any, transaction: Any) -> Any:
        """Terminate an INVITE arriving on the trunk and create the answering leg.

        Args:
            request: The parsed SIP request.
            transaction: The sippy server transaction of the request.

        Returns:
            The sippy callback triple ``(response, cancel_cb, noack_cb)``.

        Raises:
            AsError: ``AS-PEER-003`` when the Request-URI carries no called number.
        """
        self.call_id = str(request.getHFBody("call-id"))
        self.trunk_peer = _source_peer(request)
        called_number = extract_called_number(str(request.getRURI()))
        self.metrics.record_call_started()
        self.metrics.set_peer_status(f"{self.trunk_peer}:trunk", PeerStatus.REACHABLE)
        self._record(
            LogDirection.INBOUND,
            LEG_TRUNK,
            "INVITE",
            "invite received from the trunk",
            peer=self.trunk_peer,
            attributes={"called_number": called_number},
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "invite received on the trunk",
            call_id=self.call_id,
            direction=LogDirection.INBOUND,
            peer=self.trunk_peer,
            method="INVITE",
            called_number=called_number,
        )
        self.uaA = UA(self.global_config, self.recv_event)
        self.uaA.local_ua = str(self.global_config.get("_sip_uaname", ""))
        self.uaA.lContact = _local_contact(self.global_config)
        with _as_sip_identity(self.global_config):
            return self.uaA.recvRequest(request, transaction)

    # --- sippy event hook ---------------------------------------------------

    def recv_event(self, event: Any, ua: Any) -> None:
        """Relay one call control event between the two legs.

        A ``CCEvent`` raised by a previous originating leg that has already been
        replaced by a failover attempt is ignored: its expiry timer fires after the
        controller has moved on, and relaying it would tear the new leg down.

        Args:
            event: A sippy ``CCEvent``.
            ua: The sippy UA the event came from.
        """
        if ua is self.uaA:
            self._relay_from_trunk(event)
            return
        if ua is not self.uaO:
            return  # stale event from a UA that has been replaced by failover
        self._relay_from_next_hop(event)

    def _relay_from_trunk(self, event: Any) -> None:
        """Handle an event raised by the answering (trunk) leg.

        Args:
            event: A sippy ``CCEvent``.
        """
        method, summary = _describe_event(event)
        if self.uaO is None:
            if not isinstance(event, CCEventTry):
                # Nothing has been originated yet and the caller already gave up: there
                # is nothing to relay, so the call is torn down on the trunk leg only.
                self.uaA.recvEvent(CCEventDisconnect())
                return
            self._originate_outbound_leg(event)
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

        On a failure from the serving next hop, the next failover hop is tried before
        the failure is relayed to the trunk leg (``AS-PEER-002`` / ``503`` semantics).
        When no failover hop remains, the failure is relayed so the caller sees it.

        A ``CCEventFail`` or a pre-connect ``CCEventDisconnect`` from the originating
        leg (the no-answer timer calls ``disconnect()``) is treated as a failover
        trigger when a hop remains.

        Args:
            event: A sippy ``CCEvent``.
        """
        method, summary = _describe_event(event)
        if isinstance(event, (CCEventRing, CCEventConnect)):
            self._cancel_no_answer_timer()
        connected = self.uaA is not None and bool(self.uaA.isConnected())
        if (
            isinstance(event, (CCEventFail, CCEventDisconnect))
            and not connected
            and self._try_failover()
        ):
            self._cancel_no_answer_timer()
            self._record(
                LogDirection.INBOUND,
                LEG_NEXT_HOP,
                method,
                f"{summary} on the next-hop leg; trying failover",
                peer=self._next_hop_peer(),
                attributes={
                    "failed_hop": self._serving_hop.name if self._serving_hop else "",
                },
            )
            return
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

    def _try_failover(self) -> bool:
        """Try the next failover hop when the serving hop failed.

        Returns:
            ``True`` when a failover attempt was started, ``False`` when no hop remains
            and the caller must be told the call failed.
        """
        if not self._failover_hops:
            return False
        failed = self._serving_hop
        self.metrics.set_peer_status(
            f"{failed.name}:{failed.address}:{failed.port}" if failed else "next_hop",
            PeerStatus.UNREACHABLE,
        )
        next_hop = self._failover_hops.pop(0)
        self.uaO = None
        log_event(
            _LOGGER,
            logging.WARNING,
            "next hop failed; trying failover hop",
            call_id=self.call_id,
            direction=LogDirection.INTERNAL,
            failed_hop=failed.name if failed else "",
            failover_hop=next_hop.name,
            error_code=AsErrorCode.PEER_UNREACHABLE.code,
        )
        self._originate_towards(next_hop)
        return True

    def _originate_outbound_leg(self, event: Any) -> None:
        """Apply the routing decision and originate the outbound INVITE.

        The translation seam (:meth:`apply_call_policy`) decides the fate of the call:
        route, reject (``603``) or no-match (``404``). On route, the first next hop of
        the decision is used; the remaining hops stay available for failover
        (:meth:`_relay_from_next_hop`). On a rejection, the trunk leg is answered with
        the SIP status the decision carries and no outbound leg is created.

        Args:
            event: The ``CCEventTry`` raised by the answering leg.

        Raises:
            AsError: ``AS-CFG-001`` when no next hop is configured and the decision has
                no next hops either; ``AS-ROUTE-003`` when the decision carries no
                routable next hop.
        """
        try:
            outbound_event, hops = self.apply_call_policy(event)
        except AsError as reject_error:
            self._reject_on_trunk(reject_error)
            return
        if not hops:
            no_hop_error = AsError(
                AsErrorCode.ROUTE_NO_NEXT_HOP,
                f"rule {self._decision.rule_id if self._decision else '-'} selected no next hop",
                call_id=self.call_id,
            )
            self._reject_on_trunk(no_hop_error)
            return
        self._pending_event = outbound_event
        self._failover_hops = list(hops)
        self._originate_towards(self._failover_hops.pop(0))

    def _originate_towards(self, hop: NextHop) -> None:
        """Originate the outbound INVITE towards one next hop.

        A controller-owned timer (``Timeout``) watches for a no-answer condition: when
        it fires before the leg connected, the controller injects a ``CCEventFail`` on
        the originating leg, which sippy turns into a transaction failure and which the
        failover path in :meth:`_relay_from_next_hop` turns into an attempt at the next
        hop. This is deliberately not sippy's ``expire_time``: that timer is anchored to
        the INVITE event ``rtime`` and would fire immediately on a failover attempt
        whose pending event carries the original timestamp.

        Args:
            hop: Next hop to send the INVITE to.
        """
        from sippy.Time.Timeout import Timeout

        self._serving_hop = hop
        self.next_hop = (hop.address, hop.port)
        self.uaO = UA(self.global_config, event_cb=self.recv_event, nh_address=self.next_hop)
        self.uaO.local_ua = str(self.global_config.get("_sip_uaname", ""))
        self.uaO.lContact = _local_contact(self.global_config)
        expire_seconds = float(
            self.global_config.get("_next_hop_expire_seconds", _DEFAULT_NEXT_HOP_EXPIRE)
        )
        self._no_answer_timer = Timeout(self._on_next_hop_no_answer, expire_seconds, 1)
        called_number = str(self._pending_event.getData()[2])
        self.metrics.set_peer_status(f"{hop.name}:{hop.address}:{hop.port}", PeerStatus.REACHABLE)
        self._record(
            LogDirection.OUTBOUND,
            LEG_NEXT_HOP,
            "INVITE",
            "invite originated towards the next hop",
            peer=self._next_hop_peer(),
            attributes={"called_number": called_number, "next_hop": hop.name},
        )
        log_event(
            _LOGGER,
            logging.INFO,
            "invite originated towards the next hop",
            call_id=self.call_id,
            direction=LogDirection.OUTBOUND,
            peer=self._next_hop_peer(),
            method="INVITE",
            called_number=called_number,
            next_hop=hop.name,
            rule_id=self._decision.rule_id if self._decision else "",
        )
        with _as_sip_identity(self.global_config):
            self.uaO.recvEvent(self._pending_event)

    def _on_next_hop_no_answer(self) -> None:
        """Tear the serving next hop down when it did not answer in time.

        The controller-owned no-answer timer fires before any response arrived from the
        serving hop. Injecting a ``CCEventFail`` makes sippy cancel the outstanding
        transaction and raise the fail event on the originating leg, which the failover
        path turns into an attempt at the next hop.
        """
        if self.uaO is None:
            return
        connected = self.uaA is not None and bool(self.uaA.isConnected())
        if connected:
            return
        log_event(
            _LOGGER,
            logging.WARNING,
            "next hop did not answer in time",
            call_id=self.call_id,
            direction=LogDirection.INTERNAL,
            next_hop=self._serving_hop.name if self._serving_hop else "",
            error_code=AsErrorCode.PEER_UNREACHABLE.code,
        )
        # ``disconnect()`` enqueues a ``CCEventDisconnect`` and drives the state
        # transition so sippy emits the event to the event callback, which the failover
        # path in :meth:`_relay_from_next_hop` turns into an attempt at the next hop.
        self.uaO.disconnect()

    def _cancel_no_answer_timer(self) -> None:
        """Cancel the no-answer timer when the serving hop responded."""
        if self._no_answer_timer is not None:
            self._no_answer_timer.cancel()
            self._no_answer_timer = None

    def _reject_on_trunk(self, error: AsError) -> None:
        """Answer the trunk leg with the SIP status the error carries.

        Used by the translation seam when the routing decision is a rejection
        (``404`` / ``603`` / ``480`` / ``500``) so the caller sees the right status and
        the error code is counted and traced.

        Args:
            error: The :class:`AsError` built from the routing decision.
        """
        self._cancel_no_answer_timer()
        decision = self._decision
        assert decision is not None, "rejection requires a routing decision"
        # The error code is already counted in :meth:`route_call`; only the disposition
        # is recorded here so the counters do not double-count the same failure.
        self.metrics.record_call_disposition(self.disposition_for(decision))
        self.tracer.record(
            self.call_id,
            LogDirection.OUTBOUND,
            str(error.sip_status),
            f"{error.sip_status} {error.sip_phrase} relayed to the trunk leg",
            peer=self.trunk_peer,
            rule_id=decision.rule_id,
            attributes={
                "leg": LEG_TRUNK,
                "error_code": error.code.code,
                "rule_id": decision.rule_id or "",
            },
        )
        log_event(
            _LOGGER,
            logging.WARNING,
            "call rejected by routing policy",
            call_id=self.call_id,
            direction=LogDirection.OUTBOUND,
            peer=self.trunk_peer,
            method=str(error.sip_status),
            **error.as_log_fields(),
        )
        if self.uaA is not None:
            self.uaA.recvEvent(CCEventFail((error.sip_status, error.sip_phrase, None)))

    # --- the translation seam -----------------------------------------------

    def apply_call_policy(self, event: Any) -> tuple[Any, list[NextHop]]:
        """Apply the AS policies to an inbound INVITE before it leaves the AS.

        This is the **single seam** where an inbound INVITE is modified before it leaves
        the AS (``AGENT.md`` section 1, ``docs/architecture/lld.md`` section 3.3). It
        calls :func:`as_app.routing.engine.decide` with the called number, records the
        decision, and either:

        - returns the ``CCEventTry`` rebuilt with the translated called number plus the
          ordered next hops to try, or
        - raises :class:`AsError` carrying the SIP status and the internal error code
          of the rejection (``404`` / ``603`` / ``480`` / ``500``).

        SDP and the pass-through headers still pass through verbatim (M1 rule,
        unchanged); only the called number and the Request-URI host (the next hop) are
        rewritten.

        Args:
            event: The ``CCEventTry`` raised by the answering leg.

        Returns:
            The translated event to hand to the originating leg, and the next hops to
            try in order.

        Raises:
            AsError: When the decision is not routable, carrying the matching
                ``AS-ROUTE-*`` code.
        """
        original = event.getData()
        called_number = str(original[2])
        decision = self.route_call(self.call_id, called_number)
        self._decision = decision
        if decision.disposition is not Disposition.ROUTE:
            raise self.reject_error(decision, self.call_id)
        translated = decision.translated_number or called_number
        rebuilt = CCEventTry(
            (
                original[0],
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
        return rebuilt, list(decision.next_hops)

    def _pass_through_headers(self, request: Any) -> tuple[Any, ...]:
        """Copy the pass-through headers of the trunk INVITE for the outbound INVITE.

        Args:
            request: The inbound INVITE, or ``None`` when it is not available.

        Returns:
            Copies of the headers listed in
            :data:`as_app.sip_adapter.PASSTHROUGH_HEADERS`, in wire order.
        """
        if request is None:
            return ()
        headers: list[Any] = []
        for name in PASSTHROUGH_HEADERS:
            for body in request.getHFBodys(name):
                headers.append(SipHeader(name=name, body=body.getCopy()))
        return tuple(headers)

    def capture_trunk_request(self, request: Any) -> None:
        """Remember the trunk INVITE so its headers can be copied to the outbound leg.

        Args:
            request: The inbound INVITE.
        """
        self._trunk_request = request

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
        """Write one event into the Call-ID keyed trace.

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


class TrunkCallMap:
    """Process-wide entry point for requests arriving on the SIP trunk.

    The trunk is untrusted: a request from an address outside ``ALLOWED_PEERS`` is
    answered with ``403`` and ``AS-PEER-001`` before any call state is created
    (``AGENT.md`` section 9). Everything else is handed to a fresh
    :class:`CallController`, which owns the two legs of that one call.

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
        self.global_config = global_config
        self.rule_set_store = rule_set_store
        self.allowed_peers = allowed_peers
        self.metrics = metrics or get_metrics_registry()
        self.tracer = tracer or get_trace_recorder()
        self.controllers: list[CallController] = []

    def recv_request(self, request: Any, transaction: Any) -> Any:
        """Handle a request arriving on the trunk.

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

    def _new_controller(self) -> CallController:
        """Create a call controller bound to this process configuration.

        Returns:
            A controller wired to the trunk call map's stack and next hop.
        """
        next_hop: tuple[str, int] | None = None
        configured_hop = self.global_config.get("nh_addr")
        if configured_hop is not None:
            next_hop = (str(configured_hop[0]), int(configured_hop[1]))
        controller = CallController(
            self.rule_set_store,
            self.metrics,
            self.tracer,
            global_config=self.global_config,
            next_hop=next_hop,
        )
        self.controllers.append(controller)
        return controller

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
            AsErrorCode.PEER_NOT_ALLOWED,
            f"source address {source} is not an allowed trunk peer",
            context={"source": source, "sip_method": str(request.getMethod())},
        )
        call_id = str(request.getHFBody("call-id"))
        self.metrics.record_error(AsErrorCode.PEER_NOT_ALLOWED.code)
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
