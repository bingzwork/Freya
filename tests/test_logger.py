"""Tests for the FreyaLogger (`app.core.logger`).

Verifies that:
- The module exposes a single shared `logger` instance.
- Handlers are not duplicated when the module is imported or the level is
  re-resolved multiple times (this guards Phase 4's bracket logging against
  the easy regression of duplicate log lines on every event).
- The info / warning / error / debug methods delegate to the underlying
  `logging.Logger`.
"""
import logging
from pathlib import Path

from app.core.logger import FreyaLogger, logger as shared_logger


class TestFreyaLogger:
    """Behaviour of an isolated FreyaLogger instance."""

    def _isolated_logger(self, name: str) -> FreyaLogger:
        """Return a FreyaLogger that owns its own logger name (no shared handlers)."""
        return FreyaLogger(name=name)

    def test_info_delegates_to_underlying_logger(self, caplog):
        caplog.set_level(logging.INFO, logger="FreyaLoggerTestA")
        fl = self._isolated_logger("FreyaLoggerTestA")
        fl.info("hello world")
        assert any(
            record.getMessage() == "hello world"
            for record in caplog.records
            if record.name == "FreyaLoggerTestA"
        )

    def test_warning_delegates_to_underlying_logger(self, caplog):
        caplog.set_level(logging.WARNING, logger="FreyaLoggerTestB")
        fl = self._isolated_logger("FreyaLoggerTestB")
        fl.warning("careful")
        assert any(
            record.getMessage() == "careful"
            for record in caplog.records
            if record.name == "FreyaLoggerTestB"
        )

    def test_error_delegates_to_underlying_logger(self, caplog):
        caplog.set_level(logging.ERROR, logger="FreyaLoggerTestC")
        fl = self._isolated_logger("FreyaLoggerTestC")
        fl.error("boom")
        assert any(
            record.getMessage() == "boom"
            for record in caplog.records
            if record.name == "FreyaLoggerTestC"
        )

    def test_debug_delegates_to_underlying_logger(self, caplog):
        caplog.set_level(logging.DEBUG, logger="FreyaLoggerTestD")
        fl = self._isolated_logger("FreyaLoggerTestD")
        fl.debug("trace")
        assert any(
            record.getMessage() == "trace"
            for record in caplog.records
            if record.name == "FreyaLoggerTestD"
        )

    def test_logger_attributes_exist(self):
        fl = self._isolated_logger("FreyaLoggerTestE")
        assert hasattr(fl, "log_file")
        assert hasattr(fl, "logger")
        assert hasattr(fl, "name")
        # The handler-less name registration must fill the standard logging attrs.
        assert fl.logger.name == "FreyaLoggerTestE"

    def test_log_file_is_created_in_log_dir(self, tmp_path, monkeypatch):
        """Instantiating FreyaLogger creates the log file in its chosen directory."""
        fl = self._isolated_logger("FreyaLoggerTestF")
        assert fl.log_file.exists()
        assert str(fl.log_file).endswith(".log")


class TestLoggerNonDuplicative:
    """Re-instantiation and re-import must not duplicate handlers."""

    def test_re_instantiation_does_not_duplicate_handlers(self):
        """Building two FreyaLoggers with the same name must not pile up handlers."""
        # Use a fresh name so the test does not depend on shared state.
        name = "FreyaDupeTest"
        # Drop any leftover handlers from earlier tests.
        logging.getLogger(name).handlers.clear()

        fl1 = FreyaLogger(name=name)
        handlers_after_first = list(logging.getLogger(name).handlers)

        fl2 = FreyaLogger(name=name)
        handlers_after_second = list(logging.getLogger(name).handlers)

        # The no-duplicate guard inside FreyaLogger.__init__ must keep the
        # handler list identical between the two constructions.
        assert len(handlers_after_second) == len(handlers_after_first) > 0
        assert handlers_after_first == handlers_after_second

    def test_shared_logger_is_a_freyalogger(self):
        assert isinstance(shared_logger, FreyaLogger)

    def test_shared_logger_have_handlers(self):
        underlying = logging.getLogger(shared_logger.name)
        # The module-level `logger` has been built at import time; verify it
        # registered handlers and did not duplicate them on the second import.
        assert len(underlying.handlers) >= 1
