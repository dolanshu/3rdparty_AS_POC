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

"""Unit tests for the pure URI and peer helpers of the sippy adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from as_app.errors import AsError, SkeletonErrorCode
from as_app.routing.rules import NextHop
from as_app.sip_adapter import (
    build_request_uri,
    cancel_transaction_timers,
    extract_called_number,
    is_allowed_peer,
    outbound_call_id,
)

pytestmark = pytest.mark.unit


def _fake_timer() -> Any:
    """Build a stand-in for one sippy ``EventListener`` timer.

    Returns:
        A namespace with ``cb_func`` (non-``None`` while armed) and ``cancels`` (how often
        :meth:`cancel` was called). Cancelling clears ``cb_func`` exactly the way
        ``ED2``'s own listener does, so an already dead timer is recognisable.
    """
    timer: Any = SimpleNamespace(cb_func=object(), cancels=0)

    def cancel() -> None:
        timer.cancels += 1
        timer.cb_func = None

    timer.cancel = cancel
    return timer


def test_user_part_is_extracted_from_a_sip_uri() -> None:
    """The user part of the Request-URI is the called number (RFC 3261 section 19.1)."""
    assert extract_called_number("sip:+8613800138000@10.0.0.1:5060;user=phone") == "+8613800138000"


def test_uri_parameters_are_not_part_of_the_number() -> None:
    """URI parameters are stripped from the user part."""
    assert (
        extract_called_number("sip:02161234567@10.0.0.1;user=phone;transport=udp") == "02161234567"
    )


def test_missing_user_part_is_rejected() -> None:
    """A Request-URI without a user part reports AS-PEER-003."""
    with pytest.raises(AsError) as excinfo:
        extract_called_number("sip:10.0.0.1")
    assert excinfo.value.code is SkeletonErrorCode.PEER_MALFORMED_REQUEST


def test_outbound_request_uri_carries_host_port_and_transport() -> None:
    """The outbound Request-URI points at the selected next hop."""
    hop = NextHop(name="s-sbc-primary", address="127.0.0.1", port=15061)
    assert (
        build_request_uri("013800138000", hop) == "sip:013800138000@127.0.0.1:15061;transport=udp"
    )


def test_ipv6_next_hop_is_bracketed() -> None:
    """An IPv6 next hop is bracketed as required by RFC 3261 section 19.1."""
    hop = NextHop(name="v6", address="2001:db8::1", port=5060)
    assert build_request_uri("110", hop) == "sip:110@[2001:db8::1]:5060;transport=udp"


def test_every_transaction_timer_is_cancelled_before_a_shutdown() -> None:
    """Stopping a manager cancels the timers of both transaction tables.

    sippy's own ``shutdown()`` leaves these armed, which is what lets a retransmission
    dereference a torn-down stack (P8a).
    """
    client_timers = {"teA": _fake_timer(), "teB": _fake_timer()}
    # A server transaction only carries the timers its own RFC 3261 branch uses.
    server_timers = {"teA": _fake_timer(), "teD": _fake_timer()}
    client = SimpleNamespace(**client_timers)
    server = SimpleNamespace(**server_timers)
    manager = SimpleNamespace(tclient={"invite": client}, tserver={"invite": server})

    assert cancel_transaction_timers(manager) == 4

    for timer in (*client_timers.values(), *server_timers.values()):
        assert timer.cancels == 1, "every armed timer is cancelled exactly once"
        assert timer.cb_func is None
    # The transactions drop their references so nothing can re-arm them either.
    assert client.teA is None and client.teB is None
    assert server.teA is None and server.teD is None


def test_a_second_cancellation_finds_nothing_left_to_do() -> None:
    """Cancelling twice is safe; the second pass reports timers already fired."""
    client = SimpleNamespace(teA=_fake_timer())
    manager = SimpleNamespace(tclient={"invite": client}, tserver={})

    assert cancel_transaction_timers(manager) == 1
    assert cancel_transaction_timers(manager) == 0


def test_a_timer_that_has_already_fired_is_not_counted() -> None:
    """A one-shot timer whose callback ``ED2`` already ran is dead, not pending."""
    fired = _fake_timer()
    fired.cancel()
    manager = SimpleNamespace(tclient={"invite": SimpleNamespace(teA=fired)}, tserver={})

    assert cancel_transaction_timers(manager) == 0
    assert fired.cancels == 1  # sippy already cancelled it when it fired


def test_a_manager_that_was_already_shut_down_is_tolerated() -> None:
    """``shutdown()`` nulls the transaction tables; walking it must not raise."""
    assert cancel_transaction_timers(SimpleNamespace(tclient=None, tserver=None)) == 0
    assert cancel_transaction_timers(SimpleNamespace()) == 0


def test_peer_allowlist_accepts_configured_and_rejects_others() -> None:
    """Only configured trunk peers are accepted (AGENT.md section 9)."""
    assert is_allowed_peer("127.0.0.1", ["127.0.0.1", "10.0.0.1"]) is True
    assert is_allowed_peer("192.0.2.1", ["127.0.0.1"]) is False


def test_outbound_call_id_is_derived_from_and_distinct_from_the_trunk_one() -> None:
    """The outbound leg derives its own dialog identity, never the trunk Call-ID.

    The controllers depend on this pure contract: a controller that reused the trunk
    value, or derived the same one, is caught here instead of only by a socket test
    (REQ-NF-016, LLD section 10.2).
    """
    trunk_call_id = "a5f3c2e1-0001@example.invalid"
    outbound = outbound_call_id(trunk_call_id)
    assert outbound == f"{trunk_call_id}-b2b_1"
    assert outbound != trunk_call_id
