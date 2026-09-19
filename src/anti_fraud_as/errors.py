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

"""The anti-fraud AS's error family and the shared mechanism it builds on.

The second AS is a second *process*, not a second error vocabulary: it builds on the same
mechanism as the first — the memberless :class:`ErrorCode` base, the SIP status mapping,
the reason-phrase table and :class:`AsError` — and adds only the codes it owns,
``AS-FRAUD-*` in :class:`FraudErrorCode` (REQ-F-023, ADR-0009 decision 3).

The three rejection codes map to ``608 Rejected`` (RFC 8688, ADR-0007); a rejection is
distinguished by code, not by status, because they share one status. The ``AS-FRAUD-004`` /
``AS-FRAUD-005`` data failures map to ``500`` like the routing-rule family, and
``AS-FRAUD-006`` is the internal fallback when the pure engine returns no verdict.
"""

from __future__ import annotations

from as_app.errors import (
    SIP_PHRASES,
    AsError,
    ErrorCode,
    SkeletonErrorCode,
    sip_status_for,
)

__all__ = [
    "AsError",
    "ErrorCode",
    "FraudErrorCode",
    "SIP_PHRASES",
    "SkeletonErrorCode",
    "sip_status_for",
]


class FraudErrorCode(ErrorCode):
    """The anti-fraud codes: the screening verdict and its data failures.

    The three rejection codes share the ``608`` status and are told apart by their code;
    the ``AS-FRAUD-004`` / ``AS-FRAUD-005`` rows are configuration failures.
    """

    FRAUD_CALLER_BLOCKED = ("AS-FRAUD-001", 608, "calling party is on the block list")
    FRAUD_RATE_EXCEEDED = ("AS-FRAUD-002", 608, "calling party exceeded the call-rate window")
    FRAUD_REPUTATION_LOW = ("AS-FRAUD-003", 608, "calling party reputation is below the threshold")
    FRAUD_DATA_UNREADABLE = ("AS-FRAUD-004", 500, "screening data file cannot be read")
    FRAUD_DATA_SCHEMA_ERROR = ("AS-FRAUD-005", 500, "screening data file violates the schema")
    FRAUD_NO_VERDICT = ("AS-FRAUD-006", 500, "screening produced no verdict")
