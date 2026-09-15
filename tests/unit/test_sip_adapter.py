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

"""Unit tests for the pure URI and peer helpers of the sippy adapter."""

from __future__ import annotations

import pytest

from as_app.errors import AsError, AsErrorCode
from as_app.routing.rules import NextHop
from as_app.sip_adapter import build_request_uri, extract_called_number, is_allowed_peer

pytestmark = pytest.mark.unit


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
    assert excinfo.value.code is AsErrorCode.PEER_MALFORMED_REQUEST


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


def test_peer_allowlist_accepts_configured_and_rejects_others() -> None:
    """Only configured trunk peers are accepted (AGENT.md section 9)."""
    assert is_allowed_peer("127.0.0.1", ["127.0.0.1", "10.0.0.1"]) is True
    assert is_allowed_peer("192.0.2.1", ["127.0.0.1"]) is False
