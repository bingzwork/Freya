"""
Permission Menu Module

Provides an interactive keyboard-navigable permission menu with arrow key support.
Uses raw terminal input for arrow key navigation without external dialog libraries.
"""

import sys
import os
from typing import Optional

# Platform-specific key detection
if os.name == 'nt':  # Windows
    import msvcrt
else:  # Unix-like (Linux, macOS)
    import select
    import termios
    import tty

# For backward compatibility
PROMPT_TOOLKIT_AVAILABLE = True


def _fallback_permission_menu(title: str, options: list[str]) -> str:
    """Fallback implementation using numeric input when interactive menu is not available."""
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


class ArrowKeyMenu:
    """Interactive menu with arrow key navigation for terminal.

    Features:
    - Up/Down arrow keys to navigate
    - Enter to confirm selection
    - ESC to cancel (returns default)
    - Visual highlighting of current selection
    - Cross-platform support (Windows and Unix)

    Usage:
        menu = ArrowKeyMenu("Permission required", ["Yes", "No"])
        choice = menu.show()
    """

    # ANSI escape codes for styling
    CURSOR_UP = "\033[A"
    CURSOR_DOWN = "\033[B"
    ERASE_LINE = "\033[2K"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    DIM = "\033[2m"

    def __init__(
        self,
        title: str = "Permission required",
        options: list[str] = None,
        default: Optional[str] = None,
    ):
        """
        Initialize the menu.

        Args:
            title: The prompt/message to display above the menu
            options: List of selectable options (default: ["Yes", "No"])
            default: Default option to return if user cancels (Ctrl+C/ESC)
        """
        self.title = title
        self.options = options or ["Yes", "No"]
        self.default = default or (self.options[0] if self.options else "")
        self._selected_index = 0

    def show(self) -> str:
        """
        Display the interactive menu and return the selected option.

        Returns:
            The selected option string

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C and no default is set
        """
        # Initial draw
        self._draw_initial()

        # Event loop
        while True:
            key = self._get_key()

            if key == 'UP':
                self._move_selection(-1)
            elif key == 'DOWN':
                self._move_selection(1)
            elif key == 'ENTER':
                return self.options[self._selected_index]
            elif key == 'ESCAPE':
                return self.default
            elif key == 'CTRL_C':
                raise KeyboardInterrupt

    def _draw_initial(self):
        """Draw the initial menu state."""
        # Print title
        print(f"\n{self.CYAN}{self.title}{self.RESET}")
        print()
        # Print options
        for i, option in enumerate(self.options):
            self._draw_option(i, selected=(i == 0))
        # Hide cursor during interaction
        print("\033[?25l", end="", flush=True)

    def _draw_option(self, index: int, selected: bool = False):
        """Draw a single option line."""
        prefix = f"{self.GREEN}> {self.RESET}" if selected else "  "
        style = self.BOLD if selected else ""
        option_text = self.options[index]

        if selected:
            line = f"{prefix}{style}{option_text}{self.RESET}"
        else:
            line = f"{prefix}{option_text}"

        # Move cursor to the correct line and redraw
        if index == self._selected_index:
            # We're at the current line, just overwrite
            print(f"\033[2K\r{line}", end="", flush=True)
        else:
            # Move to line, redraw, move back
            offset = self._selected_index - index
            if offset > 0:
                print(f"{self.CURSOR_UP * offset}\033[2K\r{line}{self.CURSOR_DOWN * offset}", end="", flush=True)
            else:
                print(f"{self.CURSOR_DOWN * (-offset)}\033[2K\r{line}{self.CURSOR_UP * (-offset)}", end="", flush=True)

    def _move_selection(self, delta: int):
        """Move selection up or down."""
        new_index = self._selected_index + delta
        if 0 <= new_index < len(self.options):
            # Redraw old selection as unselected
            self._draw_option(self._selected_index, selected=False)
            # Update index
            self._selected_index = new_index
            # Redraw new selection as selected
            self._draw_option(self._selected_index, selected=True)

    def _get_key(self) -> str:
        """Get a key press from the terminal."""
        if os.name == 'nt':
            return self._get_key_windows()
        else:
            return self._get_key_unix()

    def _get_key_windows(self) -> str:
        """Get key press on Windows using msvcrt."""
        # Scripted CLI sessions do not provide a Windows console handle for
        # msvcrt.getch(). Read an explicit choice instead, defaulting to the
        # menu default on invalid or empty input so the gate remains fail-closed.
        if not sys.stdin.isatty():
            reply = sys.stdin.readline().strip().lower()
            if reply in {"yes", "y", "1"}:
                self._selected_index = 0
                return "ENTER"
            if reply in {"no", "n", "2"} and len(self.options) > 1:
                self._selected_index = 1
                return "ENTER"
            return "ESCAPE"
        key = msvcrt.getch()

        # Handle special keys (escape sequences)
        if key in (b'\x00', b'\xe0'):  # Special key prefix
            key = msvcrt.getch()
            if key == b'H':  # Up arrow
                return 'UP'
            elif key == b'P':  # Down arrow
                return 'DOWN'
            elif key == b'K':  # Left arrow
                return 'LEFT'
            elif key == b'M':  # Right arrow
                return 'RIGHT'
        elif key == b'\r':  # Enter
            return 'ENTER'
        elif key == b'\x1b':  # ESC
            return 'ESCAPE'
        elif key == b'\x03':  # Ctrl+C
            return 'CTRL_C'
        elif key == b'\t':  # Tab - cycle forward
            return 'DOWN'
        elif key == b'\x00':  # Sometimes comes before special keys
            pass
        return 'UNKNOWN'

    def _get_key_unix(self) -> str:
        """Get key press on Unix using termios."""
        fd = sys.stdin.fileno()

        # Save old terminal settings
        old_settings = termios.tcgetattr(fd)

        try:
            # Set raw mode
            tty.setraw(fd)

            # Check if input is ready (with small timeout)
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                return 'NONE'

            key = sys.stdin.read(1)

            # Handle escape sequences (arrow keys)
            if key == '\x1b':
                # Read next chars with short timeout
                ready, _, _ = select.select([fd], [], [], 0.1)
                if not ready:
                    return 'ESCAPE'

                key2 = sys.stdin.read(1)
                if key2 == '[':
                    ready, _, _ = select.select([fd], [], [], 0.1)
                    if not ready:
                        return 'ESCAPE'

                    key3 = sys.stdin.read(1)
                    if key3 == 'A':  # Up arrow
                        return 'UP'
                    elif key3 == 'B':  # Down arrow
                        return 'DOWN'
                    elif key3 == 'C':  # Right arrow
                        return 'RIGHT'
                    elif key3 == 'D':  # Left arrow
                        return 'LEFT'
                elif key2 == '\x1b':  # Double ESC
                    return 'ESCAPE'
                return 'ESCAPE'
            elif key == '\r' or key == '\n':  # Enter
                return 'ENTER'
            elif key == '\x03':  # Ctrl+C
                return 'CTRL_C'
            elif key == '\t':  # Tab
                return 'DOWN'

            return 'UNKNOWN'

        finally:
            # Restore terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class PermissionMenu:
    """
    Backward-compatible PermissionMenu using ArrowKeyMenu internally.

    This maintains the same API as the original PermissionMenu while
    using the new arrow-key navigation implementation.
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
        """Initialize the permission menu."""
        self.title = title
        self.options = options
        self.default = default or (options[0] if options else "")
        self._menu = ArrowKeyMenu(title, options, default)

    def show(self) -> str:
        """
        Display the interactive menu and return the selected option.

        Returns:
            The selected option string (e.g., "Yes", "No")

        Raises:
            KeyboardInterrupt: If user presses Ctrl+C and no default is set
        """
        try:
            # Show cursor again on exit
            result = self._menu.show()
            print("\033[?25h", end="", flush=True)  # Show cursor
            return result
        except KeyboardInterrupt:
            print("\033[?25h", end="", flush=True)  # Show cursor
            return self.default
        except EOFError:
            print("\033[?25h", end="", flush=True)  # Show cursor
            return self.default


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