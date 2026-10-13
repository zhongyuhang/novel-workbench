"""JSON logs with request and task identifiers."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.redaction import redact_text

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or getattr(record, "request_id", "-")
        record.task_id = task_id_var.get() or getattr(record, "task_id", "-")
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "request_id": getattr(record, "request_id", "-"),
            "task_id": getattr(record, "task_id", "-"),
        }
        path = getattr(record, "path", None)
        if isinstance(path, str):
            payload["path"] = path
        status_code = getattr(record, "status_code", None)
        if isinstance(status_code, int):
            payload["status_code"] = status_code
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise RuntimeError(f"Unsupported LOG_LEVEL: {settings.log_level}")

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestContextFilter())

    app_logger = logging.getLogger("app")
    app_logger.handlers.clear()
    app_logger.setLevel(level)
    app_logger.addHandler(handler)
    app_logger.propagate = False
