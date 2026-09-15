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

"""M0 baseline checks: layout, meta files, documentation set and CI layers.

These tests exist because the repository itself is a deliverable: the skeleton of
``AGENT.md`` section 5 and the documentation set of section 4.2 must not silently rot.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

META_FILES = (
    "AGENT.md",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "NOTICE",
    "LICENSE",
    "VERSION",
    "Makefile",
    ".env.example",
    ".gitignore",
    "pyproject.toml",
    "uv.lock",
)

REQUIRED_DIRECTORIES = ("config", "deploy", "docs", "src", "tests", "tools")

REQUIRED_DOCUMENTS = (
    "docs/README.md",
    "docs/requirements/functional-and-nonfunctional.md",
    "docs/architecture/hld.md",
    "docs/architecture/lld.md",
    "docs/operations/deployment.md",
    "docs/operations/runbook.md",
    "docs/operations/troubleshooting.md",
    "docs/acceptance/criteria.md",
    "docs/acceptance/report.md",
    "docs/demo-script.md",
    "docs/glossary.md",
    "docs/production-gaps.md",
    "docs/specs/index.md",
)

REQUIRED_ADRS = tuple(f"docs/architecture/adr/{number:04d}" for number in range(1, 7))

SOURCE_FILES_WITHOUT_FORBIDDEN_NAMES = ("src", "tests")

FORBIDDEN_MODULE_NAMES = {"util.py", "helper.py", "misc.py", "common.py", "tools.py"}


@pytest.mark.parametrize("relative_path", META_FILES)
def test_meta_file_exists(repo_root: Path, relative_path: str) -> None:
    """Every mandatory meta file is present (AGENT.md section 4.7)."""
    assert (repo_root / relative_path).is_file(), relative_path


@pytest.mark.parametrize("relative_path", REQUIRED_DIRECTORIES)
def test_top_level_directory_exists(repo_root: Path, relative_path: str) -> None:
    """The top level layout is exactly the one of AGENT.md section 4.1."""
    assert (repo_root / relative_path).is_dir(), relative_path


@pytest.mark.parametrize("relative_path", REQUIRED_DOCUMENTS)
def test_documentation_set_exists(repo_root: Path, relative_path: str) -> None:
    """The documentation baseline of AGENT.md section 4.2 is complete."""
    assert (repo_root / relative_path).is_file(), relative_path


@pytest.mark.parametrize("prefix", REQUIRED_ADRS)
def test_adr_exists(repo_root: Path, prefix: str) -> None:
    """ADR-0001 to ADR-0006 are written (AGENT.md section 4.5)."""
    assert any((repo_root / "docs/architecture/adr").glob(f"{Path(prefix).name}-*.md"))


def test_no_forbidden_module_names_in_source(repo_root: Path) -> None:
    """Domain naming: no util/helper/misc/common modules (AGENT.md section 4.3)."""
    for relative in SOURCE_FILES_WITHOUT_FORBIDDEN_NAMES:
        for path in (repo_root / relative).rglob("*.py"):
            assert path.name not in FORBIDDEN_MODULE_NAMES, str(path)


def test_source_files_carry_licence_header_and_docstring(repo_root: Path) -> None:
    """Every source file starts with the licence header and a module docstring."""
    for path in (repo_root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Licensed under the Apache License" in text, str(path)
        assert '"""' in text, str(path)


def test_ci_runs_the_gates_in_layers(repo_root: Path) -> None:
    """The CI workflow has the lint, type, unit, integration and e2e layers."""
    workflow = yaml.safe_load((repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    content = (repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "jobs" in workflow
    for job in ("lint", "type-check", "unit", "integration", "e2e"):
        assert job in content


def test_compose_defines_the_three_services(repo_root: Path) -> None:
    """The demo compose file runs as, s-sbc-mock and console with UDP ports."""
    compose = yaml.safe_load((repo_root / "deploy/docker-compose.yml").read_text(encoding="utf-8"))
    assert {"as", "s-sbc-mock", "console"} <= set(compose["services"])
    raw = (repo_root / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert "/udp" in raw


def test_version_file_matches_the_project_version(repo_root: Path) -> None:
    """``VERSION`` and the project version agree (AGENT.md section 4.7)."""
    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{version}"' in pyproject


def test_env_example_declares_every_configuration_knob(repo_root: Path) -> None:
    """All knobs of AGENT.md section 8 are declared in ``.env.example``."""
    content = (repo_root / ".env.example").read_text(encoding="utf-8")
    for knob in (
        "SIP_LISTEN_ADDRESS",
        "SIP_LISTEN_PORT",
        "SBC_PEER_ADDRESS",
        "SBC_PEER_PORT",
        "RULES_FILE",
        "ALLOWED_PEERS",
        "INTERNAL_API_ADDRESS",
        "INTERNAL_API_PORT",
        "LOG_LEVEL",
    ):
        assert knob in content, knob
