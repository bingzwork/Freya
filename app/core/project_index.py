from pathlib import Path


class ProjectIndex:

    IGNORE = {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".idea",
        ".vscode",
    }

    EXTENSIONS = {
        ".py",
        ".json",
        ".md",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
    }

    def __init__(self, workspace):

        self.workspace = Path(workspace)
        self.files = {}

    def build(self):

        self.files.clear()

        for path in self.workspace.rglob("*"):

            if not path.is_file():
                continue

            if any(part in self.IGNORE for part in path.parts):
                continue

            if path.suffix.lower() not in self.EXTENSIONS:
                continue

            try:

                relative = str(path.relative_to(self.workspace))

                self.files[relative] = path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )

            except Exception:
                pass

        return self.files

    def summary(self):

        return "\n".join(self.files.keys())

    def get(self, path):

        return self.files.get(path, "")