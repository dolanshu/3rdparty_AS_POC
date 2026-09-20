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

"""M0 baseline checks: layout, meta files, documentation set and CI layers.

These tests exist because the repository itself is a deliverable: the skeleton of
``AGENT.md`` section 5 and the documentation set of section 4.2 must not silently rot.
"""

from __future__ import annotations

import importlib.metadata
import re
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
    "docs/demo-steps.md",
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


def test_runtime_version_matches_the_version_file(repo_root: Path) -> None:
    """``as_app.__version__`` is derived from ``VERSION`` and cannot drift (M4).

    The AS serves this value on ``/healthz`` and writes it to the ``application server
    starting`` log line, so it must equal the released version rather than a hardcoded
    string. It was ``0.1.0`` while ``VERSION`` had advanced to ``0.4.0`` until M4.
    """
    import as_app

    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    assert as_app.__version__ == version


def test_runtime_version_is_not_the_unknown_placeholder() -> None:
    """``as_app.__version__`` is a real version, never ``0.0.0+unknown`` (P5).

    ``_UNKNOWN_VERSION`` is what an installed wheel used to report because it ships no
    ``VERSION`` file. The distribution metadata branch now answers first, so the runtime
    version is resolved in this environment — editable install or source checkout alike.
    """
    import as_app

    assert as_app.__version__ != as_app._UNKNOWN_VERSION
    assert as_app.__version__ == importlib.metadata.version(as_app._DISTRIBUTION_NAME)


