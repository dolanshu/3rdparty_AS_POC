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

"""The declarative screening-data file (``docs/architecture/lld.md`` section 9.4).

Block/allow lists, the reputation parameters and the call-rate window parameters are data,
not code: they are validated on load and reloaded when the file changes. Reload is
pull-based and fail-safe exactly like the routing rules (ADR-0004) — a broken edit keeps the
previous document active and cannot take the call path down.

The file carries **no addresses**: the next hop comes from the environment
(``FRAUD_SBC_PEER_*``), so there is no environment-specific copy of an address to drift from
(``docs/phase2-plan.md`` section 6, "Rule-file drift").

Entry identifiers are derived from file order — ``BL-0001`` … for ``block_list``,
``AL-0001`` … for ``allow_list`` — so the file stays a plain operator list while the trace
and the console still name the entry that matched.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from anti_fraud_as.caller_state import WindowPolicy
from anti_fraud_as.errors import AsError, FraudErrorCode

__all__ = [
    "CallRateWindowConfig",
    "ListMatch",
    "ListMatchResult",
    "ReputationConfig",
    "ScreenedNumber",
    "ScreeningData",
    "ScreeningDataStore",
    "ScreeningDocument",
    "load_screening_data",
]


class ScreenedNumber(BaseModel):
    """One entry of the block list or the allow list.

    Attributes:
        number: Exact called party this entry matches; exactly one of number/prefix is set.
        prefix: Number prefix this entry matches; exactly one of number/prefix is set.
        reason: Operator-supplied reason, shown in the trace and the console.
        description: Free text describing the range, for the console.
    """

    model_config = ConfigDict(extra="forbid")

    number: str | None = None
    prefix: str | None = None
    reason: str = ""
    description: str = ""

    @model_validator(mode="after")
    def _require_exactly_one_form(self) -> ScreenedNumber:
        """Reject an entry that names both a number and a prefix, or neither.

        Returns:
            The validated entry.

        Raises:
            ValueError: If the entry does not carry exactly one usable form.
        """
        has_number = bool(self.number and self.number.strip())
        has_prefix = bool(self.prefix and self.prefix.strip())
        if has_number == has_prefix:
            raise ValueError("a screened number needs exactly one of number or prefix")
        return self

    @property
    def value(self) -> str:
        """Return the number or prefix this entry matches on."""
        return (self.number or self.prefix or "").strip()

    @property
    def is_prefix(self) -> bool:
        """Return whether this entry matches by prefix."""
        return bool(self.prefix and self.prefix.strip())


class CallRateWindowConfig(BaseModel):
    """Call-rate window parameters of the data file.

    Attributes:
        seconds: Length of the window.
        max_calls: A caller is rejected above this many calls inside the window.
    """

    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(gt=0)
    max_calls: int = Field(ge=1)


class ReputationConfig(BaseModel):
    """Reputation parameters of the data file.

    Attributes:
        half_life_seconds: Time in which a deviation from the default score halves.
        default_score: Score a caller starts at and decays back towards.
        reject_below: Reject when the effective score is below this value.
        reject_penalty: Score removed by one rejected call.
        max_tracked_callers: Upper bound on the callers kept in memory.
    """

    model_config = ConfigDict(extra="forbid")

    half_life_seconds: float = Field(gt=0)
    default_score: float = 100.0
    reject_below: float = 30.0
    reject_penalty: float = Field(default=40.0, ge=0)
    max_tracked_callers: int = Field(default=1000, ge=1)


class ScreeningDocument(BaseModel):
    """The complete screening-data file.

    Attributes:
        version: Schema version of the file.
        name: Name of the data set.
        description: Purpose of the data set.
        window: Call-rate window parameters.
        reputation: Reputation parameters.
        block_list: Entries that make a call rejected.
        allow_list: Entries that always make a call allowed.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    name: str
    description: str = ""
    window: CallRateWindowConfig
    reputation: ReputationConfig
    block_list: list[ScreenedNumber] = Field(default_factory=list)
    allow_list: list[ScreenedNumber] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_lists(self) -> ScreeningDocument:
        """Check identifier uniqueness inside a list and disjointness across the two.

        Returns:
            The validated document.

        Raises:
            ValueError: If an entry is duplicated inside a list, or appears in both lists.
        """
        blocked = [entry.value for entry in self.block_list]
        allowed = [entry.value for entry in self.allow_list]
        if len(blocked) != len(set(blocked)):
            raise ValueError("duplicate entry in block_list")
        if len(allowed) != len(set(allowed)):
            raise ValueError("duplicate entry in allow_list")
        overlap = sorted(set(blocked) & set(allowed))
        if overlap:
            raise ValueError(f"entries appear in both block_list and allow_list: {overlap}")
        return self

    @property
    def policy(self) -> WindowPolicy:
        """Return the cross-call state parameters this document asks for."""
        return WindowPolicy(
            window_seconds=self.window.seconds,
            max_calls=self.window.max_calls,
            half_life_seconds=self.reputation.half_life_seconds,
            default_score=self.reputation.default_score,
            reject_penalty=self.reputation.reject_penalty,
            max_tracked_callers=self.reputation.max_tracked_callers,
        )


@dataclass(frozen=True)
class ListMatch:
    """A matched block-list or allow-list entry.

    Attributes:
        entry_id: Derived identifier, ``BL-0001`` / ``AL-0001`` by file order.
        value: The number or prefix that matched.
        reason: Operator-supplied reason for the entry.
    """

    entry_id: str
    value: str
    reason: str


