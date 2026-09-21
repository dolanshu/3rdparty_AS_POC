#!/usr/bin/env python3
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

"""Reproduce the `uv` `path`-dependency facts of ADR-0009 (P10).

ADR-0009 decision 6 consumes the extracted library through a `path` source, and its
*Verified facts* record seven measured properties of that mechanism. Those facts were first
observed in a scratch directory under `/tmp/p10probe` that was never committed, so a reader
could not re-run them. This tool is the **reproducible form** of those facts: it rebuilds the
whole scratch layout in a temporary directory and exercises every measured case.

It is self-contained and side-effect free outside its own temporary directory: it creates a
throwaway library repository (a `src/as_platform` package with a `VERSION` literal, a
`py.typed` marker and a hatchling build) plus one consumer variant per case, each varying one
key of `pyproject.toml`. It never reads or writes this repository and never touches the
network beyond `uv`'s own cache (the build backend `hatchling` and `mypy` must be resolvable
from the local cache or an index).

It is a **guard on its own integrity**, not a test: pytest does not collect it, it is not in
``make test`` and it is not wired into CI. It exits non-zero when any measured expectation
does not hold, so a green run is evidence and a red run means the recorded facts are wrong.

The cases, in the order of ADR-0009 *Verified facts*:

(a) a dependency key with no ``[tool.uv.sources]`` entry does not resolve;
(b) a ``path`` source installs a copy by default and ``editable = true`` links the checkout,
    so a library edit is invisible until ``uv sync --reinstall-package`` and visible at once
    when editable;
(c) a version constraint in ``dependencies`` is silently ignored for a path source;
(d) ``--locked`` refuses a stale lock while ``--frozen`` accepts the same skew and does not
    update the lock — so with a path source the lock is not a version guard;
(e) ``py.typed`` is required or ``mypy`` refuses the import;
(f) the path is resolved relative to the consuming ``pyproject.toml``, so a nested consumer
    does not find a sibling library;
(g) the dependency key may be spelled ``as_platform`` or ``as-platform``.

Usage:
    uv run python tools/path_dependency_probe.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Distribution and import name of the throwaway library, and its starting version.
LIB_DIST = "as-platform"
LIB_IMPORT = "as_platform"
LIB_VERSION = "0.4.0"

#: The version the library is bumped to when the lockfile staleness case is measured.
BUMPED_VERSION = "0.5.0"

#: A dependency key that cannot possibly match the checkout, to measure that it is ignored.
IMPOSSIBLE_PIN = ">=99.0"

_LIBRARY_PYPROJECT = """\
[project]
name = "as-platform"
version = "{version}"
requires-python = ">=3.10,<3.11"

