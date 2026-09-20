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

"""Re-export facade for the platform library's observability surface.

The implementation moved to :mod:`as_platform.observability` (ADR-0009 decision 2). This
package stays a thin re-export so the by-path references in ``tools/``, ``tests/`` and the
frozen ADRs and LLD keep resolving. It adds no behaviour and no state, and it is a
permanent part of the design, not a migration shim.
"""

from __future__ import annotations