@dataclass(frozen=True)
class ListMatchResult:
    """The list entries one calling number matched.

    Attributes:
        allowed_by: Matched allow-list entry, when one matched.
        blocked_by: Matched block-list entry, when one matched.
    """

    allowed_by: ListMatch | None = None
    blocked_by: ListMatch | None = None


class ScreeningData:
    """A loaded screening document with the list indices built once.

    Attributes:
        document: The validated screening document.
        source: Path the document was read from.
    """

    def __init__(self, document: ScreeningDocument, source: Path) -> None:
        """Build the match indices of a validated document.

        Args:
            document: Validated screening document.
            source: Path the document was read from.
        """
        self.document = document
        self.source = source
        self._block = _index(document.block_list, "BL")
        self._allow = _index(document.allow_list, "AL")

    @property
    def policy(self) -> WindowPolicy:
        """Return the cross-call state parameters of this document."""
        return self.document.policy

    @property
    def reject_above_calls(self) -> int:
        """Return the call count above which a caller is rejected."""
        return self.document.window.max_calls

    @property
    def reject_below_reputation(self) -> float:
        """Return the score below which a caller is rejected."""
        return self.document.reputation.reject_below

    def block_entries(self) -> list[ListMatch]:
        """Return the block-list entries with their derived identifiers."""
        return [entry for entry, _ in self._block]

    def allow_entries(self) -> list[ListMatch]:
        """Return the allow-list entries with their derived identifiers."""
        return [entry for entry, _ in self._allow]

    def match(self, calling_number: str) -> ListMatchResult:
        """Return the list entries a calling number matches.

        Exact ``number`` entries are evaluated before ``prefix`` entries, and within each
        group file order decides — an operator who names a specific party means it.

        Args:
            calling_number: Calling party of the call.

        Returns:
            The matched allow-list and block-list entries, either may be ``None``.
        """
        return ListMatchResult(
            allowed_by=_match(self._allow, calling_number),
            blocked_by=_match(self._block, calling_number),
        )


def _index(entries: list[ScreenedNumber], prefix: str) -> list[tuple[ListMatch, bool]]:
    """Index a list of screened numbers with derived identifiers.

    Args:
        entries: Entries of one list, in file order.
        prefix: Identifier prefix, ``BL`` or ``AL``.

    Returns:
        One ``(match, is_prefix)`` pair per entry.
    """
    return [
        (
            ListMatch(entry_id=f"{prefix}-{position:04d}", value=entry.value, reason=entry.reason),
            entry.is_prefix,
        )
        for position, entry in enumerate(entries, start=1)
    ]


def _match(index: list[tuple[ListMatch, bool]], calling_number: str) -> ListMatch | None:
    """Return the first entry of an index that accepts a calling number.

    Args:
        index: Index built by :func:`_index`.
        calling_number: Calling party of the call.

    Returns:
        The matched entry, or ``None`` when nothing matched.
    """
    for entry, is_prefix in index:
        if not is_prefix and entry.value == calling_number:
            return entry
    for entry, is_prefix in index:
        if is_prefix and calling_number.startswith(entry.value):
            return entry
    return None


def load_screening_data(path: str | Path) -> ScreeningData:
    """Read and validate a screening-data file.

    Args:
        path: Path to the YAML screening-data file.

    Returns:
        The loaded screening data.

    Raises:
        AsError: ``AS-FRAUD-004`` when the file cannot be read, ``AS-FRAUD-005`` when it is
            not valid YAML or violates the schema.
    """
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise AsError(
            FraudErrorCode.FRAUD_DATA_UNREADABLE,
            f"cannot read screening data: {exc}",
            context={"screening_file": str(source)},
        ) from exc
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AsError(
            FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR,
            f"screening data is not valid YAML: {exc}",
            context={"screening_file": str(source)},
        ) from exc
    try:
        document = ScreeningDocument.model_validate(parsed)
    except Exception as exc:  # pydantic raises ValidationError with a long message
        raise AsError(
            FraudErrorCode.FRAUD_DATA_SCHEMA_ERROR,
            f"screening data violates the schema: {exc}",
            context={"screening_file": str(source)},
        ) from exc
    return ScreeningData(document, source)


class ScreeningDataStore:
    """Hold the active screening data and detect file changes for reload (ADR-0004).

    Reload is pull-based: the sippy thread must not be blocked by file I/O, so the process
    that owns the main loop decides when to poll. It is fail-safe: a broken edit raises
    ``AS-FRAUD-005`` and the previous document stays active.
    """

    def __init__(self, path: str | Path) -> None:
        """Load the screening data eagerly.

        Args:
            path: Path to the YAML screening-data file.
        """
        self.path = Path(path)
        self.current = load_screening_data(self.path)
        self._fingerprint = self._stat()

    def _stat(self) -> tuple[int, int] | None:
        """Return the current file fingerprint.

        Returns:
            A tuple of size and modification time, or ``None`` when the file is gone.
        """
        try:
            info = os.stat(self.path)
        except OSError:
            return None
        return (info.st_size, info.st_mtime_ns)

    def maybe_reload(self) -> bool:
        """Reload the screening data when the file changed on disk.

        Returns:
            ``True`` when a new document was activated.

        Raises:
            AsError: Propagated from :func:`load_screening_data`; the previous document
                stays active so a broken edit never takes the service down.
        """
        fingerprint = self._stat()
        if fingerprint == self._fingerprint:
            return False
        self.current = load_screening_data(self.path)
        self._fingerprint = fingerprint
        return True
