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

"""Minimal P-CSCF relay: forwards an AS outbound INVITE toward the terminating UAS."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sippy.CCEvents import CCEventConnect, CCEventDisconnect, CCEventRing, CCEventTry
from sippy.MsgBody import MsgBody
from sippy.SipAddress import SipAddress
from sippy.SipConf import SipConf
from sippy.SipContact import SipContact
from sippy.SipLogger import SipLogger
from sippy.SipURL import SipURL
from sippy.UA import UA

__all__ = ["PcscfRelay"]

_LOGGER = logging.getLogger(__name__)

SIP_USER_AGENT_NAME = "3rd-party AS POC mock P-CSCF"


@dataclass
class _RelaySession:
    """Callbacks for one P-CSCF relay UAC leg."""

    on_provisional: Callable[[int, str], None] | None = None
    on_final: Callable[[int, str, Any], None] | None = None
    on_disconnect: Callable[[], None] | None = None


class PcscfRelay:
    """Originate toward the terminating UAS and relay responses to AS return UAs."""

    def __init__(
        self,
        terminating_address: str,
        terminating_port: int,
        *,
        local_address: str = "127.0.0.1",
        local_port: int = 0,
    ) -> None:
        """Create the relay."""
        self.terminating_address = terminating_address
        self.terminating_port = terminating_port
        self.local_address = local_address
        self.local_port = local_port
        self.global_config: dict[str, Any] = {}
        self._sessions: dict[str, _RelaySession] = {}

    def build_global_config(self, sip_logger: Any | None = None) -> dict[str, Any]:
        """Build sippy global configuration for the relay UAC side."""
        logger = sip_logger if sip_logger is not None else SipLogger("pcscf-relay")
        self.global_config = {
            "nh_addr": (self.terminating_address, self.terminating_port),
            "_sip_address": self.local_address,
            "_sip_port": self.local_port,
            "_sip_uaname": SIP_USER_AGENT_NAME,
            "_sip_logger": logger,
        }
        return self.global_config

    def forward_invite(
        self,
        called_number: str,
        sdp_body: str,
        *,
        session_id: str,
        calling_number: str | None = None,
        extra_headers: tuple[Any, ...] = (),
        on_provisional: Callable[[int, str], None] | None = None,
        on_final: Callable[[int, str, Any], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
    ) -> None:
        """Place an INVITE toward the terminating UAS for one orchestrator session."""
        if self.global_config.get("_sip_tm") is None:
            raise RuntimeError("PcscfRelay is not bound to a transaction manager")
        self._sessions[session_id] = _RelaySession(
            on_provisional=on_provisional,
            on_final=on_final,
            on_disconnect=on_disconnect,
        )
        event = CCEventTry(
            (
                None,
                calling_number or "anonymous",
                called_number,
                MsgBody(content=sdp_body),
                None,
                None,
            )
        )
        if extra_headers:
            event.extra_headers = extra_headers
        ua = UA(
            self.global_config,
            lambda event, ua, sid=session_id: self._event_handler(event, ua, sid),
            nh_address=(self.terminating_address, self.terminating_port),
            nh_transport=SipConf.my_transport,
        )
        ua.lContact = SipContact(
            address=SipAddress(
                url=SipURL(
                    host=self.local_address,
                    port=self.local_port,
                    transport=SipConf.my_transport,
                )
            )
        )
        ua.local_ua = SIP_USER_AGENT_NAME
        ua.recvEvent(event)
        _LOGGER.info(
            "P-CSCF relay session=%s forwarded INVITE called=%s",
            session_id,
            called_number,
        )

    def _event_handler(self, event: Any, ua: Any, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        if isinstance(event, CCEventRing):
            data = event.getData()
            if data and session.on_provisional:
                session.on_provisional(int(data[0]), str(data[1]))
            return
        if isinstance(event, CCEventConnect):
            data = event.getData()
            if data and session.on_final:
                body = data[2] if len(data) > 2 else None
                session.on_final(int(data[0]), str(data[1]), body)
            return
        if isinstance(event, CCEventDisconnect):
            if session.on_disconnect:
                session.on_disconnect()
            self._sessions.pop(session_id, None)
            return
        _LOGGER.debug("P-CSCF relay ignored %s", type(event).__name__)
