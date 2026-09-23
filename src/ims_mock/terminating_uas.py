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

"""Called-party UAS reached through the P-CSCF relay (not the S-SBC return port)."""

from __future__ import annotations

from s_sbc_mock.uas import CoreUas, ReceivedInvite

__all__ = ["TerminatingUas", "ReceivedInvite"]

#: Reuse the core-side answer pattern; only the wiring differs (ADR-0014).
TerminatingUas = CoreUas
