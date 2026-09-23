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

"""Pure S-CSCF / iFC state machine (unit-testable, no sockets)."""

from __future__ import annotations

from enum import Enum

__all__ = ["OrchestratorState", "OrchestratorFsm"]


class OrchestratorState(str, Enum):
    """States from ``docs/chained-topology-plan.md`` section 4."""

    IDLE = "idle"
    IFC1_PENDING = "ifc1_pending"
    AS1_AWAIT_OUTBOUND = "as1_await_outbound"
    IFC2_PENDING = "ifc2_pending"
    AS2_AWAIT_OUTBOUND = "as2_await_outbound"
    TERMINATING = "terminating"
    ACTIVE = "active"
    REJECTED = "rejected"


class OrchestratorFsm:
    """Minimal state machine for iFC chain progression."""

    def __init__(self) -> None:
        """Start in :attr:`OrchestratorState.IDLE`."""
        self.state = OrchestratorState.IDLE

    def on_subscriber_invite(self) -> None:
        """Subscriber placed the initial INVITE."""
        if self.state != OrchestratorState.IDLE:
            raise ValueError(f"unexpected subscriber INVITE in state {self.state}")
        self.state = OrchestratorState.IFC1_PENDING

    def on_ifc1_sent(self) -> None:
        """Trunk INVITE to AS-1 was dispatched."""
        if self.state != OrchestratorState.IFC1_PENDING:
            raise ValueError(f"unexpected iFC #1 sent in state {self.state}")
        self.state = OrchestratorState.AS1_AWAIT_OUTBOUND

    def on_as1_outbound_passthrough(self) -> None:
        """AS-1 outbound INVITE was 透传 to the orchestrator."""
        if self.state != OrchestratorState.AS1_AWAIT_OUTBOUND:
            raise ValueError(f"unexpected AS-1 outbound in state {self.state}")
        self.state = OrchestratorState.IFC2_PENDING

    def on_as1_reject(self) -> None:
        """AS-1 answered 608 on the trunk."""
        if self.state != OrchestratorState.AS1_AWAIT_OUTBOUND:
            raise ValueError(f"unexpected AS-1 reject in state {self.state}")
        self.state = OrchestratorState.REJECTED

    def on_ifc2_sent(self) -> None:
        """Trunk INVITE to AS-2 was dispatched."""
        if self.state != OrchestratorState.IFC2_PENDING:
            raise ValueError(f"unexpected iFC #2 sent in state {self.state}")
        self.state = OrchestratorState.AS2_AWAIT_OUTBOUND

    def on_as2_outbound_passthrough(self) -> None:
        """AS-2 outbound INVITE was 透传 to the orchestrator."""
        if self.state != OrchestratorState.AS2_AWAIT_OUTBOUND:
            raise ValueError(f"unexpected AS-2 outbound in state {self.state}")
        self.state = OrchestratorState.TERMINATING

    def on_dialog_active(self) -> None:
        """200 OK completed through the chain."""
        if self.state != OrchestratorState.TERMINATING:
            raise ValueError(f"unexpected dialog active in state {self.state}")
        self.state = OrchestratorState.ACTIVE

    def on_bye(self) -> None:
        """Subscriber dialog released."""
        if self.state not in (OrchestratorState.ACTIVE, OrchestratorState.TERMINATING):
            raise ValueError(f"unexpected BYE in state {self.state}")
        self.state = OrchestratorState.IDLE
