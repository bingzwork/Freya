"""
Permission Menu Module

Provides an interactive keyboard-navigable permission menu using Prompt Toolkit.
Supports arrow key navigation, highlighting, and cross-platform terminal input.
"""

import sys
from typing import Any, Callable

try:
    from prompt_toolkit.shortcuts import radiolist_dialog
    from prompt_toolkit.styles import Style
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    # Fallback for environments without prompt_toolkit
    PROMPT_TOOLKIT_AVAILABLE = False


def _fallback_permission_menu(title: str, options: list[str]) -> str:
    """Fallback implementation using numeric input when prompt_toolkit is not available."""
    print(f"\n{title}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    print(f"Enter your choice (1-{len(options)}): ", end="", flush=True)
    reply = sys.stdin.readline().strip()
    try:
        idx = int(reply) - 1
        if 0 <= idx < len(options):
            return options[idx]
    except ValueError:
        pass
    return options[0] if options else ""


class PermissionMenu:
    """
    Interactive permission menu with keyboard navigation.

    Supports:
    - Arrow key navigation (Up/Down)
    - Enter key selection
    - Highlighted cursor/pointer indication
    - Cross-platform terminal input
    - Graceful Ctrl+C handling

    Usage:
    menu = PermissionMenu("Permission required", ["Yes", "No"])
    choice = menu.show()
    if choice == "Yes":
        # Grant permission
    """

    DEFAULTS = {
        "title": "Permission required",
        "options": ["Yes", "No"],
    }

    def __init__(
        self,
        title: str = DEFAULTS["title"],
        options: list[str] = DEFAULTS["options"],
        default: str | None = None,
    ):
        """
        Initialize the permission menu.

        Args:
            title: The prompt/message to display
            options: List of selectable options
            default: Default option to return if user cancels (Ctrl+C)
        """
        self.title = title
        self.options = options
        self.default = default or (options[0] if options else "")

    def show(self) -> str:
        """
        Display the interactive menu and return the selected option.

        Returns:
            The selected option string (e.g., "Yes", "No")

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C and no default is set
        """
        if not PROMPT_TOOLKIT_AVAILABLE:
            return _fallback_permission_menu(self.title, self.options)

        return self._show_with_prompt_toolkit()

    def _show_with_prompt_toolkit(self) -> str:
        """Display the menu using Prompt Toolkit."""
        try:
            choice = radiolist_dialog(
                title=self.title,
                text="",
                values=[(option, option) for option in self.options],
                ok_text="Select",
                cancel_text="Cancel",
                style=Style.from_dict({
                    "dialog": "bg:#1e1e1e",
                    "dialog frame.label": "bg:#333333 #ffffff",
                    "dialog.body": "bg:#1e1e1e #ffffff",
                    "radiolist": "fg:#ffffff",
                    "radiolist.selected": "fg:#00ff00 bold",
                    "button": "bg:#333333 fg:#ffffff",
                    "button.focused": "bg:#00ff00 fg:#000000",
                }),
            )
            if choice is None:
                return self.default
            return choice
        except KeyboardInterrupt:
            return self.default
        except EOFError:
            return self.default
        except Exception:
            # Fallback to simple input on any error
            return _fallback_permission_menu(self.title, self.options)


def permission_prompt(
    title: str = "Permission required",
    options: list[str] = None,
    default: str | None = None,
) -> str:
    """
    Convenience function to display a permission prompt.

    This is a simple wrapper around PermissionMenu for one-off prompts.

    Args:
        title: The prompt/message to display
        options: List of selectable options (default: ["Yes", "No"])
        default: Default option to return if user cancels

    Returns:
        The selected option string

    Example:
        choice = permission_prompt("Allow file modification?", ["Yes", "No", "Always"])
        if choice == "Yes":
            # Grant permission
    """
    menu = PermissionMenu(title=title, options=options or ["Yes", "No"], default=default)
    return menu.show()
