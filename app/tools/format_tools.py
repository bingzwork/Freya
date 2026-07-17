from pathlib import Path
import subprocess

def format_file(path: str) -> str:
    """Format a Python file using black.

    Args:
        path: Relative path to the file from the workspace root.

    Returns:
        Status message.
    """
    try:
        file_path = Path(path)
        if not file_path.is_absolute():
            # Assume relative to workspace; ToolManager will handle safety
            pass
        # Ensure it's a .py file
        if file_path.suffix.lower() != ".py":
            return f"Error: Only .py files can be formatted, got {file_path.suffix}"
        # Run black
        result = subprocess.run(
            ["black", "--quiet", str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return f"Successfully formatted {path}"
        else:
            # If black failed to format (e.g., syntax error), return stderr
            return f"Black failed to format {path}: {result.stderr[:200]}"
    except FileNotFoundError:
        return "Error: 'black' not installed. Install with `pip install black`."
    except Exception as e:
        return f"Unexpected error: {e}"
