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

"""Unit tests for the declarative screening data file (LLD section 9.4).

Data, not code: the file is validated on load, and every way of getting it wrong is reported
as ``AS-FRAUD-004`` or ``AS-FRAUD-005`` rather than as a bare exception. These tests cover
the shipped file, the validation rules one by one, the derived entry identifiers and the
fail-safe reload — a broken edit must never take the call path down (ADR-0004 precedent).

Covers ACC-P8-003 (REQ-F-018) and the no-address property of ACC-P8-001 (REQ-F-016).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anti_fraud_as.errors import AsError, FraudErrorCode
from anti_fraud_as.screening_data import (
    ScreeningDataStore,
    ScreeningDocument,
    load_screening_data,
)

pytestmark = pytest.mark.unit

#: A minimal valid document; the list blocks are substituted per test.
_DOCUMENT = """\
version: 1
name: unit-screening
description: screening data for a unit test
window:
  seconds: 60
  max_calls: 3
reputation:
  half_life_seconds: 300
  default_score: 100.0
  reject_below: 30.0
  reject_penalty: 40.0
  max_tracked_callers: 100
block_list: []
allow_list: []
"""


def write_document(tmp_path: Path, **blocks: str) -> Path:
    """Write a screening document with the given list blocks substituted.

    Args:
        tmp_path: Directory the file is written to.
        **blocks: Replacement text keyed by the block name. Each value replaces that
            block's ``<name>: []`` placeholder, so a caller passes a whole YAML list.

    Returns:
        Path of the written file.
    """
    text = _DOCUMENT
    for name, replacement in blocks.items():
        text = text.replace(f"{name}: []", replacement)
    target = tmp_path / "caller_screening.yaml"
    target.write_text(text, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# The shipped file
# ---------------------------------------------------------------------------


def test_the_shipped_file_loads(shipped_screening_file: Path) -> None:
    """The data the repository ships is valid and complete (AGENT.md section 4.6)."""
    data = load_screening_data(shipped_screening_file)

    assert data.document.name == "sample-office-screening"
    assert data.document.window.max_calls >= 1
    assert data.document.window.seconds > 0
    assert data.document.reputation.half_life_seconds > 0
    assert data.block_entries(), "the shipped file must actually block something"
    assert data.allow_entries(), "the shipped file must actually exempt something"


def test_the_shipped_file_carries_no_address(shipped_screening_file: Path) -> None:
    """The data file holds policy only; the next hop comes from the environment.

    This is the deliberate answer to the rule-file-drift trap: the second AS has no
    second copy of an address to keep in step (REQ-F-016, ``docs/phase2-plan.md``
    section 6).
    """
    raw = shipped_screening_file.read_text(encoding="utf-8")
    document_fields = set(ScreeningDocument.model_fields)

    assert "127.0.0.1" not in raw
    assert "port:" not in raw
    assert "address" not in document_fields
    assert not {"next_hops", "sbc_peer", "listen"} & document_fields


def test_the_policy_is_derived_from_the_document(shipped_screening_file: Path) -> None:
    """The store's parameters are the document's, so one file configures both halves."""
    data = load_screening_data(shipped_screening_file)
    policy = data.policy

    assert policy.window_seconds == data.document.window.seconds
    assert policy.max_calls == data.document.window.max_calls
    assert policy.half_life_seconds == data.document.reputation.half_life_seconds
    assert policy.default_score == data.document.reputation.default_score
    assert policy.reject_penalty == data.document.reputation.reject_penalty
    assert policy.max_tracked_callers == data.document.reputation.max_tracked_callers
    assert data.reject_above_calls == data.document.window.max_calls
    assert data.reject_below_reputation == data.document.reputation.reject_below


def test_entries_get_identifiers_derived_from_file_order(shipped_screening_file: Path) -> None:
    """``BL-0001`` … and ``AL-0001`` … are what the trace and the console name."""
    data = load_screening_data(shipped_screening_file)

    assert [entry.entry_id for entry in data.block_entries()][:3] == [
        "BL-0001",
        "BL-0002",
        "BL-0003",
    ]
    assert [entry.entry_id for entry in data.allow_entries()] == ["AL-0001", "AL-0002"]


def test_the_shipped_file_matches_as_an_operator_would_expect(
    shipped_screening_file: Path,
) -> None:
    """Blocked numbers and prefixes match; unlisted callers match nothing."""
    data = load_screening_data(shipped_screening_file)

    blocked_number = data.match("+8613400000001")
    assert blocked_number.blocked_by is not None
    assert blocked_number.blocked_by.entry_id == "BL-0001"
    assert blocked_number.blocked_by.reason

    blocked_prefix = data.match("+861690000000")
    assert blocked_prefix.blocked_by is not None
    assert blocked_prefix.blocked_by.entry_id == "BL-0005"

    allowed_number = data.match("+86216180000")
    assert allowed_number.allowed_by is not None
    assert allowed_number.allowed_by.entry_id == "AL-0001"

    allowed_prefix = data.match("+86138001380123")
    assert allowed_prefix.allowed_by is not None
    assert allowed_prefix.allowed_by.entry_id == "AL-0002"

    unlisted = data.match("+8613500000000")
    assert unlisted.allowed_by is None
    assert unlisted.blocked_by is None


def test_an_exact_entry_wins_over_a_prefix_entry(tmp_path: Path) -> None:
    """A named party means it: exact numbers are evaluated before prefixes.

    Both entries below accept ``+8613400000001``; the exact one is written second to prove
    that file order alone does not decide.
    """
    path = write_document(
        tmp_path,
        block_list=(
            'block_list:\n  - prefix: "+8613"\n    reason: the whole range\n'
            '  - number: "+8613400000001"\n    reason: this handset\n'
        ),
    )
    data = load_screening_data(path)

    match = data.match("+8613400000001")

    assert match.blocked_by is not None
    assert match.blocked_by.entry_id == "BL-0002"
    assert match.blocked_by.reason == "this handset"


# ---------------------------------------------------------------------------
# Load-time validation, one rejection path at a time
# ---------------------------------------------------------------------------


def test_a_missing_file_is_as_fraud_004(tmp_path: Path) -> None:
    """A file that is not there is a configuration failure, not a traceback."""
    with pytest.raises(AsError) as raised:
        load_screening_data(tmp_path / "absent.yaml")

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_UNREADABLE
    assert raised.value.sip_status == 500


def test_invalid_yaml_is_as_fraud_005(tmp_path: Path) -> None:
    """Broken YAML is reported as a schema failure."""
    path = tmp_path / "caller_screening.yaml"
    path.write_text("window: [unclosed\n", encoding="utf-8")

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR


def test_an_entry_with_both_number_and_prefix_is_rejected(tmp_path: Path) -> None:
    """Exactly one form per entry: an ambiguous entry is a configuration error."""
    path = write_document(
        tmp_path,
        block_list=(
            'block_list:\n  - number: "+8613400000001"\n    prefix: "+8613"\n    reason: both\n'
        ),
    )

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR
    assert "number or prefix" in raised.value.detail


def test_an_entry_with_neither_number_nor_prefix_is_rejected(tmp_path: Path) -> None:
    """An entry that matches nothing is a mistake, not a harmless no-op."""
    path = write_document(
        tmp_path,
        block_list="block_list:\n  - reason: no matcher at all\n",
    )

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR


def test_a_duplicate_entry_inside_a_list_is_rejected(tmp_path: Path) -> None:
    """The same value twice makes the entry identifier ambiguous."""
    path = write_document(
        tmp_path,
        block_list=(
            'block_list:\n  - number: "+8613400000001"\n    reason: first\n'
            '  - number: "+8613400000001"\n    reason: again\n'
        ),
    )

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR
    assert "duplicate" in raised.value.detail


def test_a_value_in_both_lists_is_rejected(tmp_path: Path) -> None:
    """An allow-and-block the same caller is a precedence puzzle, not an outcome."""
    path = write_document(
        tmp_path,
        block_list='block_list:\n  - number: "+8613400000001"\n    reason: blocked\n',
        allow_list='allow_list:\n  - number: "+8613400000001"\n    reason: exempt\n',
    )

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR
    assert "both block_list and allow_list" in raised.value.detail


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ("seconds: 60", "seconds: 0"),
        ("max_calls: 3", "max_calls: 0"),
        ("half_life_seconds: 300", "half_life_seconds: 0"),
        ("max_tracked_callers: 100", "max_tracked_callers: 0"),
        ("reject_penalty: 40.0", "reject_penalty: -1"),
    ],
)
def test_unusable_window_and_reputation_values_are_rejected(
    tmp_path: Path, needle: str, replacement: str
) -> None:
    """A window of zero seconds or a negative penalty is not a policy, it is a typo."""
    path = tmp_path / "caller_screening.yaml"
    path.write_text(_DOCUMENT.replace(needle, replacement), encoding="utf-8")

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR


def test_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    """``extra=forbid``: a misspelled key must not be silently ignored."""
    path = tmp_path / "caller_screening.yaml"
    path.write_text(_DOCUMENT.replace("name: unit-screening", "nome: typo"), encoding="utf-8")

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR


def test_an_unsupported_version_is_rejected(tmp_path: Path) -> None:
    """The schema version is a literal, so a future file cannot be half-understood."""
    path = tmp_path / "caller_screening.yaml"
    path.write_text(_DOCUMENT.replace("version: 1", "version: 2"), encoding="utf-8")

    with pytest.raises(AsError) as raised:
        load_screening_data(path)

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR


# ---------------------------------------------------------------------------
# Fail-safe reload
# ---------------------------------------------------------------------------


def test_reload_is_a_no_op_while_the_file_is_unchanged(tmp_path: Path) -> None:
    """Polling costs one ``stat``, not one parse."""
    store = ScreeningDataStore(write_document(tmp_path))

    assert store.maybe_reload() is False


def test_reload_activates_a_changed_file(tmp_path: Path) -> None:
    """An operator edit takes effect without a restart (ADR-0004 pattern)."""
    path = write_document(tmp_path)
    store = ScreeningDataStore(path)
    assert store.current.match("+8613400000001").blocked_by is None

    path.write_text(
        _DOCUMENT.replace(
            "block_list: []",
            'block_list:\n  - number: "+8613400000001"\n    reason: edited\n',
        ),
        encoding="utf-8",
    )

    assert store.maybe_reload() is True
    match = store.current.match("+8613400000001")
    assert match.blocked_by is not None
    assert match.blocked_by.reason == "edited"


def test_a_broken_edit_keeps_the_previous_document(tmp_path: Path) -> None:
    """A broken edit cannot take the call path down: the old data stays active.

    The store raises so the caller can log ``AS-FRAUD-005``, and ``current`` still answers
    with the last good document.
    """
    path = write_document(
        tmp_path,
        block_list='block_list:\n  - number: "+8613400000001"\n    reason: still active\n',
    )
    store = ScreeningDataStore(path)
    before = store.current

    path.write_text("window: [unclosed\n", encoding="utf-8")

    with pytest.raises(AsError) as raised:
        store.maybe_reload()

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR
    assert store.current is before
    assert store.current.match("+8613400000001").blocked_by is not None


def test_a_deleted_file_keeps_the_previous_document(tmp_path: Path) -> None:
    """Losing the file is detected as a change and stays fail-safe."""
    path = write_document(tmp_path)
    store = ScreeningDataStore(path)
    before = store.current

    path.unlink()

    with pytest.raises(AsError) as raised:
        store.maybe_reload()

    assert raised.value.code is FraudErrorCode.FRAUD_DATA_UNREADABLE
    assert store.current is before
