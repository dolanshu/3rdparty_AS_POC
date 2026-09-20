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

"""Unit tests for the anti-fraud controller's two overrides of the shared shell.

The relay shell lives in ``as_platform.call_controller.BaseCallController`` and carries
defaults that fit the number-translation AS (ADR-0009 decision 4). The anti-fraud configures
its single hop by address and port only, so :class:`FraudCallController` overrides the
peer-status key and the no-answer hop label, and this file pins those overrides — including
the internal hop name ``fraud_sbc_peer`` that must never be rendered. That point was
confirmed only by inspection in the implementation-stage review, and it is exactly the kind
of silent behaviour change the extraction could otherwise leave untested (REQ-F-031).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from as_platform.hop import NextHop

from anti_fraud_as.call_controller import FraudCallController
from anti_fraud_as.caller_state import CallerStateStore
from anti_fraud_as.screening_data import ScreeningDataStore

pytestmark = pytest.mark.unit

#: Name of the single hop this AS configures. It is plumbing the shell must never render.
NEXT_HOP_NAME = "fraud_sbc_peer"

#: The next hop the controller is bound to in these tests.
NEXT_HOP = ("127.0.0.1", 15061)


def build_controller(screening_file: Path, next_hop: tuple[str, int] | None) -> FraudCallController:
    """Build a controller wired to the shipped screening data and a next hop.

    Args:
        screening_file: Screening data file the controller loads.
        next_hop: ``(address, port)`` of the next hop, or ``None``.

    Returns:
        A controller whose relay shell points at ``next_hop``.
    """
    screening_data = ScreeningDataStore(screening_file)
    caller_state = CallerStateStore(screening_data.current.policy)
    return FraudCallController(screening_data, caller_state, next_hop=next_hop)


def test_the_peer_status_key_is_the_address_and_port(screening_file: Path) -> None:
    """The shell default renders ``name:address:port``; this AS renders ``address:port``.

    The key is what the peer-status counters track a hop under, so the override keeps it
    exactly what it was before the shell moved into the library.
    """
    controller = build_controller(screening_file, NEXT_HOP)
    hop = NextHop(name=NEXT_HOP_NAME, address="127.0.0.1", port=15061)
    assert controller._peer_status_key(hop) == "127.0.0.1:15061"


def test_the_peer_status_key_never_renders_the_internal_hop_name(screening_file: Path) -> None:
    """``fraud_sbc_peer`` is configuration plumbing and must not reach the counters."""
    controller = build_controller(screening_file, NEXT_HOP)
    hop = NextHop(name=NEXT_HOP_NAME, address="10.0.0.1", port=15062)
    assert NEXT_HOP_NAME not in controller._peer_status_key(hop)


def test_the_no_answer_label_is_the_serving_hop_address_and_port(screening_file: Path) -> None:
    """The no-answer warning names the hop it is about as ``address:port``."""
    controller = build_controller(screening_file, NEXT_HOP)
    assert controller._no_answer_hop_label() == "127.0.0.1:15061"


def test_the_no_answer_label_is_a_dash_without_a_serving_hop(screening_file: Path) -> None:
    """With no hop configured the label is ``-``, not the shell's empty default."""
    controller = build_controller(screening_file, None)
    assert controller._no_answer_hop_label() == "-"
