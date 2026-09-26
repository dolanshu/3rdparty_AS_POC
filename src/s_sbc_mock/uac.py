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

"""Trunk-side of the mock S-SBC: forwards the operator INVITE towards the third-party AS.

Neither the S-CSCF nor the S-SBC is a B2BUA. In production an iFC match at the S-CSCF
hands the session to the operator S-SBC, which forwards the INVITE over the SIP trunk to
the third-party AS. The AS terminates that leg as a **UAS** on ``SIP_LISTEN_PORT`` (5060
by default). This mock side plays that **forwarded trunk INVITE** only: it is not the AS
and it is not the core network.

The INVITE carries a ``Route`` set pointing back at the S-SBC return interface so the AS
can originate the translated INVITE towards the same S-SBC (RFC 3261 top Route), not
directly towards the IMS core. Driven by :class:`CallScenario` data; built on sippy
(ADR-0005).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sippy.CCEvents import (
    CCEventConnect,
    CCEventDisconnect,
    CCEventFail,
    CCEventRing,
    CCEventTry,
)
from sippy.MsgBody import MsgBody
from sippy.SipAddress import SipAddress
from sippy.SipConf import SipConf
from sippy.SipContact import SipContact
from sippy.SipHeader import SipHeader
from sippy.SipLogger import SipLogger
from sippy.SipURL import SipURL
from sippy.Time.Timeout import Timeout
from sippy.UA import UA

__all__ = [
    "CallScenario",
    "CallOutcome",
    "DEFAULT_SDP_OFFER",
    "FEATURE_CAPS_608",
    "IMS_DOMAIN",
    "SIP_USER_AGENT_NAME",
    "TrunkUac",
]

_LOGGER = logging.getLogger(__name__)

#: User agent name the mock reports on the trunk.
SIP_USER_AGENT_NAME = "3rd-party AS POC mock S-SBC"

#: ``Feature-Caps`` the UAC declares so the anti-fraud AS may answer with ``608 Rejected``
#: without playing an announcement. RFC 8688 section 3.4 requires the announcement only
#: when the UAC has *not* declared ``sip.608``; declaring it keeps the signalling-only AS
#: media-free (``docs/phase2-plan.md`` decision D5, ADR-0006). The header is not one sippy
#: has a dedicated class for, so it is rendered by the generic header class and its on-wire
#: spelling is asserted by the integration tests, not assumed.
FEATURE_CAPS_608 = "Feature-Caps: *;+sip.608"

#: Documentation-only IMS domain used in the mock identities (RFC 2606, RFC 6761).
IMS_DOMAIN = "ims.example.invalid"

#: A plain G.711 offer, realistic enough to prove that the SDP body survives the B2BUA
#: unchanged. The address is a documentation range address (RFC 5737).
DEFAULT_SDP_OFFER = "\r\n".join(
    [
        "v=0",
        "o=- 4101 4101 IN IP4 192.0.2.10",
        "s=3rd-party AS POC call",
        "c=IN IP4 192.0.2.10",
        "t=0 0",
        "m=audio 40000 RTP/AVP 0 8 101",
        "a=rtpmap:0 PCMU/8000",
        "a=rtpmap:8 PCMA/8000",
        "a=rtpmap:101 telephone-event/8000",
        "a=fmtp:101 0-15",
        "a=sendrecv",
        "",
    ]
)


@contextmanager
def _trunk_identity(global_config: dict[str, Any]) -> Iterator[None]:
    """Pin the process-wide sippy identity to this side while a message is generated.

    ``SipConf`` is a module-level singleton and sippy reads it while it builds a ``Via``
    or a default ``Contact``. The AS and the mock are separate processes in production
    (ADR-0002) but share one interpreter in the tests, so the mock pins its own identity
    for the duration of one synchronous message generation and restores the previous
    values afterwards.

    Args:
        global_config: sippy global configuration of this side.

    Yields:
        ``None``; the identity is in place for the body of the ``with`` block.
    """
    from sippy.SipConf import SipConf

    saved = (SipConf.my_address, SipConf.my_port, SipConf.my_uaname)
    SipConf.my_address = str(global_config.get("_sip_address", SipConf.my_address))
    SipConf.my_port = int(global_config.get("_sip_port", SipConf.my_port))
    SipConf.my_uaname = str(global_config.get("_sip_uaname", SipConf.my_uaname))
    try:
        yield
    finally:
        SipConf.my_address, SipConf.my_port, SipConf.my_uaname = saved


@dataclass(frozen=True)
class CallScenario:
    """One call the mock should place, expressed as data.

    Attributes:
        name: Identifier of the scenario, used in logs and acceptance evidence.
        calling_number: Calling party in E.164, sent as ``P-Asserted-Identity``.
        called_number: Called number in the format a real office would dial.
        expect_status: Status code the AS is expected to answer with.
        ring_seconds: Time between ``180 Ringing`` and ``200 OK``.
        talk_seconds: Time between ``200 OK`` and ``BYE``.
        abandon: Send ``CANCEL`` instead of completing the call.
        sdp_offer: SDP offer sent in the INVITE; pass-through is asserted on it.
    """

    name: str
    calling_number: str
    called_number: str
    expect_status: int = 200
    ring_seconds: float = 0.2
    talk_seconds: float = 0.2
    abandon: bool = False
    sdp_offer: str = DEFAULT_SDP_OFFER


@dataclass(frozen=True)
class CallOutcome:
    """What the UAC side observed for one placed call.

    Attributes:
        scenario_name: Identifier of the scenario that was placed.
        call_id: SIP Call-ID of the call.
        status: Final SIP status code seen by the caller, ``None`` when abandoned.
        released: Whether the call has been torn down (``BYE`` seen or call failed).
        cancelled: Whether this side sent a ``CANCEL``.
    """

    scenario_name: str
    call_id: str
    status: int | None = None
    released: bool = False
    cancelled: bool = False


class TrunkUac:
    """Originates calls towards the AS over the trunk.

    Attributes:
        as_address: Address of the AS.
        as_port: UDP port of the AS.
        local_address: Local address the mock sends from.
        local_port: Local UDP port of the mock.
        outcomes: One entry per placed call, in the order the calls were placed.
    """

    def __init__(
        self,
        as_address: str,
        as_port: int,
        *,
        local_address: str = "127.0.0.1",
        local_port: int = 15060,
        route_return_address: str | None = None,
        route_return_port: int | None = None,
    ) -> None:
        """Create the trunk-forwarding side of the mock S-SBC.

        Args:
            as_address: Address of the third-party AS trunk.
            as_port: UDP port of the AS trunk (``SIP_LISTEN_PORT``, default 5060).
            local_address: Local address the mock sends the forwarded INVITE from.
            local_port: Local UDP port of that forward (mock default 15060).
            route_return_address: Host in the ``Route`` set the S-SBC inserts; defaults to
                ``route_return_address`` / ``listen_port`` of the mock UAS side.
            route_return_port: Port in that ``Route`` set; defaults to the mock UAS listen
                port (15061 in the shipped port matrix).
        """
        self.as_address = as_address
        self.as_port = as_port
        self.local_address = local_address
        self.local_port = local_port
        self.route_return_address = route_return_address or local_address
        self.route_return_port = route_return_port if route_return_port is not None else 15061
        self.outcomes: list[CallOutcome] = []
        self.global_config: dict[str, Any] = {}

    def build_global_config(self, sip_logger: Any | None = None) -> dict[str, Any]:
        """Build the sippy global configuration of this side of the mock.

        Args:
            sip_logger: SIP message logger; a ``SipLogger`` is used when omitted.

        Returns:
            The global configuration dictionary sippy expects.
        """
        logger = sip_logger if sip_logger is not None else SipLogger("s-sbc-mock-uac")
        self.global_config = {
            "nh_addr": (self.as_address, self.as_port),
            "_sip_address": self.local_address,
            "_sip_port": self.local_port,
            "_sip_uaname": SIP_USER_AGENT_NAME,
            "_sip_logger": logger,
        }
        return self.global_config

    def place_call(self, scenario: CallScenario) -> str:
        """Place one call towards the AS.

        Args:
            scenario: The call to place.

        Returns:
            The Call-ID of the call, as generated by the stack.

        Raises:
            RuntimeError: When this side is not bound to a transaction manager yet.
        """
        if self.global_config.get("_sip_tm") is None:
            raise RuntimeError(
                "TrunkUac is not bound: build_global_config() and the stack start are required"
            )
        event = CCEventTry(
            (
                None,
                scenario.calling_number,
                scenario.called_number,
                MsgBody(content=scenario.sdp_offer),
                None,
                None,
            )
        )
        event.extra_headers = self._isc_headers(scenario)
        ua = UA(
            self.global_config,
            self._event_handler(scenario),
            nh_address=(self.as_address, self.as_port),
            nh_transport=SipConf.my_transport,
        )
        ua.lContact = SipContact(
            address=SipAddress(
                url=SipURL(
                    host=self.local_address, port=self.local_port, transport=SipConf.my_transport
                )
            )
        )
        ua.local_ua = str(self.global_config.get("_sip_uaname", ""))
        with _trunk_identity(self.global_config):
            ua.recvEvent(event)
        call_id = str(ua.cId)
        self.outcomes.append(CallOutcome(scenario_name=scenario.name, call_id=call_id))
        _LOGGER.info(
            "trunk side placed call scenario=%s call_id=%s called=%s",
            scenario.name,
            call_id,
            scenario.called_number,
        )
        return call_id

    def send_trunk_invite(
        self,
        scenario: CallScenario,
        as_address: str,
        as_port: int,
        *,
        name_suffix: str = "",
    ) -> str:
        """Place one orchestrator-driven trunk INVITE towards an arbitrary AS hop.

        Used for iFC #1 and #2 in the chained topology (ADR-0014). Unlike
        :meth:`place_call`, the next hop is explicit per call.

        Args:
            scenario: Call parameters and headers to send.
            as_address: Target AS listen address.
            as_port: Target AS listen port.
            name_suffix: Appended to the scenario name in logs and ICID.

        Returns:
            The Call-ID of the placed call.

        Raises:
            RuntimeError: When this side is not bound to a transaction manager yet.
        """
        if self.global_config.get("_sip_tm") is None:
            raise RuntimeError(
                "TrunkUac is not bound: build_global_config() and the stack start are required"
            )
        event = CCEventTry(
            (
                None,
                scenario.calling_number,
                scenario.called_number,
                MsgBody(content=scenario.sdp_offer),
                None,
                None,
            )
        )
        event.extra_headers = self._isc_headers(scenario)
        ua = UA(
            self.global_config,
            self._event_handler(scenario),
            nh_address=(as_address, as_port),
            nh_transport=SipConf.my_transport,
        )
        ua.lContact = SipContact(
            address=SipAddress(
                url=SipURL(
                    host=self.local_address, port=self.local_port, transport=SipConf.my_transport
                )
            )
        )
        ua.local_ua = str(self.global_config.get("_sip_uaname", ""))
        with _trunk_identity(self.global_config):
            ua.recvEvent(event)
        call_id = str(ua.cId)
        outcome_name = f"{scenario.name}{name_suffix}" if name_suffix else scenario.name
        self.outcomes.append(CallOutcome(scenario_name=outcome_name, call_id=call_id))
        _LOGGER.info(
            "trunk side sent orchestrated INVITE scenario=%s call_id=%s target=%s:%d",
            outcome_name,
            call_id,
            as_address,
            as_port,
        )
        return call_id

    def outcome_for(self, call_id: str) -> CallOutcome | None:
        """Return the observed outcome of one placed call.

        Args:
            call_id: SIP Call-ID of the call.

        Returns:
            The outcome, or ``None`` when the Call-ID is unknown.
        """
        for outcome in self.outcomes:
            if outcome.call_id == call_id:
                return outcome
        return None

    def _event_handler(self, scenario: CallScenario) -> Any:
        """Build the sippy event callback for one call.

        Args:
            scenario: The scenario the callback belongs to.

        Returns:
            A callable ``(event, ua)`` sippy can invoke.
        """

        def handler(event: Any, ua: Any) -> None:
            self._on_event(event, ua, scenario)

        return handler

    def _isc_headers(self, scenario: CallScenario) -> tuple[Any, ...]:
        """Build the ISC-flavoured context headers a triggered INVITE carries.

        Args:
            scenario: The call to place.

        Returns:
            The extra headers to append to the INVITE.
        """
        return (
            SipHeader(
                s=(
                    "Route: "
                    f"<sip:{self.route_return_address}:{self.route_return_port};lr>"
                )
            ),
            SipHeader(s=f"P-Asserted-Identity: <sip:{scenario.calling_number}@{IMS_DOMAIN}>"),
            SipHeader(
                s=(
                    f"P-Charging-Vector: icid-value=poc-{scenario.name}"
                    ";icid-generated-at=ims.example.invalid"
                )
            ),
            SipHeader(s=f"P-Visited-Network-ID: {IMS_DOMAIN}"),
            SipHeader(s="Privacy: none"),
            SipHeader(s=f"Subject: {scenario.name}"),
            SipHeader(s=f"Organization: {scenario.name}"),
            SipHeader(s="Priority: normal"),
            # Declares 608 support so the AS may reject without an announcement (D5).
            SipHeader(s=FEATURE_CAPS_608),
        )

    def _on_event(self, event: Any, ua: Any, scenario: CallScenario) -> None:
        """Record what the caller observes, and abandon the call when asked to.

        Args:
            event: A sippy ``CCEvent``.
            ua: The sippy UA the event came from.
            scenario: The scenario the call belongs to.
        """
        call_id = str(ua.cId)
        if isinstance(event, CCEventRing):
            _LOGGER.info("trunk side received %s for call_id=%s", event.getData(), call_id)
            if scenario.abandon:
                Timeout(self._abandon, 0.05, 1, ua, call_id)
            return
        if isinstance(event, CCEventConnect):
            self._update(call_id, status=_status_of(event))
            return
        if isinstance(event, CCEventFail):
            self._update(call_id, status=_status_of(event), released=True)
            return
        if isinstance(event, CCEventDisconnect):
            self._update(call_id, released=True)
            return
        _LOGGER.debug("trunk side ignored %s", type(event).__name__)

    def _abandon(self, ua: Any, call_id: str) -> None:
        """Cancel an INVITE the caller no longer wants.

        Args:
            ua: The sippy UA of the call.
            call_id: SIP Call-ID of the call, recorded as cancelled.
        """
        _LOGGER.info("trunk side cancels call_id=%s", call_id)
        self._update(call_id, cancelled=True)
        ua.disconnect()

    def _update(
        self,
        call_id: str,
        *,
        status: int | None = None,
        released: bool | None = None,
        cancelled: bool | None = None,
    ) -> None:
        """Update the recorded outcome of a call.

        Args:
            call_id: SIP Call-ID of the call.
            status: Final status code to record, when known.
            released: Whether the call has been torn down.
            cancelled: Whether this side sent a ``CANCEL``.
        """
        for index, outcome in enumerate(self.outcomes):
            if outcome.call_id != call_id:
                continue
            self.outcomes[index] = CallOutcome(
                scenario_name=outcome.scenario_name,
                call_id=outcome.call_id,
                status=outcome.status if status is None else status,
                released=outcome.released if released is None else released,
                cancelled=outcome.cancelled if cancelled is None else cancelled,
            )
            return


def _status_of(event: Any) -> int | None:
    """Return the SIP status code carried by a connect or fail event.

    Args:
        event: A ``CCEventConnect`` or ``CCEventFail``.

    Returns:
        The status code, or ``None`` when the event carries none.
    """
    data = event.getData()
    if data is None:
        return None
    code = data[0]
    return code if isinstance(code, int) else None
