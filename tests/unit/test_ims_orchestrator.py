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

"""Unit tests for the iFC orchestrator state machine."""

from __future__ import annotations

import pytest

from ims_mock.orchestrator import OrchestratorFsm, OrchestratorState

pytestmark = pytest.mark.unit


def test_allow_path_state_transitions() -> None:
    """Happy path matches the plan's state diagram."""
    fsm = OrchestratorFsm()
    assert fsm.state == OrchestratorState.IDLE
    fsm.on_subscriber_invite()
    fsm.on_ifc1_sent()
    assert fsm.state == OrchestratorState.AS1_AWAIT_OUTBOUND
    fsm.on_as1_outbound_passthrough()
    fsm.on_ifc2_sent()
    assert fsm.state == OrchestratorState.AS2_AWAIT_OUTBOUND
    fsm.on_as2_outbound_passthrough()
    assert fsm.state == OrchestratorState.TERMINATING
    fsm.on_dialog_active()
    assert fsm.state == OrchestratorState.ACTIVE
    fsm.on_bye()
    assert fsm.state == OrchestratorState.IDLE


def test_reject_at_as1_short_circuits() -> None:
    """608 at AS-1 does not advance to iFC #2."""
    fsm = OrchestratorFsm()
    fsm.on_subscriber_invite()
    fsm.on_ifc1_sent()
    fsm.on_as1_reject()
    assert fsm.state == OrchestratorState.REJECTED


def test_ifc2_not_before_as1_outbound() -> None:
    """iFC #2 cannot fire before AS-1 outbound 透传."""
    fsm = OrchestratorFsm()
    fsm.on_subscriber_invite()
    fsm.on_ifc1_sent()
    with pytest.raises(ValueError, match="iFC #2"):
        fsm.on_ifc2_sent()
