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

"""Startup self-check and configuration model of the number-translation AS.

The AS fails fast: an invalid configuration aborts startup instead of failing later at
runtime (``AGENT.md`` section 4.3). This module owns the configuration schema
(``AGENT.md`` section 8) because parsing and validation are startup concerns and the field
names are this instance's identity.

The **process plumbing** — the port probe, the cooperative shutdown controller and the
signal handlers — is use-case-agnostic and lives in :mod:`as_platform.bootstrap`
(ADR-0009 decision 2). It is re-exported here so that ``as_app.bootstrap`` keeps the surface
its callers reference by path; the re-export is permanent, not a migration shim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from as_platform.bootstrap import (
    ShutdownController,
    check_port_available,
    install_signal_handlers,
)
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from as_app.errors import AsError, AsErrorCode, SkeletonErrorCode
from as_app.routing.rules import load_rule_set

__all__ = [
    "AsSettings",
    "ShutdownController",
    "check_port_available",
    "install_signal_handlers",
    "run_startup_self_check",
]

#: Environment file read by pydantic-settings. Only the example is committed
#: (``AGENT.md`` section 9).
DEFAULT_ENV_FILE = ".env"


class AsSettings(BaseSettings):
    """Configuration of the AS, read from the environment.

    No default silently points at a real network: the peer address must be configured,
    and switching from the local mock to a real S-SBC is a configuration change only
    (``AGENT.md`` section 8).

    Attributes:
        sip_listen_address: Local address the trunk is received on.
        sip_listen_port: Local UDP port of the trunk.
        sbc_peer_address: Next hop for outbound INVITEs (mock or real S-SBC).
        sbc_peer_port: UDP port of the next hop.
        allowed_peers: Source addresses accepted on the trunk, comma separated.
        rules_file: Path to the routing rules file.
        internal_api_address: Address the console reaches the AS on.
        internal_api_port: Port of the internal API.
        log_level: Log level name.
        log_structured: Emit JSON log lines when true.
        log_payloads: Log SIP payloads; off by default (``AGENT.md`` section 9).
        shutdown_grace_seconds: Time allowed for in-flight calls to finish.
    """

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="",
    )

    sip_listen_address: str = "127.0.0.1"
    sip_listen_port: int = Field(default=5060, ge=1, le=65535)
    sbc_peer_address: str = "127.0.0.1"
    sbc_peer_port: int = Field(default=15061, ge=1, le=65535)
    # NoDecode keeps the raw environment string so that ALLOWED_PEERS can be a plain
    # comma separated list instead of JSON (operators edit .env by hand).
    allowed_peers: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["127.0.0.1"])
    rules_file: Path = Path("config/routing_rules.yaml")
    internal_api_address: str = "127.0.0.1"
    internal_api_port: int = Field(default=8080, ge=1, le=65535)
    log_level: str = "INFO"
    log_structured: bool = True
    log_payloads: bool = False
    shutdown_grace_seconds: float = 5.0

    @field_validator("allowed_peers", mode="before")
    @classmethod
    def _split_peers(cls, value: Any) -> Any:
        """Accept a comma separated string for ``ALLOWED_PEERS``.

        Args:
            value: Raw value from the environment.

        Returns:
            A list of trimmed addresses, or the value unchanged when it is already a list.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        """Validate the log level name.

        Args:
            value: Log level name.

        Returns:
            The upper-case level name.

        Raises:
            ValueError: If the level is not a known logging level name.
        """
        known = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if value.upper() not in known:
            raise ValueError(f"unsupported log level: {value}")
        return value.upper()


def run_startup_self_check(settings: AsSettings) -> None:
    """Validate configuration, parse the rules file and check the signalling port.

    Args:
        settings: The loaded configuration.

    Raises:
        AsError: ``AS-CFG-*`` for configuration problems, ``AS-RULE-*`` for rules that
            cannot be read, parsed or validated.
    """
    if not settings.sbc_peer_address.strip():
        raise AsError(
            SkeletonErrorCode.CFG_MISSING,
            "SBC_PEER_ADDRESS is required: the AS must know its next hop",
        )
    if not settings.allowed_peers:
        raise AsError(
            SkeletonErrorCode.CFG_PEER_INVALID,
            "ALLOWED_PEERS must list at least one trunk peer address",
        )
    rules_path = Path(settings.rules_file)
    if not rules_path.is_file():
        raise AsError(
            AsErrorCode.RULE_FILE_UNREADABLE,
            f"rules file does not exist: {rules_path}",
            context={"rules_file": str(rules_path)},
        )
    load_rule_set(rules_path)
    check_port_available(settings.sip_listen_address, settings.sip_listen_port)