def test_runtime_version_falls_back_to_the_version_file_when_metadata_is_missing(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VERSION`` file is used when the distribution metadata cannot be read (P5).

    A source checkout run without an install has no ``third-party-as-poc`` distribution, so
    ``importlib.metadata.version`` raises ``PackageNotFoundError`` and the chain must fall
    through to ``VERSION`` rather than to ``_UNKNOWN_VERSION``.
    """
    import as_app

    real_version = importlib.metadata.version

    def raising_version(distribution_name: str) -> str:
        if distribution_name == as_app._DISTRIBUTION_NAME:
            raise importlib.metadata.PackageNotFoundError(distribution_name)
        return real_version(distribution_name)

    monkeypatch.setattr(importlib.metadata, "version", raising_version)

    expected = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    assert as_app._read_version() == expected
    assert as_app._read_version() != as_app._UNKNOWN_VERSION


def test_runtime_version_is_unknown_when_no_version_source_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_UNKNOWN_VERSION`` is the last resort when both sources are unavailable (P5).

    This is the state the chain exists to avoid: no distribution metadata *and* no
    ``VERSION`` file. It is reached only by a broken install, and it stays the honest
    answer instead of a fabricated version.
    """
    import as_app

    def raising_version(distribution_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(distribution_name)

    monkeypatch.setattr(importlib.metadata, "version", raising_version)
    monkeypatch.setattr(as_app, "_version_file_version", lambda: as_app._UNKNOWN_VERSION)

    assert as_app._read_version() == as_app._UNKNOWN_VERSION


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


#: Package the number-translation AS must never depend on: chaining is configuration only
#: and the two AS instances stay independent processes (REQ-F-026, ADR-0008 decision 1).
FORBIDDEN_AS_APP_IMPORT = "anti_fraud_as"

#: Documents that must name the chain's first-class run command (REQ-NF-017).
DEMO_CHAINED_DOCUMENTS = ("AGENT.md", "README.md", "docs/README.md", "tools/README.md")


def imports_module(text: str, module: str) -> bool:
    """Tell whether a Python source imports a module, in any of the import forms.

    Args:
        text: The source file content.
        module: The dotted top-level module name to look for.

    Returns:
        ``True`` for ``import module``, ``import module.sub``, ``from module import x`` and
        ``from module.sub import x``, including indented imports inside functions.
    """
    pattern = re.compile(rf"^\s*(?:import|from)\s+{re.escape(module)}(?:\s|\.|$)", re.MULTILINE)
    return pattern.search(text) is not None


def test_as_app_does_not_import_the_anti_fraud_as(repo_root: Path) -> None:
    """The two AS instances stay independent: AS-1 is never imported by AS-2 (REQ-F-026).

    The reverse direction is by design — ``anti_fraud_as`` reuses ``as_app``'s
    use-case-agnostic modules (ADR-0007 decision 9) — so only the forbidden direction is
    asserted. The chain is configuration only, and a shared import would couple the two
    processes and break that premise.
    """
    offenders = [
        str(path)
        for path in (repo_root / "src/as_app").rglob("*.py")
        if imports_module(path.read_text(encoding="utf-8"), FORBIDDEN_AS_APP_IMPORT)
    ]
    assert not offenders, "src/as_app must not import anti_fraud_as (REQ-F-026): " + ", ".join(
        offenders
    )


def test_make_demo_chained_is_a_documented_first_class_entry_point(repo_root: Path) -> None:
    """``make demo-chained`` is a real target and is documented (REQ-NF-017).

    The command is the chain's first-class entry point, mirroring ``make demo`` /
    ``make demo-fraud`` (ADR-0008 decision 6). The assertion pins the command name in the
    ``Makefile`` and in the four documents that must carry it — not the prose around it.
    """
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^demo-chained:", makefile, re.MULTILINE), (
        "the Makefile has no `demo-chained` target"
    )
    for relative in DEMO_CHAINED_DOCUMENTS:
        assert "demo-chained" in (repo_root / relative).read_text(encoding="utf-8"), (
            f"`make demo-chained` is not named in {relative}"
        )


def test_chaining_added_no_new_configuration_knob(repo_root: Path) -> None:
    """The chained wiring reuses the existing peer/listen knobs (REQ-NF-017).

    P9 added no environment variable: AS-1's next hop is the existing ``FRAUD_SBC_PEER_*``
    and AS-2's is the routing catalogue (ADR-0008 decision 1), so ``.env.example`` gained no
    key for the chain. Only the absence of a chaining knob is asserted.
    """
    content = (repo_root / ".env.example").read_text(encoding="utf-8")
    declared = {
        line.split("=", 1)[0].strip()
        for line in content.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    chaining_keys = sorted(key for key in declared if "chain" in key.lower())
    assert not chaining_keys, f"chaining introduced new configuration keys: {chaining_keys}"


#: The library distribution, its import package and the sibling checkout it is consumed from
#: (REQ-F-029, REQ-F-032, ADR-0009 decisions 1 and 6).
LIBRARY_DISTRIBUTION = "as-platform"
LIBRARY_MODULE = "as_platform"
LIBRARY_SOURCE_PATH = "../as_platform"

#: The two application packages that consume the library and stay its reference implementation.
APPLICATION_PACKAGES = ("as_app", "anti_fraud_as")


def test_the_library_is_consumed_from_the_sibling_checkout(repo_root: Path) -> None:
    """``as-platform`` is an editable ``path`` dependency on ``../as_platform`` (REQ-F-032).

    The library is a separate repository checked out beside this one and consumed through the
    ``path`` source of ADR-0009 decision 6 — never a registry dependency, so a
    single-repository checkout cannot resolve it. ``editable = true`` is load-bearing rather
    than cosmetic: it links the sibling checkout instead of installing a copy, which is what
    lets the staged extraction edit the library and immediately run this repository's gate
    against the edit.
    """
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    runtime = re.search(r"^dependencies = \[(.*?)^\]", text, re.DOTALL | re.MULTILINE)
    assert runtime is not None, "the runtime dependencies are missing from pyproject.toml"
    assert LIBRARY_DISTRIBUTION in re.findall(r'"([^"]+)"', runtime.group(1))

    sources = re.search(r"^\[tool\.uv\.sources\]\n(.*?)(?=^\[|\Z)", text, re.DOTALL | re.MULTILINE)
    assert sources is not None, "[tool.uv.sources] is missing from pyproject.toml"
    entry = re.search(
        rf"^{re.escape(LIBRARY_DISTRIBUTION)}\s*=\s*\{{(.*)\}}", sources.group(1), re.MULTILINE
    )
    assert entry is not None, "as-platform has no path source (ADR-0009 decision 6)"
    source = entry.group(1)
    assert re.search(rf'path\s*=\s*"{re.escape(LIBRARY_SOURCE_PATH)}"', source), source
    assert re.search(r"editable\s*=\s*true", source), source


def test_the_library_is_not_a_uv_workspace_member(repo_root: Path) -> None:
    """The sibling checkout is a `path` dependency, never a uv workspace member (REQ-NF-019).

    LLD section 11.1 states that neither manifest declares the other a
    `[tool.uv.workspace]` member; this asserts this repository's half. A workspace member is
    resolved by one shared lock and one root, so the library's gate (REQ-NF-021) would no
    longer be the gate of a standalone distribution.
    """
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.uv.workspace]" not in text, "the library must not be a uv workspace member"


def test_both_as_instances_are_users_of_the_platform_library(repo_root: Path) -> None:
    """Both AS instances consume the extracted skeleton (REQ-F-029).

    The shared shell lives in the ``as_platform`` library and this repository is its
    reference implementation, so each application package imports the library rather than
    carrying a private copy of the shell the extraction moved out.
    """
    for package in APPLICATION_PACKAGES:
        consumed = any(
            imports_module(path.read_text(encoding="utf-8"), LIBRARY_MODULE)
            for path in (repo_root / "src" / package).rglob("*.py")
        )
        assert consumed, f"{package} does not consume the as-platform library (REQ-F-029)"
