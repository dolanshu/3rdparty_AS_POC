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

"""Authoritative error model for the AS.

One code system covers configuration, rules, routing and peer handling. Each code maps
to a SIP status code (RFC 3261 section 21) and to a log message, so that a log line, an
error counter and a SIP response never disagree about what went wrong. The mapping is
documented in ``docs/architecture/lld.md``; no module raises bare ``Exception`` with an
ad-hoc string (``AGENT.md`` section 4.3).
"""

from __future__ import annotations

from enum import Enum
from typing import Final

__all__ = ["AsError", "AsErrorCode", "SIP_PHRASES", "sip_status_for"]


class AsErrorCode(Enum):
    """Internal, stable error identifier with its SIP status and log message."""

    # --- configuration -----------------------------------------------------
    CFG_MISSING = ("AS-CFG-001", 500, "required configuration value is missing")
    CFG_INVALID = ("AS-CFG-002", 500, "configuration value failed validation")
    CFG_PORT_UNAVAILABLE = ("AS-CFG-003", 500, "signalling port cannot be bound")
    CFG_PEER_INVALID = ("AS-CFG-004", 500, "trunk peer configuration is not usable")

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

    # --- trunk peers -------------------------------------------------------
    PEER_NOT_ALLOWED = ("AS-PEER-001", 403, "source address is not an allowed trunk peer")
    PEER_UNREACHABLE = ("AS-PEER-002", 503, "next hop peer did not answer")
    PEER_MALFORMED_REQUEST = ("AS-PEER-003", 400, "request from the trunk could not be parsed")

    # --- anti-fraud screening (P8) -----------------------------------------
    # The anti-fraud AS is a second process, but a second process must not grow a second
    # error vocabulary: its codes live in this one authoritative model (REQ-F-023). The
    # three rejection codes map to 608 Rejected (RFC 8688, ADR-0007); a rejection is
    # distinguished by code, not by status, because they share one status.
    FRAUD_CALLER_BLOCKED = ("AS-FRAUD-001", 608, "calling party is on the block list")
    FRAUD_RATE_EXCEEDED = ("AS-FRAUD-002", 608, "calling party exceeded the call-rate window")
    FRAUD_REPUTATION_LOW = ("AS-FRAUD-003", 608, "calling party reputation is below the threshold")
    FRAUD_DATA_UNREADABLE = ("AS-FRAUD-004", 500, "screening data file cannot be read")
    FRAUD_DATA_SCHEMA_ERROR = ("AS-FRAUD-005", 500, "screening data file violates the schema")
    FRAUD_NO_VERDICT = ("AS-FRAUD-006", 500, "screening produced no verdict")

    # --- internal ----------------------------------------------------------
    INTERNAL_ERROR = ("AS-INT-001", 500, "unexpected internal failure")

    def __init__(self, code: str, sip_status: int, message: str) -> None:
        """Bind the enum member to its code, SIP status and default log message.

        Args:
            code: Stable, human readable identifier such as ``AS-ROUTE-001``.
            sip_status: SIP status code used when the failure is reported on the trunk.
            message: Default log message, written in lower case English.
        """
        self.code: Final[str] = code
        self.sip_status: Final[int] = sip_status
        self.message: Final[str] = message


#: Reason phrases for the status codes this application can emit (RFC 3261 section 21,
#: RFC 8688 section 3 for 608). sippy puts the phrase it is given on the wire verbatim, so
#: this map is the only thing that makes a rejected call read as ``608 Rejected`` instead of
#: falling back to ``Server Internal Error`` (ADR-0007, LLD section 9.5).
SIP_PHRASES: Final[dict[int, str]] = {
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    480: "Temporarily Unavailable",
    500: "Server Internal Error",
    503: "Service Unavailable",
    603: "Decline",
    608: "Rejected",
}


def sip_status_for(code: AsErrorCode) -> int:
    """Return the SIP status code that reports the given internal error.

    Args:
        code: Internal error identifier.

    Returns:
        The SIP status code from the error model.
    """
    return code.sip_status


class AsError(Exception):
    """Application error carrying an :class:`AsErrorCode` and structured context.

    The context dictionary is logged verbatim; it must never contain payload bodies or
    credentials (``AGENT.md`` section 9).
    """

    def __init__(
        self,
        code: AsErrorCode,
        detail: str | None = None,
        *,
        call_id: str | None = None,
        context: dict[str, str] | None = None,
    ) -> None:
        """Create an application error.

        Args:
            code: Internal error identifier.
            detail: Optional specific explanation; falls back to the code message.
            call_id: SIP Call-ID of the affected call, when known.
            context: Extra structured fields for the log line.
        """
        super().__init__(detail or code.message)
        self.code = code
        self.detail = detail or code.message
        self.call_id = call_id
        self.context: dict[str, str] = dict(context or {})

    @property
    def sip_status(self) -> int:
        """SIP status code used to report this failure on the trunk."""
        return self.code.sip_status

    @property
    def sip_phrase(self) -> str:
        """Reason phrase belonging to :attr:`sip_status`."""
        return SIP_PHRASES.get(self.sip_status, "Server Internal Error")

    def as_log_fields(self) -> dict[str, str]:
        """Render the error as the structured fields of a log line.

        Returns:
            A mapping with the error code, the SIP status and the detail text.
        """
        fields = {
            "error_code": self.code.code,
            "sip_status": str(self.sip_status),
            "error_detail": self.detail,
        }
        fields.update(self.context)
        return fields
