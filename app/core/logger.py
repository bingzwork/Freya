import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime


class PromptSafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            message = self.format(record)
            sys.stdout.write(message + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


class FreyaLogger:

    def __init__(self, name="Freya"):

        self.name = name

        self.log_dir = Path("data/logs")

        self.log_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = (
            datetime.now()
            .strftime("%Y-%m-%d")
            + ".log"
        )

        self.log_file = self.log_dir / filename

        self.logger = logging.getLogger(name)

        # Set root logger level to DEBUG to capture everything in file
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:

            file_handler = RotatingFileHandler(
                self.log_file,
                maxBytes=int(os.environ.get("FREYA_LOG_MAX_BYTES", 20 * 1024 * 1024)),
                backupCount=int(os.environ.get("FREYA_LOG_BACKUP_COUNT", 7)),
                encoding="utf-8",
            )

            console_handler = PromptSafeStreamHandler()

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            # File handler: capture everything (DEBUG and above)
            # INFO is the normal production level; DEBUG remains opt-in.
            file_level=getattr(logging, os.environ.get("FREYA_LOG_LEVEL", "INFO").upper(), logging.INFO)
            file_handler.setLevel(file_level)

            # Console handler: default to INFO, can be overridden via FREYA_LOG_LEVEL env var
            console_level = os.environ.get("FREYA_LOG_LEVEL", "INFO").upper()
            console_handler.setLevel(getattr(logging, console_level, logging.INFO))

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

        # Trace logging flag - set to True to enable chat/priority trace logs
        self._trace_enabled = os.environ.get("FREYA_TRACE", "false").lower() == "true"

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def debug(self, message):
        self.logger.debug(message)

    def trace(self, message):
        """Trace-level logging (more verbose than DEBUG). Only outputs if FREYA_TRACE=true."""
        if self._trace_enabled:
            self.logger.info(message)  # Use INFO level so console shows it when trace enabled


logger = FreyaLogger()