[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/as_platform"]
"""


@dataclass
class Check:
    """One measured case and whether its expectation held.

    Attributes:
        key: The ADR-0009 *Verified facts* label, for example ``(a)``.
        title: What the case measures, in one line.
        ok: Whether the observed behaviour matched the recorded expectation.
        detail: The observed evidence, printed whether the check passed or failed.
    """

    key: str
    title: str
    ok: bool
    detail: str


def _uv_env() -> dict[str, str]:
    """Return the environment a `uv` subprocess runs with.

    ``RUST_LOG`` is cleared because this machine's shell exports it, which makes `uv` print
    resolver trace lines that would bury the report; ``VIRTUAL_ENV`` is cleared so a
    subprocess run inside this repository's own virtual environment does not warn; and
    ``PYTHONDONTWRITEBYTECODE`` is set so importing the library never leaves a stale
    ``__pycache__`` behind (see :func:`_clear_bytecode`). Everything else is inherited.

    Returns:
        A copy of the environment with the noisy variables removed.
    """
    env = dict(os.environ)
    env.pop("RUST_LOG", None)
    env.pop("ICUBE_RUST_LOG_LEVEL", None)
    env.pop("VIRTUAL_ENV", None)
    env["UV_NO_PROGRESS"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_uv(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run `uv` in a directory and capture its output.

    Args:
        cwd: Directory the command runs in.
        *args: Arguments after the ``uv`` executable, for example ``sync --locked``.

    Returns:
        The completed process, with ``stdout`` and ``stderr`` captured as text.
    """
    return subprocess.run(
        ["uv", *args],
        cwd=cwd,
        env=_uv_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    """Return a process's combined output, for substring matching."""
    return result.stdout + result.stderr


def _clear_bytecode(package: Path) -> None:
    """Remove compiled bytecode under a package so an edit is never masked by a stale `.pyc`.

    Python validates a cached ``.pyc`` by source mtime and size, and a version literal such as
    ``"0.4.0"`` rewritten to ``"0.5.0"`` keeps both; a same-second edit would otherwise be
    read from the previous bytecode. The probe rewrites the library repeatedly, so it clears
    the cache itself.

    Args:
        package: The library package whose bytecode is removed.
    """
    for cache in package.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def write_library(root: Path, *, version: str = LIB_VERSION, py_typed: bool = True) -> None:
    """Write the throwaway library repository.

    Args:
        root: Directory the library repository is written into.
        version: Version the library declares, in both ``pyproject.toml`` and the module.
        py_typed: Whether the package carries its PEP 561 marker.
    """
    package = root / "src" / LIB_IMPORT
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(f'VERSION = "{version}"\n__version__ = VERSION\n')
    marker = package / "py.typed"
    if py_typed:
        marker.write_text("")
    else:
        marker.unlink(missing_ok=True)
    (root / "pyproject.toml").write_text(_LIBRARY_PYPROJECT.format(version=version))
    _clear_bytecode(package)


def set_library_module(root: Path, version: str) -> None:
    """Change only the module's ``VERSION`` literal, leaving the declared version alone.

    This is how a library edit is simulated: the code changes, the distribution version does
    not, so an implicit re-sync has no reason to rebuild a copied install.

    Args:
        root: The library repository.
        version: The new literal.
    """
    package = root / "src" / LIB_IMPORT
    (package / "__init__.py").write_text(f'VERSION = "{version}"\n__version__ = VERSION\n')
    _clear_bytecode(package)


def set_library_version(root: Path, version: str) -> None:
    """Change the version the library declares, in both places that carry it.

    Args:
        root: The library repository.
        version: The new version.
    """
    set_library_module(root, version)
    (root / "pyproject.toml").write_text(_LIBRARY_PYPROJECT.format(version=version))


def write_consumer(root: Path, text: str) -> None:
    """Write one consumer project and return nothing.

    Args:
        root: Directory the consumer is written into.
        text: The full ``pyproject.toml`` contents.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(text)


def consumer_pyproject(
    *,
    dependency: str = LIB_DIST,
    source: str | None = None,
    groups: str = "",
) -> str:
    """Build a consumer ``pyproject.toml``.

    Args:
        dependency: The requirement string written into ``[project].dependencies``.
        source: The ``[tool.uv.sources]`` block, or ``None`` for no source table.
        groups: An extra block appended verbatim, for example a ``[dependency-groups]`` table.

    Returns:
        The file contents.
    """
    text = (
        "[project]\n"
        'name = "consumer"\n'
        'version = "0.0.1"\n'
        'requires-python = ">=3.10,<3.11"\n'
        f'dependencies = ["{dependency}"]\n'
    )
    if groups:
        text += groups
    if source is not None:
        text += f"\n[tool.uv.sources]\n{source}\n"
    return text


def site_packages(consumer: Path) -> Path:
    """Return the consumer's `site-packages` directory.

    Args:
        consumer: The consumer project whose environment was synced.

    Returns:
        The first ``lib/python*/site-packages`` directory found in its virtual environment.
    """
    found = next((consumer / ".venv" / "lib").glob("python*/site-packages"), None)
    if found is None:
        raise RuntimeError(
            f"no site-packages directory under {consumer / '.venv' / 'lib'}"
        )
    return found


def installed_version(consumer: Path) -> str:
    """Return the library version the consumer's environment actually imports.

    ``--no-sync`` is essential: an implicit sync would rebuild the install and hide the very
    staleness the caller is trying to observe.

    Args:
        consumer: The consumer project whose environment was synced.

    Returns:
        The value of ``as_platform.VERSION`` as the installed code reports it.
    """
    result = run_uv(
        consumer,
        "run",
        "--no-sync",
        "python",
        "-c",
        "import as_platform; print(as_platform.VERSION)",
    )
    return result.stdout.strip()


def _direct_url(consumer: Path) -> dict[str, object] | None:
    """Return the ``direct_url.json`` of the installed library, when there is one."""
    for path in site_packages(consumer).glob(f"{LIB_IMPORT}-*.dist-info/direct_url.json"):
        return json.loads(path.read_text())
    return None


def case_source_is_mandatory(root: Path) -> Check:
    """Fact (a): a dependency key with no path source does not resolve."""
    consumer = root / "app_no_source"
    write_consumer(consumer, consumer_pyproject())
    result = run_uv(consumer, "sync")
    ok = result.returncode != 0 and "was not found in the package registry" in _combined(result)
    detail = f"exit {result.returncode}; " + next(
        (line for line in _combined(result).splitlines() if "was not found" in line),
        "no 'not found' line",
    )
    return Check("(a)", "a dependency key alone does not resolve", ok, detail)


def case_default_is_a_copy(root: Path, library: Path) -> Check:
    """Fact (b): a `path` source with no `editable` installs a copy, not a link."""
    consumer = root / "app_default"
    write_consumer(consumer, consumer_pyproject(source=f'{LIB_DIST} = {{ path = "../lib" }}'))
    sync = run_uv(consumer, "sync")
    if sync.returncode != 0:
        return Check("(b)", "default install is a copy", False, f"sync failed: {_combined(sync)}")
    direct = _direct_url(consumer) or {}
    info = direct.get("dir_info", {})
    editable = isinstance(info, dict) and info.get("editable")
    copy_present = (site_packages(consumer) / LIB_IMPORT).is_dir()
    set_library_module(library, "EDITED")
    invisible = installed_version(consumer) == LIB_VERSION
    reinstall = run_uv(consumer, "sync", "--reinstall-package", LIB_DIST)
    visible_after = installed_version(consumer) == "EDITED"
    set_library_module(library, LIB_VERSION)
    ok = (
        sync.returncode == 0
        and editable is False
        and copy_present
        and invisible
        and reinstall.returncode == 0
        and visible_after
    )
    detail = (
        f"direct_url editable={editable!r}, copy in site-packages={copy_present}, "
        f"edit invisible before re-sync={invisible}, visible after "
        f"--reinstall-package={visible_after}"
    )
    return Check("(b)", "default install is a copy; --reinstall-package refreshes it", ok, detail)


def case_editable_links(root: Path, library: Path) -> Check:
    """Fact (b): `editable = true` links the checkout, so an edit is visible at once."""
    consumer = root / "app_editable"
    write_consumer(
        consumer,
        consumer_pyproject(source=f'{LIB_DIST} = {{ path = "../lib", editable = true }}'),
    )
    sync = run_uv(consumer, "sync")
    if sync.returncode != 0:
        return Check("(b)", "editable links the checkout", False, f"sync failed: {_combined(sync)}")
    direct = _direct_url(consumer) or {}
    info = direct.get("dir_info", {})
    editable = isinstance(info, dict) and info.get("editable")
    linked = any(site_packages(consumer).glob("_editable_impl_*.pth"))
    set_library_module(library, "EDITED")
    visible = installed_version(consumer) == "EDITED"
    set_library_module(library, LIB_VERSION)
    ok = sync.returncode == 0 and editable is True and linked and visible
    detail = (
        f"direct_url editable={editable!r}, _editable_impl pth={linked}, "
        f"edit visible with no re-sync={visible}"
    )
    return Check(
        "(b)", "editable = true links the checkout; the edit is visible at once", ok, detail
    )


def case_pin_is_ignored(root: Path) -> Check:
    """Fact (c): a version constraint in `dependencies` is ignored for a path source."""
    consumer = root / "app_pin"
    write_consumer(
        consumer,
        consumer_pyproject(
            dependency=f"{LIB_DIST}{IMPOSSIBLE_PIN}",
            source=f'{LIB_DIST} = {{ path = "../lib", editable = true }}',
        ),
    )
    result = run_uv(consumer, "sync")
    version = installed_version(consumer) if result.returncode == 0 else ""
    ok = result.returncode == 0 and version == LIB_VERSION
    detail = f"exit {result.returncode}, installed {version!r} (pin was {IMPOSSIBLE_PIN!r})"
    return Check("(c)", "a version constraint is silently ignored", ok, detail)


def case_underscore_spelling(root: Path) -> Check:
    """Fact (g): the key may be spelled with an underscore or a hyphen."""
    consumer = root / "app_underscore"
    write_consumer(
        consumer,
        consumer_pyproject(
            dependency=LIB_IMPORT,
            source=f'{LIB_IMPORT} = {{ path = "../lib", editable = true }}',
        ),
    )
    result = run_uv(consumer, "sync")
    version = installed_version(consumer) if result.returncode == 0 else ""
    ok = result.returncode == 0 and version == LIB_VERSION
    detail = f"exit {result.returncode}, installed {version!r} from the underscore spelling"
    return Check("(g)", "the key may be spelled as_platform or as-platform", ok, detail)


def case_nested_path(root: Path) -> Check:
    """Fact (f): the path is relative to the consuming `pyproject.toml`."""
    consumer = root / "nested" / "a" / "consumer"
    write_consumer(consumer, consumer_pyproject(source=f'{LIB_DIST} = {{ path = "../lib" }}'))
    result = run_uv(consumer, "sync")
    combined = _combined(result)
    expected = f"Distribution not found at: file://{consumer.parent / 'lib'}"
    ok = result.returncode != 0 and expected in combined
    detail = f"exit {result.returncode}; " + next(
        (line for line in combined.splitlines() if "Distribution not found" in line),
        "no 'Distribution not found' line",
    )
    return Check("(f)", "a nested consumer does not find a sibling library", ok, detail)


def case_lock_versus_frozen(root: Path, library: Path) -> Check:
    """Fact (d): `--locked` refuses a stale lock; `--frozen` accepts the same skew."""
    consumer = root / "app_lock"
    write_consumer(
        consumer,
        consumer_pyproject(source=f'{LIB_DIST} = {{ path = "../lib", editable = true }}'),
    )
    sync = run_uv(consumer, "sync")
    if sync.returncode != 0:
        return Check("(d)", "lock vs --frozen", False, f"initial sync failed: {_combined(sync)}")
    set_library_version(library, BUMPED_VERSION)
    locked = run_uv(consumer, "sync", "--locked")
    frozen = run_uv(consumer, "sync", "--frozen")
    installed = installed_version(consumer)
    lock_text = (consumer / "uv.lock").read_text()
    lock_still_stale = f'version = "{LIB_VERSION}"' in lock_text
    set_library_version(library, LIB_VERSION)
    ok = (
        locked.returncode != 0
        and "needs to be updated" in _combined(locked)
        and frozen.returncode == 0
        and installed == BUMPED_VERSION
        and lock_still_stale
    )
    detail = (
        f"--locked exit {locked.returncode} "
        f"({'refused' if locked.returncode else 'accepted'}), "
        f"--frozen exit {frozen.returncode} installed {installed!r}, "
        f"lock still records {LIB_VERSION}={lock_still_stale}"
    )
    return Check("(d)", "--locked refuses a stale lock; --frozen accepts the skew", ok, detail)


def case_py_typed_required(root: Path, library: Path) -> Check:
    """Fact (e): without `py.typed`, `mypy` refuses the import of a copied install."""
    consumer = root / "app_mypy"
    write_consumer(
        consumer,
        consumer_pyproject(
            source=f'{LIB_DIST} = {{ path = "../lib" }}',
            groups='\n[dependency-groups]\ndev = ["mypy>=1.9"]\n',
        ),
    )
    source = consumer / "src" / "app.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("import as_platform\n\nreveal_type(as_platform.VERSION)\n")
    write_library(library, py_typed=True)
    sync = run_uv(consumer, "sync")
    if sync.returncode != 0:
        return Check("(e)", "py.typed is required", False, f"sync failed: {_combined(sync)}")
    with_marker = run_uv(consumer, "run", "--no-sync", "mypy", "src/app.py")
    write_library(library, py_typed=False)
    run_uv(consumer, "sync", "--reinstall-package", LIB_DIST)
    without_marker = run_uv(consumer, "run", "--no-sync", "mypy", "src/app.py")
    write_library(library, py_typed=True)
    ok = (
        with_marker.returncode == 0
        and without_marker.returncode != 0
        and "import-untyped" in _combined(without_marker)
    )
    detail = (
        f"mypy with py.typed exit {with_marker.returncode}, "
        f"without py.typed exit {without_marker.returncode} "
        f"(import-untyped={'import-untyped' in _combined(without_marker)})"
    )
    return Check("(e)", "py.typed is required or mypy refuses the import", ok, detail)


def main() -> int:
    """Run every measured case and print the report.

    Returns:
        Process exit code: ``0`` when every expectation held, ``1`` otherwise.
    """
    if shutil.which("uv") is None:
        print("uv is not on PATH; this probe measures uv's own behaviour", file=sys.stderr)
        return 1

    print("P10 path-dependency probe - reproducing the ADR-0009 *Verified facts*")
    print("layout     : a throwaway library plus one consumer variant per case, in a temp dir")
    print("scope      : this repository is never read or written; the temp dir is removed")
    print("requirement: uv 0.12.x and hatchling/mypy resolvable from the local cache or an index")
    print()

    root = Path(tempfile.mkdtemp(prefix="p10-path-dependency-"))
    library = root / "lib"
    checks: list[Check] = []
    try:
        write_library(library)
        for case in (
            case_source_is_mandatory,
            lambda r: case_default_is_a_copy(r, library),
            lambda r: case_editable_links(r, library),
            case_pin_is_ignored,
            case_underscore_spelling,
            case_nested_path,
            lambda r: case_lock_versus_frozen(r, library),
            lambda r: case_py_typed_required(r, library),
        ):
            check = case(root)
            checks.append(check)
            verdict = "OK" if check.ok else "FAILED"
            print(f"{check.key} {check.title:<58} : {verdict}")
            print(f"    {check.detail}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    failed = [check for check in checks if not check.ok]
    failed_keys = ", ".join(check.key for check in failed)
    print()
    print("--- verdict --------------------------------------------------------")
    print(f"cases measured : {len(checks)}")
    print(f"expectations   : {'all held' if not failed else 'FAILED: ' + failed_keys}")
    if failed:
        print("the recorded ADR-0009 facts do not reproduce; the design must be revisited")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
