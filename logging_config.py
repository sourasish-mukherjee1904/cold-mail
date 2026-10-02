"""
Logging configuration with credential redaction and clean formatting.
"""

import logging
import os
import re
from typing import Any

# Patterns to mask sensitive information
REDACTION_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|secret|token|password|bearer\s+)(\s*[:=]\s*|\s+)([\'"]?[a-zA-Z0-9_\-\.]{8,}[\'"]?)'), r'\1\2[REDACTED]'),
    (re.compile(r'([a-zA-Z0-9_\-\.]{20,})'), r'[POSSIBLE_TOKEN_REDACTED]'),
]


class SensitiveDataFilter(logging.Filter):
    """Filter that strips out sensitive keys and tokens from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            for pattern, replacement in REDACTION_PATTERNS:
                # Avoid redacting standard UUIDs or URLs unless they look like secrets
                if "key" in msg.lower() or "secret" in msg.lower() or "token" in msg.lower():
                    msg = pattern.sub(replacement, msg)
            record.msg = msg
        return True


def setup_logger(name: str = "outreach", log_file: str = "outreach.log", level: int = logging.INFO) -> logging.Logger:
    """Configures and returns a thread-safe logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(SensitiveDataFilter())
    logger.addHandler(console_handler)

    # File Handler
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(SensitiveDataFilter())
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not initialize file log handler: {e}")

    return logger


logger = setup_logger()
