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

"""Third-party Application Server (B2BUA) reachable over a SIP trunk from the S-SBC.

The package owns the signalling application only: the number translation and routing
decision lives in :mod:`as_app.routing`, the sippy glue in :mod:`as_app.sip_adapter`
and :mod:`as_app.call_controller`, and the observability surface in
:mod:`as_app.observability`. Nothing here may import from ``s_sbc_mock`` — the AS must
run against a real S-SBC without a code change (``AGENT.md`` section 5).
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

#: Distribution name declared in ``pyproject.toml``. An installed wheel carries its version
#: in the distribution metadata under exactly this name.
_DISTRIBUTION_NAME = "third-party-as-poc"

#: Reported when neither the installed distribution metadata nor the ``VERSION`` file yields
#: a version.
_UNKNOWN_VERSION = "0.0.0+unknown"


def _distribution_version() -> str:
    """Return the version recorded in the installed distribution metadata.

    An installed wheel does not ship the repository ``VERSION`` file, so the metadata the
    build backend wrote into the wheel is the only version source it carries. Reading it
    first (P5) is what keeps an installed wheel from reporting ``_UNKNOWN_VERSION``.

    Returns:
        The version string of the installed ``_DISTRIBUTION_NAME`` distribution.

    Raises:
        importlib.metadata.PackageNotFoundError: The distribution is not installed — the
            case for a source checkout that was never installed.
        Exception: Any error a metadata backend raises while reading a present but
            unreadable distribution is propagated as well and handled by the caller.
    """
    return importlib.metadata.version(_DISTRIBUTION_NAME)


def _version_file_version() -> str:
    """Return the repository version from the ``VERSION`` file.

    ``VERSION`` sits at the repository root, two directories above this module. It is the
    version source of a source checkout, and it is guarded to agree with ``pyproject.toml``
    by ``AGENT.md`` section 4.7 and the test suite.

    Returns:
        The stripped contents of ``VERSION``, or ``_UNKNOWN_VERSION`` when the file is not
        present — which is the case for an installed wheel.
    """
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return _UNKNOWN_VERSION


def _read_version() -> str:
    """Return the runtime version: installed metadata first, then the ``VERSION`` file.

    The three-step chain (P5, the "Version discovery" gap of ``docs/production-gaps.md``):

    1. ``importlib.metadata.version("third-party-as-poc")`` — the version an installed
       wheel carries in its distribution metadata;
    2. the repository ``VERSION`` file — the source-checkout path, where no distribution
       metadata has to exist at all;
    3. ``_UNKNOWN_VERSION`` when neither source is available.

    Metadata comes first because it is the only branch an installed wheel can satisfy: a
    wheel ships no ``VERSION`` file. It is also safe for an editable install and for a bare
    source checkout, because ``VERSION``, ``pyproject.toml`` and the installed metadata all
    carry the same version — ``test_version_file_matches_the_project_version`` guards the
    first pair, and an editable install derives its metadata from the same ``pyproject.toml``.

    Returns:
        The version string the AS serves on ``/healthz`` and in the ``application server
        starting`` log line, or ``_UNKNOWN_VERSION`` when no source is available.
    """
    try:
        return _distribution_version()
    except Exception:  # PackageNotFoundError, or any metadata backend failure.
        return _version_file_version()


__version__ = _read_version()
