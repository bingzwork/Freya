"""Tests for Runtime Context Module.

This module tests the runtime context functionality that provides
environment awareness for Freya.
"""

import os
import pytest
from unittest.mock import patch

from app.intent.runtime_context import (
    RuntimeContext,
    get_runtime_context,
    set_runtime_context,
    reset_runtime_context,
)


class TestRuntimeContext:
    """Test RuntimeContext dataclass."""

    def test_detect_creates_context(self):
        """Test that detect() creates a valid context."""
        ctx = RuntimeContext.detect()
        assert ctx is not None
        assert isinstance(ctx, RuntimeContext)

    def test_os_properties(self):
        """Test OS detection."""
        ctx = RuntimeContext.detect()
        assert ctx.os_name in ["Windows", "Linux", "Darwin"]
        assert ctx.os_version is not None
        assert ctx.os_family in ["windows", "linux", "macos"]

    def test_shell_properties(self):
        """Test shell detection."""
        ctx = RuntimeContext.detect()
        assert ctx.shell_name is not None
        # Shell path may be None on some systems

    def test_python_properties(self):
        """Test Python detection."""
        ctx = RuntimeContext.detect()
        assert ctx.python_version is not None
        assert ctx.python_major > 0
        assert ctx.python_minor >= 0
        assert ctx.python_patch >= 0
        assert ctx.python_executable is not None

    def test_working_directory(self):
        """Test working directory detection."""
        ctx = RuntimeContext.detect()
        assert ctx.working_directory is not None
        assert os.path.isdir(ctx.working_directory)

    def test_environment(self):
        """Test environment variable collection."""
        ctx = RuntimeContext.detect()
        assert isinstance(ctx.environment, dict)

    def test_is_windows(self):
        """Test is_windows method."""
        ctx = RuntimeContext.detect()
        assert isinstance(ctx.is_windows(), bool)

    def test_is_linux(self):
        """Test is_linux method."""
        ctx = RuntimeContext.detect()
        assert isinstance(ctx.is_linux(), bool)

    def test_is_macos(self):
        """Test is_macos method."""
        ctx = RuntimeContext.detect()
        assert isinstance(ctx.is_macos(), bool)

    def test_only_one_os_true(self):
        """Test that only one OS check is true."""
        ctx = RuntimeContext.detect()
        true_count = sum([ctx.is_windows(), ctx.is_linux(), ctx.is_macos()])
        assert true_count == 1, f"Expected exactly one OS to be true, got {true_count}"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        ctx = RuntimeContext.detect()
        d = ctx.to_dict()
        assert "os" in d
        assert "shell" in d
        assert "python" in d
        assert "working_directory" in d
        assert "environment" in d

    def test_get_system_prompt_suffix(self):
        """Test system prompt suffix generation."""
        ctx = RuntimeContext.detect()
        suffix = ctx.get_system_prompt_suffix()
        assert isinstance(suffix, str)
        assert "RUNTIME CONTEXT" in suffix
        assert ctx.os_name in suffix
        assert ctx.shell_name in suffix
        assert ctx.python_version in suffix

    def test_get_command_hint(self):
        """Test command hint generation."""
        ctx = RuntimeContext.detect()
        hint = ctx.get_command_hint()
        assert isinstance(hint, str)

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_windows_command_hint(self):
        """Test command hint for Windows."""
        with patch("platform.system") as mock_system:
            mock_system.return_value = "Windows"
            reset_runtime_context()
            ctx = get_runtime_context()
            hint = ctx.get_command_hint()
            # On Windows, should mention PowerShell or CMD
            assert "PowerShell" in hint or "Windows" in hint or "CMD" in hint

    def test_unix_command_hint(self):
        """Test command hint for Unix.

        The Unix branch is exercised by patching ``platform.system`` to
        ``"Linux"``, so this test is platform-agnostic and runs on every OS.
        """
        with patch("platform.system") as mock_system:
            mock_system.return_value = "Linux"
            reset_runtime_context()
            ctx = get_runtime_context()
            hint = ctx.get_command_hint()
            # The Unix branch should mention Unix / Linux / bash commands.
            assert "Unix" in hint or "Linux" in hint or "bash" in hint

    def test_repr(self):
        """Test string representation."""
        ctx = RuntimeContext.detect()
        repr_str = repr(ctx)
        assert "RuntimeContext" in repr_str
        assert ctx.os_family in repr_str
        assert ctx.shell_name in repr_str


class TestGlobalContextManagement:
    """Test global context management functions."""

    def setup_method(self):
        """Reset context before each test."""
        reset_runtime_context()

    def teardown_method(self):
        """Reset context after each test."""
        reset_runtime_context()

    def test_get_runtime_context(self):
        """Test get_runtime_context returns a valid context."""
        ctx = get_runtime_context()
        assert isinstance(ctx, RuntimeContext)

    def test_get_runtime_context_caches(self):
        """Test that get_runtime_context caches the result."""
        ctx1 = get_runtime_context()
        ctx2 = get_runtime_context()
        assert ctx1 is ctx2, "Context should be cached"

    def test_set_runtime_context(self):
        """Test set_runtime_context."""
        with patch("platform.system") as mock_system:
            mock_system.return_value = "Linux"
            reset_runtime_context()
            ctx = RuntimeContext.detect()
            set_runtime_context(ctx)

            retrieved = get_runtime_context()
            assert retrieved is ctx

    def test_reset_runtime_context(self):
        """Test reset_runtime_context."""
        ctx1 = get_runtime_context()
        reset_runtime_context()
        ctx2 = get_runtime_context()
        assert ctx1 is not ctx2, "Context should be different after reset"


class TestOSNormalization:
    """Test OS family normalization."""

    def test_normalize_windows(self):
        """Test Windows normalization."""
        assert RuntimeContext._normalize_os_family("Windows") == "windows"
        assert RuntimeContext._normalize_os_family("windows") == "windows"
        assert RuntimeContext._normalize_os_family("WIN10") == "win10"

    def test_normalize_linux(self):
        """Test Linux normalization."""
        assert RuntimeContext._normalize_os_family("Linux") == "linux"
        assert RuntimeContext._normalize_os_family("linux") == "linux"

    def test_normalize_macos(self):
        """Test macOS normalization."""
        assert RuntimeContext._normalize_os_family("Darwin") == "macos"
        assert RuntimeContext._normalize_os_family("darwin") == "macos"


class TestPythonVersionParsing:
    """Test Python version parsing."""

    def test_parse_standard_version(self):
        """Test parsing standard version format."""
        major, minor, patch = RuntimeContext._parse_python_version("3.11.6")
        assert major == 3
        assert minor == 11
        assert patch == 6

    def test_parse_short_version(self):
        """Test parsing short version format."""
        major, minor, patch = RuntimeContext._parse_python_version("3.11")
        assert major == 3
        assert minor == 11
        assert patch == 0

    def test_parse_single_digit_version(self):
        """Test parsing single digit version."""
        major, minor, patch = RuntimeContext._parse_python_version("3")
        assert major == 3
        assert minor == 0
        assert patch == 0

    def test_parse_dev_version(self):
        """Test parsing dev version."""
        major, minor, patch = RuntimeContext._parse_python_version("3.11.0a1")
        assert major == 3
        assert minor == 11
        assert patch == 0
