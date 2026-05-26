import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.logging_context import LoggingContextFilter, iter_record_fields


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": settings.app_name,
            "env": settings.app_env,
        }

        payload.update(iter_record_fields(record))
        payload.setdefault("event", record.getMessage())

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextLogFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        context = iter_record_fields(record)
        base = super().format(record)
        if not context:
            return base
        context_repr = " ".join(
            f"{key}={value}" for key, value in sorted(context.items())
        )
        return f"{base} | {context_repr}"


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if settings.use_json_logs:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(TextLogFormatter())
    handler.addFilter(LoggingContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for logger_name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
