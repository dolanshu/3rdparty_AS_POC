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

"""Anti-fraud Application Server — the second concrete AS (P8).

A separate process that screens the **calling** party of a trunk INVITE and returns a
verdict: relay the INVITE unchanged, or answer ``608 Rejected`` (RFC 8688). The design is
`docs/architecture/adr/0007-anti-fraud-as-and-608-rejection.md` and
`docs/architecture/lld.md` section 9.

The package reuses the use-case-agnostic modules of :mod:`as_platform` — the error model,
structured logging, counters, tracing, generic sippy plumbing — by direct import, and takes
its version from :mod:`as_app` so both AS instances report the repository version. It is a
concrete second application, **not** a framework: no registry, no plugin protocol and no
shared base class (ADR-0007 decision 9; the common skeleton is the library, ADR-0009).
"""

from __future__ import annotations

from as_app import __version__

__all__ = ["__version__"]
