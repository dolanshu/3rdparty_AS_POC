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

"""Unit tests for routing rule loading, validation and reload detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from as_app.errors import AsError, AsErrorCode
from as_app.routing.rules import RuleSetStore, load_rule_set

pytestmark = pytest.mark.unit

MINIMAL_DOCUMENT = """
version: 1
name: test
next_hops:
  - name: hop-a
    address: 127.0.0.1
    port: 15061
    priority: 2
  - name: hop-b
    address: 127.0.0.1
    port: 15062
    priority: 1
rules:
  - rule_id: R-LOW
    priority: 200
    match:
      called_prefixes: ["0"]
    action:
      kind: route
      translate:
        to_format: national
      next_hops: [hop-b]
  - rule_id: R-HIGH
    priority: 10
    match:
      called_numbers: ["110"]
    action:
      kind: route
      translate:
        to_format: short_code
      next_hops: [hop-a, hop-b]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_rule_set_loads_and_meets_sample_data_scale(rule_set) -> None:
    """The shipped rule set loads and satisfies AGENT.md section 4.6."""
    rules = rule_set.document.rules
    assert 10 <= len(rules) <= 20
    assert len({rule.rule_id for rule in rules}) == len(rules)
    assert len(rule_set.document.next_hops) >= 2
    routed = [rule for rule in rules if rule.action.kind == "route"]
    assert any(len(rule.action.next_hops) >= 2 for rule in routed)


def test_rules_are_ordered_by_priority(rule_set) -> None:
    """Evaluation order follows priority, not file order."""
    priorities = [rule.priority for rule in rule_set.ordered_rules]
    assert priorities == sorted(priorities)


def test_disabled_rules_are_not_evaluated(tmp_path: Path) -> None:
    """A disabled rule is present in the document but absent from evaluation order."""
    document = MINIMAL_DOCUMENT.replace(
        "  - rule_id: R-HIGH\n    priority: 10\n",
        "  - rule_id: R-HIGH\n    priority: 10\n    enabled: false\n",
    )
    rule_set = load_rule_set(_write(tmp_path, document))
    assert [rule.rule_id for rule in rule_set.ordered_rules] == ["R-LOW"]
    assert [rule.rule_id for rule in rule_set.document.rules] == ["R-LOW", "R-HIGH"]


def test_duplicate_rule_identifier_is_rejected(tmp_path: Path) -> None:
    """Two rules with the same identifier fail validation with AS-RULE-003."""
    document = MINIMAL_DOCUMENT.replace("rule_id: R-HIGH", "rule_id: R-LOW")
    with pytest.raises(AsError) as excinfo:
        load_rule_set(_write(tmp_path, document))
    assert excinfo.value.code is AsErrorCode.RULE_SCHEMA_ERROR


def test_unknown_next_hop_reference_is_rejected(tmp_path: Path) -> None:
    """A rule pointing at an undefined next hop fails validation."""
    document = MINIMAL_DOCUMENT.replace("next_hops: [hop-b]", "next_hops: [hop-missing]")
    with pytest.raises(AsError) as excinfo:
        load_rule_set(_write(tmp_path, document))
    assert excinfo.value.code is AsErrorCode.RULE_SCHEMA_ERROR


def test_missing_file_raises_rule_file_unreadable(tmp_path: Path) -> None:
    """A rules file that does not exist reports AS-RULE-001."""
    with pytest.raises(AsError) as excinfo:
        load_rule_set(tmp_path / "absent.yaml")
    assert excinfo.value.code is AsErrorCode.RULE_FILE_UNREADABLE


def test_invalid_yaml_raises_rule_parse_error(tmp_path: Path) -> None:
    """Broken YAML reports AS-RULE-002."""
    with pytest.raises(AsError) as excinfo:
        load_rule_set(_write(tmp_path, "version: 1\nname: [\n"))
    assert excinfo.value.code is AsErrorCode.RULE_PARSE_ERROR


def test_next_hops_are_resolved_by_priority(tmp_path: Path) -> None:
    """Next hops of a rule are returned best first, by ascending priority."""
    rule_set = load_rule_set(_write(tmp_path, MINIMAL_DOCUMENT))
    rule = next(rule for rule in rule_set.ordered_rules if rule.rule_id == "R-HIGH")
    assert [hop.name for hop in rule_set.next_hops_for(rule)] == ["hop-b", "hop-a"]


def test_unknown_next_hop_lookup_raises_route_error(tmp_path: Path) -> None:
    """Resolving an undefined next hop at runtime reports AS-ROUTE-003."""
    rule_set = load_rule_set(_write(tmp_path, MINIMAL_DOCUMENT))
    with pytest.raises(AsError) as excinfo:
        rule_set.next_hop("hop-missing")
    assert excinfo.value.code is AsErrorCode.ROUTE_NO_NEXT_HOP


def test_store_reloads_when_the_file_changes(tmp_path: Path) -> None:
    """The store activates a new rule set when the file changes on disk."""
    path = _write(tmp_path, MINIMAL_DOCUMENT)
    store = RuleSetStore(path)
    assert store.maybe_reload() is False

    path.write_text(MINIMAL_DOCUMENT.replace("name: test", "name: test-2"), encoding="utf-8")
    assert store.maybe_reload() is True
    assert store.current.document.name == "test-2"
    assert store.maybe_reload() is False


def test_store_keeps_previous_rule_set_when_reload_fails(tmp_path: Path) -> None:
    """A broken edit leaves the previous rule set in place instead of failing later."""
    path = _write(tmp_path, MINIMAL_DOCUMENT)
    store = RuleSetStore(path)
    path.write_text("version: 1\nname: [", encoding="utf-8")
    with pytest.raises(AsError):
        store.maybe_reload()
    assert store.current.document.name == "test"
