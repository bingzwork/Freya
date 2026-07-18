"""
UI module for Freya AI Agent.

Contains terminalUI components including permission menus.
"""

from app.ui.permission_menu import (
 PermissionMenu,
 permission_prompt,
 PROMPT_TOOLKIT_AVAILABLE,
)

__all__ = [
 "PermissionMenu",
 "permission_prompt",
 "PROMPT_TOOLKIT_AVAILABLE",
]
