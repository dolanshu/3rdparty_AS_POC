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

"""End-to-end call flows.

The e2e layer drives a complete call through the AS and the mock S-SBC on localhost UDP
and asserts on the messages that arrive on the far side, including the error branches
(``AGENT.md`` section 11). The signalling path is delivered in **M1**; until then the
cases below are declared here so that the required coverage is visible in CI and nobody
has to re-derive it.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

PENDING = pytest.mark.skip(reason="signalling path is delivered in M1 (see docs/roadmap.md)")


@PENDING
def test_complete_call_invite_to_bye() -> None:
    """INVITE -> 100 -> 180 -> 200 OK -> ACK -> BYE completes with SDP pass-through."""
    raise NotImplementedError


@PENDING
def test_unmatched_number_is_answered_with_404() -> None:
    """A called number no rule accepts is answered with 404 and AS-ROUTE-001."""
    raise NotImplementedError


@PENDING
def test_blocked_number_is_answered_with_603() -> None:
    """A policy rejection is answered with 603 Decline and AS-ROUTE-002."""
    raise NotImplementedError


@PENDING
def test_caller_abandonment_sends_cancel() -> None:
    """A caller that gives up before answer makes the AS tear the call down with CANCEL."""
    raise NotImplementedError
