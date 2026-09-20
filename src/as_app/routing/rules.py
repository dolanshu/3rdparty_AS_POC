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

"""Routing rule model, YAML loading and reload detection.

The rule set is data, not code: it lives in ``config/routing_rules.yaml`` and can be
changed without touching the application (ADR-0004). The console only ever displays
rules; it never edits them (``AGENT.md`` section 1).
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from as_platform.hop import NextHop
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from as_app.errors import AsError, AsErrorCode

__all__ = [
    "MatchCriteria",
    "NextHop",
    "NumberFormat",
    "NumberTranslation",
    "RejectAction",
    "RouteAction",
    "RoutingRule",
    "RoutingRulesDocument",
    "RuleAction",
    "RuleSet",
    "RuleSetStore",
    "load_rule_set",
]

RuleId = Annotated[str, StringConstraints(pattern=r"^R-[A-Z0-9]{3,8}(-[A-Z0-9]{1,12})*$")]


class NumberFormat(str, Enum):
    """Number format recognised on the trunk.

    E.164 is the canonical form for routing; the other three are the local forms that an
    office PBX or a national core actually dials.
    """

    E164 = "e164"
    NATIONAL = "national"
    SHORT_CODE = "short_code"
    INTERNATIONAL = "international"


class NumberTranslation(BaseModel):
    """How the called number is rewritten before the outbound INVITE is originated.

    Attributes:
        to_format: Format the number has after the translation.
        strip_prefix: Prefix removed from the number, if present.
        prepend: Digits inserted in front of the remaining number.
    """

    model_config = ConfigDict(extra="forbid")

    to_format: NumberFormat
    strip_prefix: str = ""
    prepend: str = ""


class MatchCriteria(BaseModel):
    """Conditions a called number must satisfy for a rule to match.

    Attributes:
        called_prefixes: The called number must start with one of these digit strings.
        called_numbers: The called number must equal one of these (short codes).
        number_format: If set, the number must already be in this format.
        description: Free text explaining the number range, shown in the console.
    """

    model_config = ConfigDict(extra="forbid")

    called_prefixes: list[str] = Field(default_factory=list)
    called_numbers: list[str] = Field(default_factory=list)
    number_format: NumberFormat | None = None
    description: str = ""

    @model_validator(mode="after")
    def _require_condition(self) -> MatchCriteria:
        """Reject a match block that would match everything by accident.

        Returns:
            The validated criteria.

        Raises:
            ValueError: If neither prefixes, exact numbers nor a format are given.
        """
        if not self.called_prefixes and not self.called_numbers and self.number_format is None:
            raise ValueError("a match block needs called_prefixes, called_numbers or number_format")
        return self


class RouteAction(BaseModel):
    """Route the call: translate the number and pick a next hop.

    Attributes:
        kind: Discriminator of the action union.
        translate: Number rewriting applied to the called number.
        next_hops: Names into the document-level next hop catalogue, best first.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["route"] = "route"
    translate: NumberTranslation
    next_hops: list[str] = Field(min_length=1)


class RejectAction(BaseModel):
    """Reject the call with a policy decision, typically ``603 Decline``.

    Attributes:
        kind: Discriminator of the action union.
        status: SIP status code sent back on the trunk.
        reason: Human readable reason, logged and shown in the console.
        error_code: Internal error code from :mod:`as_app.errors`.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["reject"] = "reject"
    status: int = Field(default=603, ge=300, le=699)
    reason: str = "rejected by routing policy"
    error_code: str = AsErrorCode.ROUTE_REJECTED.code


RuleAction = Annotated[RouteAction | RejectAction, Field(discriminator="kind")]


class RoutingRule(BaseModel):
    """One routing rule.

    Attributes:
        rule_id: Stable identifier such as ``R-010``, unique in the document.
        priority: Evaluation order, lower is evaluated first.
        description: What this rule is for.
        enabled: Disabled rules are skipped during matching.
        match: Conditions on the called number.
        action: What to do when the rule matches.
        tags: Free-form labels, for example the operator or the service type.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: RuleId
    priority: int = Field(default=100, ge=0)
    description: str = ""
    enabled: bool = True
    match: MatchCriteria
    action: RuleAction
    tags: list[str] = Field(default_factory=list)


