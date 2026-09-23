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

"""Unit tests for trunk Route parsing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from as_app.route_header import parse_top_route_target

pytestmark = pytest.mark.unit


def _request(route_values: list[str]) -> Any:
    """Build a minimal sippy-like request with Route headers."""

    class _Body:
        def __init__(self, value: str) -> None:
            self._value = value

        def getCopy(self) -> str:
            return self._value

    return SimpleNamespace(
        getHFBodys=lambda name: [_Body(v) for v in route_values] if name == "route" else [],
    )


def test_top_route_target_is_parsed_from_the_first_entry() -> None:
    """The outbound leg follows the top Route entry (RFC 3261)."""
    request = _request(["<sip:127.0.0.1:15061;lr>"])
    assert parse_top_route_target(request) == ("127.0.0.1", 15061)


def test_top_route_target_uses_default_port_when_omitted() -> None:
    """A Route URI without a port falls back to the SIP default."""
    request = _request(["<sip:ssbc.operator.example;lr>"])
    assert parse_top_route_target(request, default_port=5060) == ("ssbc.operator.example", 5060)


def test_missing_route_returns_none() -> None:
    """Calls without a Route set keep the catalogue hop address."""
    assert parse_top_route_target(_request([])) is None
    assert parse_top_route_target(None) is None
