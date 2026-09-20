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

"""Configuration and startup self-check of the anti-fraud AS.

Same fail-fast contract as the first AS (``AGENT.md`` section 4.3): an unusable
configuration or screening-data file aborts startup instead of failing later at runtime.

The settings model is separate from ``as_app.bootstrap.AsSettings`` because the two AS
instances are configured independently; sharing one model would mean adding the screening
fields to the number-translation AS's model for no gain (ADR-0007 decision 9). Instance
identifying knobs are prefixed ``FRAUD_`` so a single ``.env`` cannot point the wrong
process at the wrong peer, while the observability and runtime knobs are shared with the
first AS because they describe the process, not the instance. **No default silently points
at a real network** — every address defaults to loopback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from as_platform.bootstrap import check_port_available
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from anti_fraud_as.errors import AsError, FraudErrorCode, SkeletonErrorCode
from anti_fraud_as.screening_data import load_screening_data

__all__ = ["DEFAULT_ENV_FILE", "FraudAsSettings", "run_startup_self_check"]

#: Environment file read by pydantic-settings. Only the example is committed
#: (``AGENT.md`` section 9).
DEFAULT_ENV_FILE = ".env"

#: Known logging level names, shared with the first AS.
_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


class FraudAsSettings(BaseSettings):
    """Configuration of the anti-fraud AS, read from the environment.

    Attributes:
        fraud_sip_listen_address: Local address the trunk is received on.
        fraud_sip_listen_port: Local UDP port of the trunk; defaults to ``5062`` so both AS
            instances can run on one host (the port-collision trap of
            ``docs/phase2-plan.md`` section 6).
        fraud_sbc_peer_address: Next hop the allowed INVITE is relayed to.
        fraud_sbc_peer_port: UDP port of that next hop.
        fraud_allowed_peers: Source addresses accepted on the trunk, comma separated.
        fraud_screening_file: Path to the screening-data file.
        fraud_internal_api_address: Address the console reaches this AS on.
        fraud_internal_api_port: Port of the internal API.
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

    fraud_sip_listen_address: str = "127.0.0.1"
    fraud_sip_listen_port: int = Field(default=5062, ge=1, le=65535)
    fraud_sbc_peer_address: str = "127.0.0.1"
    fraud_sbc_peer_port: int = Field(default=15061, ge=1, le=65535)
    # NoDecode keeps the raw environment string so FRAUD_ALLOWED_PEERS can be a plain comma
    # separated list instead of JSON (operators edit .env by hand).
    fraud_allowed_peers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1"]
    )
    fraud_screening_file: Path = Path("config/caller_screening.yaml")
    fraud_internal_api_address: str = "127.0.0.1"
    fraud_internal_api_port: int = Field(default=8082, ge=1, le=65535)
    log_level: str = "INFO"
    log_structured: bool = True
    log_payloads: bool = False
    shutdown_grace_seconds: float = 5.0

    @field_validator("fraud_allowed_peers", mode="before")
    @classmethod
    def _split_peers(cls, value: Any) -> Any:
        """Accept a comma separated string for ``FRAUD_ALLOWED_PEERS``.

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
        if value.upper() not in _LOG_LEVELS:
            raise ValueError(f"unsupported log level: {value}")
        return value.upper()


def run_startup_self_check(settings: FraudAsSettings) -> None:
    """Validate the configuration, the screening-data file and the signalling port.

    Args:
        settings: The loaded configuration.

    Raises:
        AsError: ``AS-CFG-*`` for configuration problems, ``AS-FRAUD-004`` / ``AS-FRAUD-005``
            when the screening-data file cannot be read or is invalid.
    """
    if not settings.fraud_sbc_peer_address.strip():
        raise AsError(
            SkeletonErrorCode.CFG_MISSING,
            "FRAUD_SBC_PEER_ADDRESS is required: the AS must know its next hop",
        )
    if not settings.fraud_allowed_peers:
        raise AsError(
            SkeletonErrorCode.CFG_PEER_INVALID,
            "FRAUD_ALLOWED_PEERS must list at least one trunk peer address",
        )
    screening_path = Path(settings.fraud_screening_file)
    if not screening_path.is_file():
        raise AsError(
            FraudErrorCode.FRAUD_DATA_UNREADABLE,
            f"screening data file does not exist: {screening_path}",
            context={"screening_file": str(screening_path)},
        )
    load_screening_data(screening_path)
    check_port_available(settings.fraud_sip_listen_address, settings.fraud_sip_listen_port)
