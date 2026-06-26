"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Literal


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        log_entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exc"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable log formatter."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True) -> None:
        super().__init__()
        self.use_colors = use_colors and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        if self.use_colors:
            level = f"{self.COLORS.get(level, '')}{level}{self.RESET}"

        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        msg = record.getMessage()

        parts = [ts, f"[{level}]", record.name, msg]

        if record.exc_info and record.exc_info[0]:
            parts.append("\n" + self.formatException(record.exc_info))

        return " ".join(parts)


class LogBufferHandler(logging.Handler):
    """Handler that stores logs in memory for WebSocket streaming."""

    def __init__(self, max_len: int = 500) -> None:
        super().__init__()
        from collections import deque
        self.buffer = deque(maxlen=max_len)
        self.listeners = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.buffer.append(msg)
            for listener in list(self.listeners):
                try:
                    listener(msg)
                except Exception:
                    self.listeners.discard(listener)
        except Exception:
            self.handleError(record)

    def subscribe(self, callback) -> None:
        self.listeners.add(callback)

    def unsubscribe(self, callback) -> None:
        self.listeners.discard(callback)


# Global log buffer instance
log_buffer = LogBufferHandler()


def setup_logging(
    level: str = "INFO",
    fmt: Literal["json", "text"] = "text",
    log_file: str = "",
) -> None:
    """Configure application logging."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(TextFormatter())
    root.addHandler(console_handler)

    # Memory buffer handler (always active, no ANSI colors)
    log_buffer.setFormatter(TextFormatter(use_colors=False))
    root.addHandler(log_buffer)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JSONFormatter())
        root.addHandler(file_handler)

    # Suppress noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
