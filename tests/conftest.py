# Copyright 2026 the 3rd-party AS POC authors.
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

"""Shared fixtures for the unit, integration and e2e layers.

All UDP ports used by tests are allocated dynamically, so parallel runs and CI never
collide on 5060 (``AGENT.md`` section 11).
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = REPO_ROOT / "config" / "routing_rules.yaml"


def pytest_configure(config: pytest.Config) -> None:
    """Register the three test layers as markers.

    Args:
        config: The pytest configuration object.
    """
    config.addinivalue_line("markers", "unit: pure logic, no sockets")
    config.addinivalue_line("markers", "integration: AS and mock on localhost UDP")
    config.addinivalue_line("markers", "e2e: complete call flows including error branches")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root.

    Returns:
        Absolute path of the repository root.
    """
    return REPO_ROOT


@pytest.fixture(scope="session")
def rules_file() -> Path:
    """Return the path of the shipped sample rule set.

    Returns:
        Path of ``config/routing_rules.yaml``.
    """
    return RULES_FILE


@pytest.fixture
def rule_set(rules_file: Path):
    """Load the shipped sample rule set.

    Args:
        rules_file: Path of the rules file.

    Returns:
        The loaded :class:`~as_app.routing.rules.RuleSet`.
    """
    from as_app.routing.rules import load_rule_set

    return load_rule_set(rules_file)


@pytest.fixture
def free_udp_port() -> int:
    """Reserve a free UDP port for the duration of a test.

    Returns:
        A port number that was free when the fixture ran.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
