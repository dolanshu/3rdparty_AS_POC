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

"""Third-party Application Server (B2BUA) reachable over a SIP trunk from the S-SBC.

The package owns the signalling application only: the number translation and routing
decision lives in :mod:`as_app.routing`, the sippy glue in :mod:`as_app.sip_adapter`
and :mod:`as_app.call_controller`, and the observability surface in
:mod:`as_app.observability`. Nothing here may import from ``s_sbc_mock`` — the AS must
run against a real S-SBC without a code change (``AGENT.md`` section 5).
"""

from __future__ import annotations

from pathlib import Path

#: Reported when the ``VERSION`` file cannot be read, for example in an installed wheel.
_UNKNOWN_VERSION = "0.0.0+unknown"


def _read_version() -> str:
    """Return the repository version from the ``VERSION`` file.

    ``VERSION`` sits at the repository root, two directories above this module. Deriving the
    value from it keeps the runtime version (the ``/healthz`` payload and the ``application
    server starting`` log line) in step with ``VERSION`` and ``pyproject.toml``, which
    ``AGENT.md`` section 4.7 and the test suite already guard.

    Returns:
        The stripped contents of ``VERSION``, or ``_UNKNOWN_VERSION`` when the file is not
        present — which is the case for an installed wheel (see ``docs/production-gaps.md``).
    """
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return _UNKNOWN_VERSION


__version__ = _read_version()