class RoutingRulesDocument(BaseModel):
    """The complete routing rules file.

    Attributes:
        version: Schema version of the file.
        name: Name of the rule set.
        description: Purpose of the rule set.
        next_hops: Catalogue of peers a rule may select.
        rules: The rules, in file order; evaluation order comes from ``priority``.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    name: str
    description: str = ""
    next_hops: list[NextHop] = Field(min_length=1)
    rules: list[RoutingRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_references(self) -> RoutingRulesDocument:
        """Check rule identifier uniqueness and next hop references.

        Returns:
            The validated document.

        Raises:
            ValueError: If an identifier is duplicated or a next hop is unknown.
        """
        seen: set[str] = set()
        for rule in self.rules:
            if rule.rule_id in seen:
                raise ValueError(f"duplicate rule identifier: {rule.rule_id}")
            seen.add(rule.rule_id)
        catalogue = {hop.name for hop in self.next_hops}
        for rule in self.rules:
            if isinstance(rule.action, RouteAction):
                missing = sorted(set(rule.action.next_hops) - catalogue)
                if missing:
                    raise ValueError(f"rule {rule.rule_id} references unknown next hops: {missing}")
        return self


class RuleSet:
    """A loaded rule set with pre-resolved next hops and evaluation order.

    Attributes:
        document: The validated rules document.
        source: Path the rule set was loaded from.
    """

    def __init__(self, document: RoutingRulesDocument, source: Path) -> None:
        """Create a rule set view.

        Args:
            document: Validated rules document.
            source: Path the document was read from.
        """
        self.document = document
        self.source = source
        self._next_hops: dict[str, NextHop] = {hop.name: hop for hop in document.next_hops}
        self._ordered: list[RoutingRule] = sorted(
            (rule for rule in document.rules if rule.enabled),
            key=lambda rule: (rule.priority, rule.rule_id),
        )

    @property
    def ordered_rules(self) -> list[RoutingRule]:
        """Enabled rules in evaluation order.

        Returns:
            Rules ordered by ascending priority, then by identifier.
        """
        return list(self._ordered)

    def next_hop(self, name: str) -> NextHop:
        """Resolve a next hop by name.

        Args:
            name: Next hop name from the catalogue.

        Returns:
            The next hop definition.

        Raises:
            AsError: ``AS-ROUTE-003`` when the name is not in the catalogue.
        """
        try:
            return self._next_hops[name]
        except KeyError as exc:
            raise AsError(
                AsErrorCode.ROUTE_NO_NEXT_HOP,
                f"unknown next hop: {name}",
                context={"next_hop": name},
            ) from exc

    def next_hops_for(self, rule: RoutingRule) -> list[NextHop]:
        """Return the next hops of a route action, best first.

        Args:
            rule: The matched rule; its action must be a :class:`RouteAction`.

        Returns:
            Next hops ordered by ascending priority.
        """
        if not isinstance(rule.action, RouteAction):
            return []
        hops = [self.next_hop(name) for name in rule.action.next_hops]
        return sorted(hops, key=lambda hop: (hop.priority, hop.name))


def load_rule_set(path: str | Path) -> RuleSet:
    """Read and validate a routing rules file.

    Args:
        path: Path to a YAML rules file.

    Returns:
        The loaded rule set.

    Raises:
        AsError: ``AS-RULE-001`` when the file cannot be read, ``AS-RULE-002`` when it is
            not valid YAML, ``AS-RULE-003`` when it violates the schema.
    """
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise AsError(
            AsErrorCode.RULE_FILE_UNREADABLE,
            f"cannot read routing rules: {exc}",
            context={"rules_file": str(source)},
        ) from exc
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AsError(
            AsErrorCode.RULE_PARSE_ERROR,
            f"routing rules are not valid YAML: {exc}",
            context={"rules_file": str(source)},
        ) from exc
    try:
        document = RoutingRulesDocument.model_validate(parsed)
    except Exception as exc:  # pydantic raises ValidationError with a long message
        raise AsError(
            AsErrorCode.RULE_SCHEMA_ERROR,
            f"routing rules violate the schema: {exc}",
            context={"rules_file": str(source)},
        ) from exc
    return RuleSet(document, source)


class RuleSetStore:
    """Holds the active rule set and detects file changes for reload (ADR-0004).

    Reload is pull-based: the sippy thread cannot be blocked by file I/O, so the polling
    decision is taken from the process that owns the main loop.
    """

    def __init__(self, path: str | Path) -> None:
        """Load the rule set eagerly.

        Args:
            path: Path to the YAML rules file.
        """
        self.path = Path(path)
        self.current = load_rule_set(self.path)
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
        """Reload the rule set when the file changed on disk.

        Returns:
            ``True`` when a new rule set was activated.

        Raises:
            AsError: Propagated from :func:`load_rule_set`; the previous rule set stays
                active so a broken edit never takes the service down.
        """
        fingerprint = self._stat()
        if fingerprint == self._fingerprint:
            return False
        self.current = load_rule_set(self.path)
        self._fingerprint = fingerprint
        return True
