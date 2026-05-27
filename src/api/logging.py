import logging
import json
import contextvars
from typing import Any

# Context variable to hold per-request values (request_id, user, etc.)
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # attach request_id if available
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_record["request_id"] = request_id

        # include any non-standard attributes present on the record under "extra"
        extra = {}
        for k, v in record.__dict__.items():
            if k in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
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
                "message",
                "request_id",
            ):
                continue
            try:
                json.dumps(v)
                extra[k] = v
            except Exception:
                extra[k] = repr(v)

        if extra:
            log_record["extra"] = extra

        if record.exc_info:
            import traceback

            log_record["exception"] = "".join(traceback.format_exception(*record.exc_info))

        # ensure ASCII-safe output but keep unicode when possible
        return json.dumps(log_record, ensure_ascii=False)


class ContextVarFilter(logging.Filter):
    """Inject contextvar values into the LogRecord so formatters can include them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with a JSON formatter and contextvar filter.

    Idempotent: calling multiple times will replace handlers on the root logger.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(ContextVarFilter())

    root = logging.getLogger()
    # replace handlers to avoid duplicate logging during re-imports
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(level)


__all__ = ["setup_logging", "request_id_var"]
