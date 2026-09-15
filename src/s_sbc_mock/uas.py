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

"""UAS side of the mock: emulates the core network behind the S-SBC.

The AS originates a new INVITE back to the trunk; this side answers it the way a core
network node would: ``100 Trying``, ``180 Ringing``, ``200 OK``, then ``BYE``. It is
built on the same SIP stack as the AS (ADR-0001, ADR-0005).

The sippy UAS is wired in M1; M0 fixes the interface.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CoreUas", "ReceivedInvite"]


@dataclass(frozen=True)
class ReceivedInvite:
    """An INVITE that reached the core side of the mock.

    Attributes:
        call_id: SIP Call-ID of the call.
        request_uri: Request-URI as received, after AS translation.
        called_number: User part of the Request-URI.
        calling_number: Calling party from ``P-Asserted-Identity``.
        body: SDP body, passed through by the AS.
    """

    call_id: str
    request_uri: str
    called_number: str
    calling_number: str | None = None
    body: str = ""


class CoreUas:
    """Answers the INVITE originated by the AS.

    Attributes:
        listen_address: Local address to bind.
        listen_port: Local UDP port to bind.
        ring_seconds: Delay before ``180 Ringing``.
        answer_seconds: Delay before ``200 OK``.
    """

    def __init__(
        self,
        listen_address: str = "127.0.0.1",
        listen_port: int = 15061,
        *,
        ring_seconds: float = 0.2,
        answer_seconds: float = 0.2,
    ) -> None:
        """Create the UAS side of the mock.

        Args:
            listen_address: Local address to bind.
            listen_port: Local UDP port to bind.
            ring_seconds: Delay before ``180 Ringing``.
            answer_seconds: Delay before ``200 OK``.
        """
        self.listen_address = listen_address
        self.listen_port = listen_port
        self.ring_seconds = ring_seconds
        self.answer_seconds = answer_seconds
        self.received_invites: list[ReceivedInvite] = []

    def wait_for_invite(self, timeout_seconds: float = 5.0) -> ReceivedInvite:
        """Wait for the next INVITE originated by the AS.

        Args:
            timeout_seconds: How long to wait.

        Returns:
            The received INVITE.

        Raises:
            NotImplementedError: Until the sippy UAS is wired in M1.
        """
        raise NotImplementedError(
            f"CoreUas.wait_for_invite(timeout={timeout_seconds}) is implemented in M1"
        )
