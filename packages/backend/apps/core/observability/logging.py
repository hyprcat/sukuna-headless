from __future__ import annotations

from typing import Any

import structlog


def configure_structlog() -> None:
    """Configure structlog for stdlib pass-through."""
    structlog.configure(
        processors=_structlog_processors(),
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _structlog_processors() -> list[Any]:
    return [
        structlog.stdlib.filter_by_level,
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]


def stdlib_pre_chain() -> list[Any]:
    """Foreign pre-chain shared with the JSON ``ProcessorFormatter``."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
