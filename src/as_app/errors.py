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

"""The number-translation AS's error family and the shared mechanism it builds on.

The shared mechanism — the memberless :class:`ErrorCode` base, the SIP status mapping, the
reason-phrase table and :class:`AsError` — lives in the platform library
(``as_platform.errors``). :class:`AsErrorCode` adds the codes this AS owns: the routing
rule vocabulary (``AS-RULE-*``) and the routing decision vocabulary (``AS-ROUTE-*``). The
framework codes ``AS-CFG-*``, ``AS-PEER-*`` and ``AS-INT-*`` are the library's
:class:`SkeletonErrorCode` family (ADR-0009 decision 3).

One mechanism, one code set per family: a log line, an error counter and a SIP response
never disagree about what went wrong, and no module raises a bare ``Exception`` with an
ad-hoc string (``AGENT.md`` section 4.3). The mapping is documented in
``docs/architecture/lld.md``.
"""

from __future__ import annotations

from as_platform.errors import (
    SIP_PHRASES,
    AsError,
    ErrorCode,
    SkeletonErrorCode,
    sip_status_for,
)

__all__ = [
    "AsError",
    "AsErrorCode",
    "ErrorCode",
    "SIP_PHRASES",
    "SkeletonErrorCode",
    "sip_status_for",
]


class AsErrorCode(ErrorCode):
    """The number-translation codes: routing rules and routing decisions."""

    # --- routing rules -----------------------------------------------------
    RULE_FILE_UNREADABLE = ("AS-RULE-001", 500, "routing rules file cannot be read")
    RULE_PARSE_ERROR = ("AS-RULE-002", 500, "routing rules file is not valid YAML")
    RULE_SCHEMA_ERROR = ("AS-RULE-003", 500, "routing rules violate the schema")
    RULE_DUPLICATE_ID = ("AS-RULE-004", 500, "routing rule identifier is not unique")

    # --- routing decisions -------------------------------------------------
    ROUTE_NO_MATCH = ("AS-ROUTE-001", 404, "no routing rule matched the called number")
    ROUTE_REJECTED = ("AS-ROUTE-002", 603, "policy rejected the call")
    ROUTE_NO_NEXT_HOP = ("AS-ROUTE-003", 480, "no next hop is available for the route")
    ROUTE_TRANSLATION_FAILED = ("AS-ROUTE-004", 500, "number translation produced no result")
