import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context")

# Attributes on LogRecord that must not be copied into JSON output.
_BUILTIN_LOG_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


def get_log_context() -> dict[str, Any]:
    try:
        return _log_context.get().copy()
    except LookupError:
        return {}


def update_log_context(**fields: Any) -> None:
    current = get_log_context()
    for key, value in fields.items():
        if value is not None:
            current[key] = value
    _log_context.set(current)


def clear_log_context() -> None:
    _log_context.set({})


@contextmanager
def log_context(**fields: Any):
    previous = get_log_context()
    merged = previous.copy()
    for key, value in fields.items():
        if value is not None:
            merged[key] = value
    token = _log_context.set(merged)
    try:
        yield
    finally:
        _log_context.reset(token)


def log_extra(**fields: Any) -> dict[str, Any]:
    """Merge request context with per-line fields for logger.info(..., extra=)."""
    merged = get_log_context()
    merged.update(fields)
    return {key: value for key, value in merged.items() if value is not None}


class LoggingContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_log_context().items():
            setattr(record, key, value)
        return True


def iter_record_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _BUILTIN_LOG_ATTRS or key.startswith("_"):
            continue
        if value is None:
            continue
        fields[key] = value
    return fields
