import logging
import os
from pathlib import Path
from datetime import datetime


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

            file_handler = logging.FileHandler(
                self.log_file,
                encoding="utf-8",
            )

            console_handler = logging.StreamHandler()

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            # File handler: capture everything (DEBUG and above)
            file_handler.setLevel(logging.DEBUG)

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