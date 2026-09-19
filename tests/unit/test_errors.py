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

"""Unit tests for the error model and its SIP status mapping."""

from __future__ import annotations

import pytest

from anti_fraud_as.errors import FraudErrorCode
from as_app.errors import SIP_PHRASES, AsError, AsErrorCode, SkeletonErrorCode

pytestmark = pytest.mark.unit

#: Every code family the mechanism carries, one subclass per vocabulary (ADR-0009
#: decision 3). The uniqueness and status-coverage checks below span all three, so a code
#: added to any family cannot collide with another or miss its reason phrase.
ALL_FAMILIES = (AsErrorCode, SkeletonErrorCode, FraudErrorCode)


def test_every_code_has_a_unique_identifier_and_status() -> None:
    """Error codes are unique across every family and every status has a reason phrase."""
    codes = [code.code for family in ALL_FAMILIES for code in family]
    assert len(codes) == len(set(codes))
    for family in ALL_FAMILIES:
        for code in family:
            assert code.sip_status in SIP_PHRASES


def test_relevant_sip_statuses_are_present() -> None:
    """The statuses the POC needs are mapped (AGENT.md section 1, failure branches)."""
    statuses = {code.sip_status for family in ALL_FAMILIES for code in family}
    assert {404, 603, 403, 500}.issubset(statuses)


def test_error_exposes_status_phrase_and_log_fields() -> None:
    """An error renders its code, status and context for a log line."""
    error = AsError(
        AsErrorCode.ROUTE_NO_MATCH,
        "no rule for +9991234567",
        call_id="abc@example.invalid",
        context={"called_number": "+9991234567"},
    )
    assert error.sip_status == 404
    assert error.sip_phrase == "Not Found"
    fields = error.as_log_fields()
    assert fields["error_code"] == "AS-ROUTE-001"
    assert fields["sip_status"] == "404"
    assert fields["called_number"] == "+9991234567"


def test_error_falls_back_to_the_code_message() -> None:
    """Without a detail the message of the code is used."""
    assert (
        AsError(SkeletonErrorCode.PEER_NOT_ALLOWED).detail
        == "source address is not an allowed trunk peer"
    )
