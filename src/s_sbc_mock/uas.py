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

"""Return side of the mock S-SBC: receives the AS-originated INVITE on the trunk.

The third-party AS is the only B2BUA: on the trunk leg it acts as **UAS**, on the outbound
leg as **UAC** with a fresh ``Call-ID``. The translated INVITE is sent back to the
operator S-SBC (top ``Route`` on the inbound INVITE), which relays it into the IMS — not
directly to the core. This mock binds the S-SBC **return** UDP port (15061 in the shipped
matrix) and answers the INVITE the way the POC needs for a completed call:
``100 Trying``, ``180 Ringing``, ``200 OK``, then ``BYE``.

``100 Trying`` is not sent explicitly: sippy emits it when the INVITE is terminated
(``UasStateIdle``).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ims_mock.callbacks import ReturnPassthroughCallback

from sippy.CCEvents import CCEventConnect, CCEventDisconnect, CCEventRing, CCEventTry
from sippy.SipAddress import SipAddress
from sippy.SipConf import SipConf
from sippy.SipContact import SipContact
from sippy.SipLogger import SipLogger
from sippy.SipURL import SipURL
from sippy.Time.Timeout import Timeout
from sippy.UA import UA

__all__ = ["CoreUas", "ReceivedInvite"]

_LOGGER = logging.getLogger(__name__)

#: User agent name the S-SBC return side reports on the trunk.
SIP_USER_AGENT_NAME = "3rd-party AS POC mock S-SBC"


@dataclass(frozen=True)
class ReceivedInvite:
    """An INVITE that reached the core side of the mock.

    Attributes:
        call_id: SIP Call-ID of the call.
        request_uri: Request-URI as received, after AS translation.
        called_number: User part of the Request-URI.
        calling_number: Calling party from ``P-Asserted-Identity``.
        body: SDP body, passed through by the AS.
        headers: Selected headers, captured verbatim for pass-through assertions.
    """

    call_id: str
    request_uri: str
    called_number: str
    calling_number: str | None = None
    body: str = ""
    headers: dict[str, str] | None = None


def _header_value(request: Any, name: str) -> str | None:
    """Return the verbatim value of a header, or ``None`` when it is absent.

    Args:
        request: A parsed sippy ``SipRequest``.
        name: Lower case header name.

    Returns:
        The header value as a string.
    """
    if request.countHFs(name) == 0:
        return None
    return str(request.getHFBody(name)).strip()


class CoreUas:
    """Answers the INVITE originated by the AS.

    Attributes:
        listen_address: Local address to bind.
        listen_port: Local UDP port to bind.
        ring_seconds: Delay before ``180 Ringing``.
        answer_seconds: Delay before ``200 OK``.
        talk_seconds: Delay between ``200 OK`` and the ``BYE`` that releases the call.
        received_invites: Every INVITE the AS originated, in arrival order.
        released_call_ids: Call-IDs for which this side has sent a ``BYE``.
    """

    def __init__(
        self,
        listen_address: str = "127.0.0.1",
        listen_port: int = 15061,
        *,
        ring_seconds: float = 0.2,
        answer_seconds: float = 0.2,
        talk_seconds: float = 0.2,
        passthrough: bool = False,
        passthrough_callback: ReturnPassthroughCallback | None = None,
        leg_label: str = "",
    ) -> None:
        """Create the UAS side of the mock.

        Args:
            listen_address: Local address to bind.
            listen_port: Local UDP port to bind.
            ring_seconds: Delay before ``180 Ringing``.
            answer_seconds: Delay before ``200 OK``.
            talk_seconds: Delay between ``200 OK`` and the ``BYE``.
            passthrough: When ``True``, do not auto-answer; notify ``passthrough_callback``.
            passthrough_callback: Orchestrator hook for 透传 (P9b, ADR-0014).
            leg_label: ``as1`` / ``as2`` label passed to the callback.
        """
        self.listen_address = listen_address
        self.listen_port = listen_port
        self.ring_seconds = ring_seconds
        self.answer_seconds = answer_seconds
        self.talk_seconds = talk_seconds
        self.passthrough = passthrough
        self.passthrough_callback = passthrough_callback
        self.leg_label = leg_label
        self.received_invites: list[ReceivedInvite] = []
        self.released_call_ids: list[str] = []
        self.global_config: dict[str, Any] = {}

    def build_global_config(self, sip_logger: Any | None = None) -> dict[str, Any]:
        """Build the sippy global configuration of this side of the mock.

        Args:
            sip_logger: SIP message logger; a quiet ``SipLogger`` is used when omitted.

        Returns:
            The global configuration dictionary sippy expects.
        """
        logger = sip_logger if sip_logger is not None else SipLogger("s-sbc-mock-uas")
        self.global_config = {
            "_sip_address": self.listen_address,
            "_sip_port": self.listen_port,
            "_sip_uaname": SIP_USER_AGENT_NAME,
            "_sip_logger": logger,
        }
        return self.global_config

    def recv_request(self, request: Any, transaction: Any) -> Any:
        """Handle a request arriving from the AS.

        Args:
            request: The parsed SIP request.
            transaction: The sippy server transaction of the request.

        Returns:
            The sippy callback triple ``(response, cancel_cb, noack_cb)``.
        """
        if request.getHFBody("to").getTag() is not None:
            return (request.genResponse(481, "Call Leg/Transaction Does Not Exist"), None, None)
        if request.getMethod() != "INVITE":
            return (request.genResponse(501, "Not Implemented"), None, None)
        self._record(request)
        if self.passthrough and self.passthrough_callback is not None:
            ua = UA(self.global_config, self._passthrough_on_event)
            ua.local_ua = SIP_USER_AGENT_NAME
            ua.lContact = self._contact()
            self.passthrough_callback.on_return_invite(request, ua, self.leg_label)
            return ua.recvRequest(request, transaction)
        ua = UA(self.global_config, self._on_event)
        ua.local_ua = SIP_USER_AGENT_NAME
        ua.lContact = self._contact()
        return ua.recvRequest(request, transaction)

    def _contact(self) -> Any:
        """Build the Contact header of the core side.

        Returns:
            A ``SipContact`` pointing at the local address and port of this side.
        """
        url = SipURL(
            host=self.listen_address, port=self.listen_port, transport=SipConf.my_transport
        )
        return SipContact(address=SipAddress(url=url))

    def wait_for_invite(self, timeout_seconds: float = 5.0) -> ReceivedInvite:
        """Wait for the next INVITE originated by the AS.

        The call is driven by sippy's blocking event loop, so this method advances that
        loop in short slices until the INVITE arrives. It is meant for the fixture case,
        where the caller owns the loop; in process mode the loop is already running and
        :attr:`received_invites` is read directly.

        Args:
            timeout_seconds: How long to wait.

        Returns:
            The received INVITE.

        Raises:
            TimeoutError: When no INVITE arrived within the timeout.
        """
        from sippy.Core.EventDispatcher import ED2

        deadline = time.monotonic() + timeout_seconds
        while not self.received_invites:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no INVITE reached the core side within {timeout_seconds}s")
            ED2.loop(timeout=min(0.05, remaining))
        return self.received_invites[-1]

    def _record(self, request: Any) -> None:
        """Store the INVITE the AS originated, for assertions and evidence.

        Args:
            request: The parsed SIP INVITE.
        """
        call_id = str(request.getHFBody("call-id"))
        request_uri = str(request.getRURI())
        body = request.getBody()
        calling = _header_value(request, "p-asserted-identity")
        self.received_invites.append(
            ReceivedInvite(
                call_id=call_id,
                request_uri=request_uri,
                called_number=str(request.getRURI().username),
                calling_number=calling,
                body="" if body is None else str(body).strip(),
                headers={header.name: str(header.body) for header in request.headers},
            )
        )
        _LOGGER.info(
            "core side received INVITE call_id=%s ruri=%s called=%s",
            call_id,
            request_uri,
            request.getRURI().username,
        )

    def _passthrough_on_event(self, event: Any, ua: Any) -> None:
        """Handle events on a return leg waiting for orchestrator-injected responses.

        Args:
            event: A sippy ``CCEvent``.
            ua: The sippy UA the event came from.
        """
        if isinstance(event, CCEventDisconnect):
            return
        _LOGGER.debug("return passthrough ignored %s", type(event).__name__)

    def _on_event(self, event: Any, ua: Any) -> None:
        """Answer the call: ring, answer, then release it after the talk time.

        Args:
            event: A sippy ``CCEvent``.
            ua: The sippy UA the event came from.
        """
        if isinstance(event, CCEventTry):
            Timeout(self._ring, self.ring_seconds, 1, ua)
            return
        if isinstance(event, CCEventDisconnect):
            # The far end released the call; nothing left to do on this side.
            return
        _LOGGER.debug("core side ignored %s", type(event).__name__)

    def _ring(self, ua: Any) -> None:
        """Send ``180 Ringing`` and schedule the answer.

        Args:
            ua: The sippy UA of the call.
        """
        ua.recvEvent(CCEventRing((180, "Ringing", None)))
        Timeout(self._answer, self.answer_seconds, 1, ua)

    def _answer(self, ua: Any) -> None:
        """Send ``200 OK`` with the offered SDP echoed back, and schedule the release.

        Args:
            ua: The sippy UA of the call.
        """
        body = ua.rSDP.getCopy() if ua.rSDP is not None else None
        ua.recvEvent(CCEventConnect((200, "OK", body)))
        Timeout(self._release, self.talk_seconds, 1, ua)

    def _release(self, ua: Any) -> None:
        """Send the ``BYE`` that releases the call.

        Args:
            ua: The sippy UA of the call.
        """
        call_id = str(ua.cId)
        self.released_call_ids.append(call_id)
        ua.disconnect()
