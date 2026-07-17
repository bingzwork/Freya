import ast
from pathlib import Path


class SymbolIndex:

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

    PYTHON_EXTENSIONS = {
        ".py",
    }

    def __init__(self, workspace):

        self.workspace = Path(workspace)

        self.files = {}

        self.symbols = {}


    def clear(self):

        self.files.clear()

        self.symbols.clear()


    def build(self):

        self.clear()

        for file in self.workspace.rglob("*"):

            if not file.is_file():
                continue

            if any(part in self.IGNORE for part in file.parts):
                continue

            if file.suffix.lower() not in self.PYTHON_EXTENSIONS:
                continue

            self.index_file(file)

        return self.symbols


    def index_file(self, path):

        try:

            source = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )

        except Exception:

            return

        relative = str(
            path.relative_to(self.workspace)
        )

        self.files[relative] = source

        try:

            tree = ast.parse(source)

        except Exception:

            return

        symbols = []

        for node in ast.walk(tree):

            if isinstance(node, ast.ClassDef):

                symbols.append(
                    {
                        "type": "class",
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )

            elif isinstance(node, ast.FunctionDef):

                symbols.append(
                    {
                        "type": "function",
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )

            elif isinstance(node, ast.AsyncFunctionDef):

                symbols.append(
                    {
                        "type": "async_function",
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                    }
                )

        self.symbols[relative] = symbols


    def summary(self):

        lines = []

        for file in sorted(self.symbols):

            lines.append(file)

            for symbol in self.symbols[file]:

                lines.append(
                    f"    {symbol['type']}: {symbol['name']} (line {symbol['line']})"
                )

            lines.append("")

        return "\n".join(lines)


    def find_symbol(self, name):

        matches = []

        name = name.lower()

        for file in self.symbols:

            for symbol in self.symbols[file]:

                if name in symbol["name"].lower():

                    matches.append(
                        {
                            "file": file,
                            **symbol,
                        }
                    )

        return matches


    def get_file(self, path):

        return self.files.get(path, "")

    def get_symbol_source(self, path, symbol):
        """Return the exact source lines belonging to an indexed symbol."""
        source = self.get_file(path)
        if not source:
            return ""

        lines = source.splitlines(keepends=True)
        start = symbol["line"] - 1
        end = symbol.get("end_line", symbol["line"])
        return "".join(lines[start:end])
