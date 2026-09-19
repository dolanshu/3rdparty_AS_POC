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

"""Unit tests for the ``AS-FRAUD-*`` error family and how the verdict is observed.

Two things are pinned here. First, the second AS is a second *process*, not a second error
vocabulary: its codes live in the one authoritative model of ``src/as_app/errors.py``, and
the three rejection codes carry ``608`` with the phrase ``Rejected`` — sippy puts the phrase
it is handed on the wire verbatim, so a missing ``SIP_PHRASES[608]`` would answer
``608 Server Internal Error`` (ADR-0007, LLD section 9.5).

Second, the verdict has to be observable off the wire (REQ-F-024): the generic counter
bucket, the health document and the screening payload are the three surfaces the console
reads, and each one is asserted by key rather than by shape.

Covers ACC-P8-005 (REQ-F-023, REQ-F-024) and the rejection semantics of ACC-P8-002
(REQ-F-019).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anti_fraud_as.internal_api import (
    INTERNAL_API_ROUTES,
    health_payload,
    metrics_payload,
    screening_payload,
)
from anti_fraud_as.screening_data import ScreeningDataStore
from as_app.errors import SIP_PHRASES, AsError, AsErrorCode
from as_app.observability.metrics import MetricsRegistry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The 608 phrase and the AS-FRAUD-* family (REQ-F-023)
# ---------------------------------------------------------------------------


def test_sip_phrases_maps_608_to_rejected() -> None:
    """``608`` has its own phrase; the fallback would put the wrong words on the wire."""
    assert SIP_PHRASES[608] == "Rejected"


def test_every_error_code_has_a_reason_phrase() -> None:
    """No code can fall back to ``Server Internal Error`` by accident.

    ``AsError.sip_phrase`` resolves through ``SIP_PHRASES``, so a status the table does not
    know is answered with the wrong phrase silently. This is the guard that the new ``608``
    family was added to the table as well as to the code list.
    """
    missing = sorted({code.sip_status for code in AsErrorCode} - set(SIP_PHRASES))

    assert not missing, f"error statuses without a reason phrase: {missing}"


@pytest.mark.parametrize(
    "code",
    [
        AsErrorCode.FRAUD_CALLER_BLOCKED,
        AsErrorCode.FRAUD_RATE_EXCEEDED,
        AsErrorCode.FRAUD_REPUTATION_LOW,
    ],
)
def test_the_screening_rejections_are_answered_with_608(code: AsErrorCode) -> None:
    """A screening rejection is a 608, whichever signal fired.

    The status is shared, so the *code* is what distinguishes block list from rate window
    from reputation in the counters and the trace.
    """
    error = AsError(code, code.message)

    assert error.sip_status == 608
    assert error.sip_phrase == "Rejected"
    assert error.as_log_fields()["sip_status"] == "608"
    assert error.as_log_fields()["error_code"] == code.code


@pytest.mark.parametrize(
    "code",
    [
        AsErrorCode.FRAUD_DATA_UNREADABLE,
        AsErrorCode.FRAUD_DATA_SCHEMA_ERROR,
        AsErrorCode.FRAUD_NO_VERDICT,
    ],
)
def test_the_configuration_failures_are_answered_with_500(code: AsErrorCode) -> None:
    """A broken data file is an AS failure, not a verdict about the caller."""
    error = AsError(code, code.message)

    assert error.sip_status == 500
    assert error.sip_phrase == "Server Internal Error"


def test_the_fraud_codes_are_unique_and_prefixed() -> None:
    """Codes are stable identifiers: no duplicates, and the family is recognisable."""
    fraud = [code for code in AsErrorCode if code.code.startswith("AS-FRAUD-")]
    codes = [code.code for code in fraud]

    assert codes == [
        "AS-FRAUD-001",
        "AS-FRAUD-002",
        "AS-FRAUD-003",
        "AS-FRAUD-004",
        "AS-FRAUD-005",
        "AS-FRAUD-006",
    ]
    assert len(set(codes)) == len(codes)


def test_fraud_codes_live_in_the_shared_error_model() -> None:
    """One authoritative model for both processes (REQ-F-023).

    The anti-fraud AS must not grow its own error vocabulary: a reviewer reads one table,
    and the console renders one ``errors_by_code`` map.
    """
    from anti_fraud_as import call_controller, screening_data

    assert call_controller.AsErrorCode is AsErrorCode
    assert screening_data.AsErrorCode is AsErrorCode


# ---------------------------------------------------------------------------
# The verdict is observable (REQ-F-024)
# ---------------------------------------------------------------------------


def test_the_counter_bucket_records_named_counters() -> None:
    """The one generic addition to the registry: a named bucket both AS instances share."""
    registry = MetricsRegistry()
    registry.record_counter("verdict.reject")
    registry.record_counter("verdict.reject")
    registry.record_counter("screen.block_list")

    snapshot = registry.snapshot()

    assert snapshot.counters == {"verdict.reject": 2, "screen.block_list": 1}


def test_the_counter_bucket_is_empty_until_it_is_written() -> None:
    """The number-translation AS never writes it, so its payload only gains an empty key."""
    registry = MetricsRegistry()

    assert registry.snapshot().counters == {}
    assert metrics_payload(registry)["counters"] == {}


def test_metrics_payload_exposes_the_counters_next_to_the_errors() -> None:
    """Both surfaces the console needs: what happened, and why."""
    registry = MetricsRegistry()
    registry.record_call_started()
    registry.record_counter("verdict.reject")
    registry.record_error(AsErrorCode.FRAUD_CALLER_BLOCKED.code)

    payload = metrics_payload(registry)

    assert payload["counters"] == {"verdict.reject": 1}
    assert payload["errors_by_code"] == {"AS-FRAUD-001": 1}
    assert payload["calls_total"] == 1
    # The number-translation key is still present so one console page renders either AS.
    assert payload["rule_hits"] == {}


def test_health_reports_the_instance_identity() -> None:
    """The console labels the page from what the AS reports, never from the port."""
    from anti_fraud_as.internal_api import INSTANCE_NAME as FRAUD_INSTANCE
    from as_app.internal_api import INSTANCE_NAME as AS_INSTANCE

    assert FRAUD_INSTANCE == "anti-fraud"
    assert AS_INSTANCE == "number-translation"
    assert FRAUD_INSTANCE != AS_INSTANCE

    payload = health_payload(version="0.0.0", uptime_seconds=1.0, screening_data_loaded=True)

    assert payload["instance"] == FRAUD_INSTANCE


def test_health_reports_the_honest_readiness_key_and_the_compatibility_one() -> None:
    """``screening_data_loaded`` is the truth; ``rule_set_loaded`` only keeps the page shared.

    The anti-fraud AS has no rule set, so the compatibility key must not be the one a
    consumer believes.
    """
    ready = health_payload(version="0.0.0", uptime_seconds=1.0, screening_data_loaded=True)
    degraded = health_payload(version="0.0.0", uptime_seconds=1.0, screening_data_loaded=False)

    assert ready["status"] == "ok"
    assert ready["screening_data_loaded"] is True
    assert ready["rule_set_loaded"] is True
    assert ready["uptime_seconds"] == 1.0

    assert degraded["status"] == "degraded"
    assert degraded["screening_data_loaded"] is False


def test_the_internal_api_covers_the_console_surface() -> None:
    """The routes the console of the second instance needs are all declared."""
    joined = " ".join(INTERNAL_API_ROUTES)

    for fragment in (
        "/healthz",
        "/api/v1/metrics",
        "/api/v1/screening",
        "/api/v1/traces",
        "/ws/events",
    ):
        assert fragment in joined, fragment


def test_the_screening_payload_is_read_only_json(screening_file: Path) -> None:
    """The console renders the lists and the thresholds without a second call."""
    store = ScreeningDataStore(screening_file)

    payload = screening_payload(store)

    assert payload["name"] == store.current.document.name
    assert payload["window"]["max_calls"] == store.current.document.window.max_calls
    assert payload["reputation"]["reject_below"] == store.current.document.reputation.reject_below
    assert [entry["entry_id"] for entry in payload["block_list"]] == [
        entry.entry_id for entry in store.current.block_entries()
    ]
    assert [entry["entry_id"] for entry in payload["allow_list"]] == [
        entry.entry_id for entry in store.current.allow_entries()
    ]
    # The payload is what the browser receives, so it has to serialise.
    assert json.loads(json.dumps(payload)) == payload


def test_the_second_as_serves_the_repository_version() -> None:
    """One version source for both AS processes (AGENT.md section 4.7)."""
    import anti_fraud_as
    import as_app

    assert anti_fraud_as.__version__ == as_app.__version__
