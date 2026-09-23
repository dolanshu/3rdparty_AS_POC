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

"""Callback contracts between the S-SBC return side and the orchestrator."""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["ReturnPassthroughCallback"]


class ReturnPassthroughCallback(Protocol):
    """In-process 透传 hook from the S-SBC return UAS."""

    def on_return_invite(self, request: Any, ua: Any, leg: str) -> None:
        """AS outbound INVITE arrived on the return port.

        Args:
            request: Parsed sippy request.
            ua: Server UA handling the INVITE.
            leg: ``as1`` or ``as2`` depending on which hop produced the message.
        """
