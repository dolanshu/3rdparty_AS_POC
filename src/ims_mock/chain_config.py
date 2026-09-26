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

"""Ordered iFC chain configuration for the POC mock."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AsHop", "ChainConfig"]


@dataclass(frozen=True)
class AsHop:
    """One external AS entry in the iFC chain.

    Attributes:
        name: Short identifier (`anti-fraud`, `translation`, …).
        host: SIP listen address of the AS trunk.
        port: SIP listen port of the AS trunk.
    """

    name: str
    host: str
    port: int


@dataclass(frozen=True)
class ChainConfig:
    """Fixed ordered list of AS hops the orchestrator applies.

    Attributes:
        hops: iFC entries in evaluation order.
    """

    hops: tuple[AsHop, ...]

    @classmethod
    def default_two_as(cls, as1_host: str, as1_port: int, as2_host: str, as2_port: int) -> ChainConfig:
        """Build the shipped two-AS chain (anti-fraud then translation).

        Args:
            as1_host: AS-1 listen address.
            as1_port: AS-1 listen port.
            as2_host: AS-2 listen address.
            as2_port: AS-2 listen port.

        Returns:
            A chain with two hops.
        """
        return cls(
            hops=(
                AsHop("anti-fraud", as1_host, as1_port),
                AsHop("translation", as2_host, as2_port),
            )
        )
