"""Code Analyzer for static analysis of Python code.

This module provides static analysis capabilities for finding issues
in Python source code.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from app.diagnostics.issue import Issue, IssueSeverity, IssueType, IssueCollection


class CodeAnalyzer:
    """Analyzes Python code for potential issues.

    This class performs static analysis on Python source code to identify
    various types of issues including code quality, potential bugs, and
    performance problems.
    """

    def __init__(self, workspace: str = "."):
        """Initialize the code analyzer.

        Args:
            workspace: The project workspace directory.
        """
        self.workspace = Path(workspace).resolve()
        self._issues: IssueCollection = IssueCollection()

    def analyze(self, paths: Optional[List[str]] = None) -> IssueCollection:
        """Analyze code in specified paths or entire workspace.

        Args:
            paths: List of file or directory paths to analyze. If None, analyzes workspace.
        """
        self._issues = IssueCollection()

        if paths is None:
            paths = [str(self.workspace)]

        for path_str in paths:
            path = Path(path_str).resolve()
            if path.is_file() and path.suffix == ".py":
                self._analyze_file(path)
            elif path.is_dir():
                self._analyze_directory(path)

        return self._issues

    def _analyze_directory(self, directory: Path) -> None:
        """Analyze all Python files in a directory."""
        for py_file in directory.rglob("*.py"):
            # Skip __pycache__ and hidden directories
            if "__pycache__" in str(py_file) or ".git" in str(py_file):
                continue
            self._analyze_file(py_file)

    def _analyze_file(self, file_path: Path) -> None:
        """Analyze a single Python file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()

            # Parse the source
            tree = ast.parse(source, filename=str(file_path))

            # Run all analysis checks
            self._check_unused_imports(tree, file_path, source)
            self._check_unreachable_code(tree, file_path, source)
            self._check_empty_blocks(tree, file_path, source)
            self._check_long_functions(tree, file_path, source)
            self._check_complex_functions(tree, file_path, source)
            self._check_missing_docstrings(tree, file_path, source)
            self._check_missing_type_hints(tree, file_path, source)
            self._check_bare_except(tree, file_path, source)
            self._check_strings_in_code(tree, file_path, source)

        except (SyntaxError, UnicodeDecodeError) as e:
            self._issues.add(Issue(
                id=f"syntax_{file_path.name}",
                title=f"Syntax Error in {file_path.name}",
                description=str(e),
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.BUG,
                location=f"{file_path}:1",
                file_path=str(file_path),
                line_number=1,
            ))
        except Exception as e:
            self._issues.add(Issue(
                id=f"analysis_error_{file_path.name}",
                title=f"Analysis Error in {file_path.name}",
                description=str(e),
                severity=IssueSeverity.WARNING,
                issue_type=IssueType.MAINTENANCE,
                location=f"{file_path}:1",
                file_path=str(file_path),
            ))

    def _check_unused_imports(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for unused imports."""
        # Get all imported names
        imported_names: Dict[str, List[Tuple[int, str]]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name not in imported_names:
                        imported_names[name] = []
                    imported_names[name].append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    full_name = f"{module}.{alias.name}" if module else alias.name
                    if name not in imported_names:
                        imported_names[name] = []
                    imported_names[name].append((node.lineno, full_name))

        # Get all used names
        used_names: Dict[str, bool] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names[node.id] = True
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names[node.value.id] = True

        # Report unused imports
        for name, imports in imported_names.items():
            # Skip __future__ imports and common special names
            if name.startswith("__") or name in ["absolute_import", "division", "print_function", "unicode_literals", "annotations"]:
                continue
            if name not in used_names:
                for lineno, full_name in imports:
                    self._issues.add(Issue(
                        id=f"unused_import_{file_path.name}_{lineno}",
                        title=f"Unused import: {full_name}",
                        description=f"Import '{full_name}' is defined but never used",
                        severity=IssueSeverity.WARNING,
                        issue_type=IssueType.CODE_QUALITY,
                        location=f"{file_path}:{lineno}",
                        file_path=str(file_path),
                        line_number=lineno,
                        fix_suggestion="Remove the unused import",
                        tags=["import", "unused"],
                    ))

    def _check_unreachable_code(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for unreachable code after return/raise/break."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function_unreachable(node, file_path, source)

    def _check_function_unreachable(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, file_path: Path, source: str) -> None:
        """Check for unreachable code in a function."""
        if not func_node.body:
            return

        lines = source.splitlines()
        for i, stmt in enumerate(func_node.body[:-1]):
            next_stmt = func_node.body[i + 1]
            # Check if this statement always exits
            if self._always_exits(stmt):
                # Check if next statement is not part of an else/elif
                self._issues.add(Issue(
                    id=f"unreachable_{file_path.name}_{stmt.lineno}",
                    title="Unreachable code",
                    description=f"Code after line {stmt.lineno} is unreachable",
                    severity=IssueSeverity.WARNING,
                    issue_type=IssueType.CODE_QUALITY,
                    location=f"{file_path}:{next_stmt.lineno}",
                    file_path=str(file_path),
                    line_number=next_stmt.lineno,
                    fix_suggestion="Remove the unreachable code or fix the control flow",
                    tags=["unreachable", "dead_code"],
                ))

    def _always_exits(self, stmt: ast.AST) -> bool:
        """Check if a statement always causes function exit."""
        if isinstance(stmt, ast.Return):
            return True
        if isinstance(stmt, ast.Raise):
            return True
        if isinstance(stmt, ast.Break):
            return True
        if isinstance(stmt, ast.Continue):
            return False  # Continue doesn't exit
        # Check for sys.exit() or os._exit() calls
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if isinstance(call.func, ast.Attribute):
                if call.func.attr in ["exit", "_exit"]:
                    return True
                if call.func.attr == "abort":
                    return True
        return False

    def _check_empty_blocks(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for empty if/for/while/try blocks."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.AsyncFor, ast.AsyncWith)):
                body = getattr(node, "body", [])
                if not body:
                    self._issues.add(Issue(
                        id=f"empty_block_{file_path.name}_{node.lineno}",
                        title="Empty block",
                        description=f"Empty block at line {node.lineno}",
                        severity=IssueSeverity.WARNING,
                        issue_type=IssueType.CODE_QUALITY,
                        location=f"{file_path}:{node.lineno}",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        fix_suggestion="Remove the empty block or add a pass comment",
                        tags=["empty", "block"],
                    ))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.body:
                    self._issues.add(Issue(
                        id=f"empty_{node.__class__.__name__}_{file_path.name}_{node.lineno}",
                        title=f"Empty {node.__class__.__name__}",
                        description=f"Empty {node.__class__.__name__.lower()} at line {node.lineno}",
                        severity=IssueSeverity.WARNING,
                        issue_type=IssueType.CODE_QUALITY,
                        location=f"{file_path}:{node.lineno}",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        tags=["empty"],
                    ))

    def _check_long_functions(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for functions that are too long."""
        threshold = 100  # lines
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start_line = node.lineno
                end_line = node.end_lineno or start_line
                length = end_line - start_line + 1
                if length > threshold:
                    self._issues.add(Issue(
                        id=f"long_function_{file_path.name}_{node.lineno}",
                        title=f"Long function: {node.name}",
                        description=f"Function '{node.name}' is {length} lines long (threshold: {threshold})",
                        severity=IssueSeverity.WARNING,
                        issue_type=IssueType.CODE_QUALITY,
                        location=f"{file_path}:{start_line}-{end_line}",
                        file_path=str(file_path),
                        line_number=start_line,
                        fix_suggestion=f"Consider breaking this function into smaller functions",
                        tags=["long", "function", "refactor"],
                    ))

    def _check_complex_functions(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for functions with high cyclomatic complexity."""
        threshold = 10  # McCabe complexity
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = self._calculate_complexity(node)
                if complexity > threshold:
                    self._issues.add(Issue(
                        id=f"complex_function_{file_path.name}_{node.lineno}",
                        title=f"Complex function: {node.name}",
                        description=f"Function '{node.name}' has cyclomatic complexity {complexity} (threshold: {threshold})",
                        severity=IssueSeverity.WARNING,
                        issue_type=IssueType.CODE_QUALITY,
                        location=f"{file_path}:{node.lineno}",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        fix_suggestion="Consider simplifying this function or breaking it into smaller functions",
                        tags=["complex", "function", "refactor"],
                    ))

    def _calculate_complexity(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """Calculate cyclomatic complexity for a function."""
        complexity = 1  # Base complexity
        for node in ast.walk(func_node):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                complexity += 1
            elif isinstance(node, (ast.And, ast.Or)):
                complexity += 1
            elif isinstance(node, ast.IfExp):
                complexity += 1
        return complexity

    def _check_missing_docstrings(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for missing docstrings in public functions and classes."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Skip private members
                if node.name.startswith("_"):
                    continue
                if not ast.get_docstring(node):
                    self._issues.add(Issue(
                        id=f"missing_docstring_{file_path.name}_{node.lineno}",
                        title=f"Missing docstring: {node.name}",
                        description=f"{node.__class__.__name__} '{node.name}' is missing a docstring",
                        severity=IssueSeverity.INFO,
                        issue_type=IssueType.DOCUMENTATION,
                        location=f"{file_path}:{node.lineno}",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        fix_suggestion="Add a docstring to document this function/class",
                        tags=["docstring", "documentation"],
                    ))

    def _check_missing_type_hints(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for missing type hints in function signatures."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private functions
                if node.name.startswith("_"):
                    continue
                # Check return type
                if not node.returns:
                    self._issues.add(Issue(
                        id=f"missing_return_type_{file_path.name}_{node.lineno}",
                        title=f"Missing return type: {node.name}",
                        description=f"Function '{node.name}' is missing a return type hint",
                        severity=IssueSeverity.INFO,
                        issue_type=IssueType.CODE_QUALITY,
                        location=f"{file_path}:{node.lineno}",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        fix_suggestion="Add a return type hint to the function",
                        tags=["type_hint", "typing"],
                    ))

    def _check_bare_except(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for bare except: clauses."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    self._issues.add(Issue(
                        id=f"bare_except_{file_path.name}_{node.lineno}",
                        title="Bare except clause",
                        description=f"Bare except: clause at line {node.lineno} catches all exceptions",
                        severity=IssueSeverity.ERROR,
                        issue_type=IssueType.BUG,
                        location=f"{file_path}:{node.lineno}",
                        file_path=str(file_path),
                        line_number=node.lineno,
                        fix_suggestion="Specify the exception type to catch, or use 'Exception' at minimum",
                        tags=["exception", "error_handling"],
                    ))

    def _check_strings_in_code(self, tree: ast.AST, file_path: Path, source: str) -> None:
        """Check for potential issues with string literals."""
        # Check for hardcoded passwords/secrets
        password_patterns = [
            r"password\s*=\s*['\"].+['\"]",
            r"password\s*:\s*['\"].+['\"]",
            r"api_key\s*=\s*['\"].+['\"]",
            r"secret\s*=\s*['\"].+['\"]",
        ]

        lines = source.splitlines()
        for i, line in enumerate(lines, 1):
            for pattern in password_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self._issues.add(Issue(
                        id=f"hardcoded_secret_{file_path.name}_{i}",
                        title="Potential hardcoded secret",
                        description=f"Line {i} contains a potential hardcoded password/secret",
                        severity=IssueSeverity.CRITICAL,
                        issue_type=IssueType.SECURITY,
                        location=f"{file_path}:{i}",
                        file_path=str(file_path),
                        line_number=i,
                        code_snippet=line.strip(),
                        fix_suggestion="Use environment variables or a secrets manager for sensitive data",
                        tags=["security", "secret", "password"],
                    ))
                    break  # Only report once per line

    def get_issues(self) -> IssueCollection:
        """Get all collected issues."""
        return self._issues

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the analysis."""
        return {
            "total_issues": len(self._issues.issues),
            "by_severity": self._issues.count_by_severity(),
            "by_type": self._issues.count_by_type(),
        }
