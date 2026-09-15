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

"""Startup self-check, configuration model and graceful shutdown.

The AS fails fast: an invalid configuration aborts startup instead of failing later at
runtime (``AGENT.md`` section 4.3). This module owns the configuration schema
(``AGENT.md`` section 8) because parsing and validation are startup concerns.

Signal handling has to cooperate with sippy's blocking event loop: ``ED2.loop()`` cannot
be interrupted from a handler, so the handlers only request shutdown and the loop is
stopped from a timer owned by the loop (ADR-0002, and ``AGENT.md`` section 6).
"""

from __future__ import annotations

import signal
import socket
from pathlib import Path
from types import FrameType
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from as_app.errors import AsError, AsErrorCode
from as_app.routing.rules import load_rule_set

__all__ = ["AsSettings", "ShutdownController", "install_signal_handlers", "run_startup_self_check"]

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
    sbc_peer_port: int = Field(default=5061, ge=1, le=65535)
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


def check_port_available(address: str, port: int, *, family: int = socket.AF_INET) -> None:
    """Check that a UDP port can be bound before the service starts.

    Args:
        address: Local address to bind.
        port: UDP port to bind.
        family: Socket family used for the check.

    Raises:
        AsError: ``AS-CFG-003`` when the port cannot be bound.
    """
    probe = socket.socket(family, socket.SOCK_DGRAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((address, port))
    except OSError as exc:
        raise AsError(
            AsErrorCode.CFG_PORT_UNAVAILABLE,
            f"cannot bind UDP {address}:{port}: {exc}",
            context={"address": address, "port": str(port)},
        ) from exc
    finally:
        probe.close()


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
            AsErrorCode.CFG_MISSING,
            "SBC_PEER_ADDRESS is required: the AS must know its next hop",
        )
    if not settings.allowed_peers:
        raise AsError(
            AsErrorCode.CFG_PEER_INVALID,
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


class ShutdownController:
    """Cooperative shutdown state shared between signal handlers and the event loop."""

    def __init__(self) -> None:
        """Create a controller in the running state."""
        self._requested = False
        self._reason: str | None = None

    @property
    def requested(self) -> bool:
        """Whether a shutdown has been requested."""
        return self._requested

    @property
    def reason(self) -> str | None:
        """Why the shutdown was requested, for example ``SIGTERM``."""
        return self._reason

    def request(self, reason: str) -> None:
        """Request a graceful shutdown.

        Args:
            reason: Short description of the trigger.
        """
        self._requested = True
        self._reason = reason


def install_signal_handlers(controller: ShutdownController) -> None:
    """Install ``SIGTERM`` and ``SIGINT`` handlers that only request shutdown.

    The handlers must not stop the sippy event loop themselves; a handler runs between
    bytecodes and the loop owns the sockets.

    Args:
        controller: Shutdown state the handlers write to.
    """

    def _handler(signum: int, _frame: FrameType | None) -> None:
        controller.request(f"signal {signal.Signals(signum).name}")

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _handler)
