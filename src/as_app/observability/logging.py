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

"""Structured logging for the AS.

Every line carries timestamp, level, module, ``call_id``, ``direction``, ``peer`` and an
event message; the Call-ID threads the whole call across both legs
(``AGENT.md`` section 4.3). Payload bodies are never logged here — payload display is a
console feature and payload logging is an explicit switch (``AGENT.md`` section 9).

Open item (M1): this module shadows the standard library ``logging`` name; keep all
imports in this repository package-absolute.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from typing import Any

__all__ = [
    "LogDirection",
    "StructuredFormatter",
    "configure_logging",
    "get_logger",
    "log_event",
]

#: Field set of every log line. Documented in ``docs/architecture/lld.md``; never
#: changed silently.
LOG_FIELDS: tuple[str, ...] = (
    "timestamp",
    "level",
    "module",
    "call_id",
    "direction",
    "peer",
    "event",
)

DEFAULT_DIRECTION = "-"
DEFAULT_UNKNOWN = "-"


class LogDirection:
    """Direction of a message relative to the AS, as used in the ``direction`` field."""

    INBOUND = "in"
    OUTBOUND = "out"
    INTERNAL = "internal"

    ALL: tuple[str, ...] = (INBOUND, OUTBOUND, INTERNAL)


class StructuredFormatter(logging.Formatter):
    """Render a record as one JSON object with the fixed field set."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise the record to a single-line JSON object.

        Args:
            record: The log record to render.

        Returns:
            A JSON object containing the mandatory fields plus any extras.
        """
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "module": record.module,
            "call_id": getattr(record, "call_id", DEFAULT_UNKNOWN),
            "direction": getattr(record, "direction", DEFAULT_DIRECTION),
            "peer": getattr(record, "peer", DEFAULT_UNKNOWN),
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in logging.LogRecord.__dict__ or key in (
                "args",
                "msg",
                "levelno",
                "levelname",
                "pathname",
                "filename",
                "module",
                "name",
                "message",
                "asctime",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
            ):
                continue
            if value is None:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=False)


def get_logger(name: str) -> logging.Logger:
    """Return the logger for a module of the application.

    Args:
        name: Dotted module name, normally ``__name__``.

    Returns:
        The logger instance for that name.
    """
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    call_id: str | None = None,
    direction: str = DEFAULT_DIRECTION,
    peer: str | None = None,
    **extra: Any,
) -> None:
    """Emit one structured event.

    Args:
        logger: Target logger.
        level: Logging level such as ``logging.INFO``.
        event: Human readable event message, lower case English.
        call_id: SIP Call-ID of the affected call, when known.
        direction: One of :class:`LogDirection` values.
        peer: Remote address involved, when known.
        **extra: Additional structured fields rendered into the log line.
    """
    if not logger.isEnabledFor(level):
        return
    logger.log(
        level,
        event,
        # stacklevel=2 attributes the line to the caller of log_event, not to this
        # wrapper, so the `module` field names the module that raised the event.
        stacklevel=2,
        extra={
            "call_id": call_id or DEFAULT_UNKNOWN,
            "direction": direction,
            "peer": peer or DEFAULT_UNKNOWN,
            **extra,
        },
    )


def configure_logging(level: str = "INFO", *, structured: bool = True) -> None:
    """Install the application log handler on the root logger.

    Args:
        level: Log level name, for example ``INFO`` or ``DEBUG``.
        structured: Emit JSON when true, a human readable single line otherwise.
    """
    root = logging.getLogger()
    for previous in list(root.handlers):
        root.removeHandler(previous)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        StructuredFormatter()
        if structured
        else logging.Formatter("%(asctime)s %(levelname)s %(module)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
