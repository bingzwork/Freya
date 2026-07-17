from pathlib import Path

from app.core.project_index import ProjectIndex
from app.core.symbol_index import SymbolIndex
from app.intelligence.file_locator import FileLocator
from app.intelligence.context_builder import ContextBuilder
from app.intelligence.dependency_graph import DependencyGraph
from app.intelligence.lexical_search import LexicalSearch


def test_project_index_skips_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('hello')", encoding="utf-8")
    ignored = tmp_path / ".venv" / "ignored.py"
    ignored.parent.mkdir()
    ignored.write_text("print('ignored')", encoding="utf-8")

    index = ProjectIndex(tmp_path)
    files = index.build()

    assert set(files) == {"app.py"}


def test_symbol_index_and_file_locator_find_symbols(tmp_path: Path) -> None:
    source = "class ToolManager:\n    def execute(self):\n        return True\n"
    (tmp_path / "tools.py").write_text(source, encoding="utf-8")
    symbols = SymbolIndex(tmp_path)
    symbols.build()

    match = FileLocator(symbols).best_match("toolmanager")

    assert match["file"] == "tools.py"
    assert match["type"] == "class"
    assert match["name"] == "ToolManager"
    assert symbols.get_symbol_source("tools.py", match) == source


def test_context_builder_extracts_symbol_and_local_dependency(tmp_path: Path) -> None:
    (tmp_path / "dependency.py").write_text(
        "def helper():\n    return 'dependency'\n",
        encoding="utf-8",
    )
    (tmp_path / "service.py").write_text(
        "from dependency import helper\n\nclass Service:\n    def run(self):\n        return helper()\n",
        encoding="utf-8",
    )
    symbols = SymbolIndex(tmp_path)
    symbols.build()
    graph = DependencyGraph(symbols)
    graph.build()

    match = FileLocator(symbols).best_match("service")
    context = ContextBuilder(symbols, graph).build([match])

    assert "class Service" in context
    assert "DEPENDENCY: dependency.py" in context
    assert "def helper" in context


def test_lexical_search_ranks_code_by_task_language(tmp_path: Path) -> None:
    (tmp_path / "storage.py").write_text(
        "def save_project_memory():\n    \"\"\"Persist project memory safely.\"\"\"\n",
        encoding="utf-8",
    )
    (tmp_path / "display.py").write_text("def render_screen():\n    pass\n", encoding="utf-8")
    symbols = SymbolIndex(tmp_path)
    symbols.build()

    results = LexicalSearch(symbols).search("persist memory safely")

    assert results[0]["file"] == "storage.py"
    assert results[0]["name"] == "save_project_memory"
