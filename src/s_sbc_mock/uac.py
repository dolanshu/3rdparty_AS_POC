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

"""UAC side of the mock: emulates the S-CSCF iFC trigger.

The S-CSCF does not call the AS directly in production — an iFC match routes the INVITE
to the S-SBC, which forwards it over the trunk. This side of the mock originates that
INVITE towards the AS and then behaves like a normal UAC (cancel, ack, bye).

The sippy UAC is wired in M1; M0 fixes the interface and the scenario parameters.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CallScenario", "TrunkUac"]


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
    """

    name: str
    calling_number: str
    called_number: str
    expect_status: int = 200
    ring_seconds: float = 0.2
    talk_seconds: float = 0.2
    abandon: bool = False


class TrunkUac:
    """Originates calls towards the AS over the trunk.

    Attributes:
        as_address: Address of the AS.
        as_port: UDP port of the AS.
        local_address: Local address the mock sends from.
        local_port: Local UDP port of the mock.
    """

    def __init__(
        self,
        as_address: str,
        as_port: int,
        *,
        local_address: str = "127.0.0.1",
        local_port: int = 15060,
    ) -> None:
        """Create the UAC side of the mock.

        Args:
            as_address: Address of the AS.
            as_port: UDP port of the AS.
            local_address: Local address to send from.
            local_port: Local UDP port to bind.
        """
        self.as_address = as_address
        self.as_port = as_port
        self.local_address = local_address
        self.local_port = local_port

    def place_call(self, scenario: CallScenario) -> str:
        """Place one call towards the AS.

        Args:
            scenario: The call to place.

        Returns:
            The Call-ID of the call.

        Raises:
            NotImplementedError: Until the sippy UAC is wired in M1.
        """
        raise NotImplementedError(
            f"TrunkUac.place_call({scenario.name!r}) is implemented in M1 (signalling path)"
        )
