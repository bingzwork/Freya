
"""
Unit tests for the PermissionMenu class.

Tests keyboard navigation, selection behavior, and fallback functionality.
"""

import unittest
from unittest.mock import patch, MagicMock
from io import StringIO
import sys

from app.ui.permission_menu import (
    PermissionMenu,
    permission_prompt,
    PROMPT_TOOLKIT_AVAILABLE,
    _fallback_permission_menu,
)


class TestFallbackPermissionMenu(unittest.TestCase):
    """Tests for the fallback implementation when prompt_toolkit is not available."""

    def test_fallback_returns_first_option_on_invalid_input(self):
        """Test that fallback returns first option when user enters invalid input."""
        with patch('sys.stdin', StringIO('invalid')):
            result = _fallback_permission_menu('Test prompt', ['Yes', 'No'])
            self.assertEqual(result, 'Yes')

    def test_fallback_returns_selected_option(self):
        """Test that fallback returns the selected option."""
        with patch('sys.stdin', StringIO('2')):
            result = _fallback_permission_menu('Test prompt', ['Yes', 'No'])
            self.assertEqual(result, 'No')

    def test_fallback_handles_empty_options(self):
        """Test that fallback handles empty options list."""
        with patch('sys.stdin', StringIO('1')):
            result = _fallback_permission_menu('Test prompt', [])
            self.assertEqual(result, '')


class TestPermissionPromptFunction(unittest.TestCase):
    """Tests for the permission_prompt convenience function."""

    def test_permission_prompt_default_options(self):
        """Test that permission_prompt uses default options."""
        with patch('app.ui.permission_menu.PermissionMenu') as mock_menu:
            mock_instance = MagicMock()
            mock_instance.show.return_value = 'Yes'
            mock_menu.return_value = mock_instance

            result = permission_prompt()

            mock_menu.assert_called_once_with(
                title='Permission required',
                options=['Yes', 'No'],
                default=None
            )
            mock_instance.show.assert_called_once()
            self.assertEqual(result, 'Yes')

    def test_permission_prompt_custom_options(self):
        """Test that permission_prompt accepts custom options."""
        with patch('app.ui.permission_menu.PermissionMenu') as mock_menu:
            mock_instance = MagicMock()
            mock_instance.show.return_value = 'Always'
            mock_menu.return_value = mock_instance

            result = permission_prompt(
                title='Custom prompt',
                options=['Yes', 'No', 'Always'],
                default='No'
            )

            mock_menu.assert_called_once_with(
                title='Custom prompt',
                options=['Yes', 'No', 'Always'],
                default='No'
            )
            self.assertEqual(result, 'Always')


if __name__ == '__main__':
    unittest.main()

class TestNonTtyPermissionInput(unittest.TestCase):
    def test_non_tty_yes_and_no_are_explicit_choices(self):
        menu = PermissionMenu(options=["Yes", "No"], default="No")
        with patch("os.name", "nt"), patch("sys.stdin", StringIO("No\n")):
            with patch("app.ui.permission_menu.msvcrt.getch") as getch:
                self.assertEqual(menu.show(), "No")
                getch.assert_not_called()

        menu = PermissionMenu(options=["Yes", "No"], default="No")
        with patch("os.name", "nt"), patch("sys.stdin", StringIO("Yes\n")):
            with patch("app.ui.permission_menu.msvcrt.getch") as getch:
                self.assertEqual(menu.show(), "Yes")
                getch.assert_not_called()
