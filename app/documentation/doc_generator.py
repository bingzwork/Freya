"""Documentation generator for automatic documentation creation.

This module provides functionality for generating various types of
documentation from code and metadata.
"""

import ast
import inspect
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid


class DocType(Enum):
    """Types of documentation that can be generated."""
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    API = "api"
    README = "readme"
    CHANGELOG = "changelog"
    TUTORIAL = "tutorial"
    REFERENCE = "reference"


class DocFormat(Enum):
    """Formats for documentation output."""
    MARKDOWN = "markdown"
    HTML = "html"
    RST = "rst"
    TEXT = "text"


@dataclass
class DocumentationGenerator:
    """Generates documentation from source code and metadata."""

    workspace: Optional[str] = None
    project_name: str = "Freya"
    output_dir: str = "docs"
    include_private: bool = False
    include_inherited: bool = True
    max_depth: int = 3

    def __post_init__(self):
        self._workspace = Path(self.workspace) if self.workspace else Path(".")
        self._output_dir = self._workspace / self.output_dir
        self._scanned_modules: Set[str] = set()

    def _get_module_path(self, module_name: str) -> Optional[Path]:
        """Find the file path for a module."""
        # Try to find in the workspace
        for ext in ["", ".py"]:
            path = self._workspace / (module_name.replace(".", "/") + ext)
            if path.exists():
                return path

        # Try as a file
        path = self._workspace / f"{module_name}.py"
        if path.exists():
            return path

        return None

    def _parse_docstring(self, docstring: str) -> Dict[str, Any]:
        """Parse a docstring into structured data."""
        result: Dict[str, Any] = {
            "short": "",
            "long": "",
            "args": {},
            "returns": None,
            "raises": [],
            "examples": [],
        }

        if not docstring:
            return result

        lines = [line.strip() for line in docstring.strip().split("\n")]

        # Extract short description (first line)
        if lines:
            result["short"] = lines[0]
            long_lines = lines[1:]
        else:
            long_lines = []

        # Parse rest of docstring
        current_section = None
        current_content: List[str] = []
        long_description: List[str] = []

        for line in long_lines:
            if not line:
                continue

            # Check for section headers (Google/NumPy style)
            section_match = re.match(r"^([A-Za-z_]+):\s*", line)
            if section_match and current_section:
                # Save previous section
                if current_section == "long":
                    result["long"] = "\n".join(long_description)
                else:
                    result[current_section] = " ".join(current_content)
                current_section = section_match.group(1).lower()
                current_content = [line[section_match.end():].strip()]
            elif section_match and not current_section:
                # First section after short description is part of long description
                long_description.append(line)
                current_section = None
            else:
                if current_section:
                    current_content.append(line)
                else:
                    long_description.append(line)

        # Save long description
        if long_description:
            result["long"] = "\n".join(long_description)

        # Save last section
        if current_section and current_content:
            result[current_section] = " ".join(current_content)

        # Parse args
        if "args" in result and isinstance(result["args"], str):
            args_dict = {}
            for arg_line in result["args"].split(","):
                arg_line = arg_line.strip()
                if " " in arg_line:
                    name, desc = arg_line.split(" ", 1)
                    args_dict[name.strip()] = desc.strip()
                elif arg_line:
                    args_dict[arg_line] = ""
            result["args"] = args_dict

        # Parse examples
        if "examples" in result and isinstance(result["examples"], str):
            result["examples"] = [ex.strip() for ex in result["examples"].split("\n\n") if ex.strip()]

        # Parse raises
        if "raises" in result and isinstance(result["raises"], str):
            result["raises"] = [r.strip() for r in result["raises"].split(",") if r.strip()]

        return result

    def _extract_class_info(self, node: ast.ClassDef) -> Dict[str, Any]:
        """Extract information from a class AST node."""
        docstring = ast.get_docstring(node) or ""
        parsed_doc = self._parse_docstring(docstring)

        bases = [base.id if isinstance(base, ast.Name) else str(base) for base in node.bases]

        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name.startswith("_") and not self.include_private:
                    continue
                methods.append(self._extract_function_info(item, is_method=True))

        return {
            "name": node.name,
            "docstring": docstring,
            "short_description": parsed_doc["short"],
            "long_description": parsed_doc.get("long", ""),
            "bases": bases,
            "methods": methods,
            "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
        }

    def _extract_function_info(self, node: ast.FunctionDef, is_method: bool = False) -> Dict[str, Any]:
        """Extract information from a function AST node."""
        docstring = ast.get_docstring(node) or ""
        parsed_doc = self._parse_docstring(docstring)

        # Extract arguments
        args = []
        for arg in node.args.args:
            arg_info: Dict[str, Any] = {"name": arg.arg}
            if arg.annotation:
                arg_info["type"] = ast.unparse(arg.annotation) if hasattr(ast, 'unparse') else str(arg.annotation)
            args.append(arg_info)

        # Extract return type
        return_type = None
        if node.returns:
            return_type = ast.unparse(node.returns) if hasattr(ast, 'unparse') else str(node.returns)

        # Extract default values
        defaults = []
        for default in node.args.defaults:
            defaults.append(ast.unparse(default) if hasattr(ast, 'unparse') else str(default))

        return {
            "name": node.name,
            "docstring": docstring,
            "short_description": parsed_doc["short"],
            "long_description": parsed_doc.get("long", ""),
            "args": args,
            "return_type": return_type,
            "returns": parsed_doc.get("returns"),
            "raises": parsed_doc.get("raises", []),
            "examples": parsed_doc.get("examples", []),
            "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
            "is_method": is_method,
            "is_private": node.name.startswith("_"),
        }

    def _parse_module_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse a Python module file and extract documentation."""
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {"error": f"Syntax error in {file_path}"}

        module_doc = {
            "path": str(file_path),
            "name": file_path.stem,
            "package": file_path.parent.name if len(file_path.parts) > 1 else "",
            "classes": [],
            "functions": [],
            "imports": [],
            "docstring": ast.get_docstring(tree) or "",
        }

        parsed_doc = self._parse_docstring(module_doc["docstring"])
        module_doc["short_description"] = parsed_doc["short"]
        module_doc["long_description"] = parsed_doc.get("long", "")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if not node.name.startswith("_") or self.include_private:
                    class_info = self._extract_class_info(node)
                    module_doc["classes"].append(class_info)
            elif isinstance(node, ast.FunctionDef):
                if not node.name.startswith("_") or self.include_private:
                    if not any(isinstance(n, ast.ClassDef) and node in n.body for n in ast.walk(tree)):
                        func_info = self._extract_function_info(node)
                        module_doc["functions"].append(func_info)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_doc["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    module_doc["imports"].append(f"{node.module}.{alias.name}")

        return module_doc

    def scan_module(self, module_name: str) -> Dict[str, Any]:
        """Scan a module and extract documentation information.

        Args:
            module_name: The name of the module to scan (e.g., 'app.core.config')

        Returns:
            Dictionary containing module documentation information
        """
        file_path = self._get_module_path(module_name)
        if not file_path:
            return {"error": f"Module {module_name} not found"}

        return self._parse_module_file(file_path)

    def scan_directory(self, dir_path: str) -> List[Dict[str, Any]]:
        """Scan a directory for Python files and extract documentation.

        Args:
            dir_path: The directory path to scan

        Returns:
            List of module documentation dictionaries
        """
        path = self._workspace / dir_path if not Path(dir_path).is_absolute() else Path(dir_path)
        modules = []

        for py_file in path.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_doc = self._parse_module_file(py_file)
            modules.append(module_doc)

        return modules

    def generate_module_doc(
        self,
        module_name: str,
        output_format: DocFormat = DocFormat.MARKDOWN,
    ) -> str:
        """Generate documentation for a single module.

        Args:
            module_name: The name of the module
            output_format: The output format

        Returns:
            Generated documentation string
        """
        module_info = self.scan_module(module_name)
        if "error" in module_info:
            return f"# Error: {module_info['error']}"

        return self._format_module_doc(module_info, output_format)

    def _format_module_doc(self, module_info: Dict[str, Any], output_format: DocFormat) -> str:
        """Format module documentation in the specified format."""
        lines = []

        if output_format == DocFormat.MARKDOWN:
            lines.append(f"# {module_info['name']}")
            lines.append("")
            lines.append(module_info.get("short_description", ""))
            lines.append("")

            if module_info.get("long_description"):
                lines.append(module_info["long_description"])
                lines.append("")

            # Classes
            if module_info.get("classes"):
                lines.append("## Classes")
                lines.append("")
                for cls in module_info["classes"]:
                    lines.append(f"### `{cls['name']}`")
                    lines.append("")
                    lines.append(cls.get("short_description", ""))
                    lines.append("")

                    if cls.get("bases"):
                        lines.append(f"**Bases:** {', '.join(cls['bases'])}")
                        lines.append("")

                    if cls.get("methods"):
                        lines.append("#### Methods")
                        lines.append("")
                        for method in cls["methods"]:
                            if method.get("is_private") and not self.include_private:
                                continue
                            args = ", ".join([a["name"] for a in method.get("args", [])])
                            lines.append(f"- **`{method['name']}({args})`**: {method.get('short_description', '')}")
                        lines.append("")

            # Functions
            if module_info.get("functions"):
                lines.append("## Functions")
                lines.append("")
                for func in module_info["functions"]:
                    if func.get("is_private") and not self.include_private:
                        continue
                    args = ", ".join([a["name"] for a in func.get("args", [])])
                    return_type = func.get("return_type", "")
                    lines.append(f"- **`{func['name']}({args}) -> {return_type}`**: {func.get('short_description', '')}")
                lines.append("")

        elif output_format == DocFormat.TEXT:
            lines.append(f"{module_info['name']}")
            lines.append("=" * len(module_info["name"]))
            lines.append("")
            lines.append(module_info.get("short_description", ""))
            # ... (similar structure for text format)

        return "\n".join(lines)

    def generate_api_doc(
        self,
        module_names: List[str],
        output_format: DocFormat = DocFormat.MARKDOWN,
    ) -> str:
        """Generate API documentation for multiple modules.

        Args:
            module_names: List of module names to include
            output_format: The output format

        Returns:
            Generated API documentation string
        """
        lines = []

        if output_format == DocFormat.MARKDOWN:
            lines.append(f"# {self.project_name} API Documentation")
            lines.append("")
            lines.append(f"Generated on {datetime.now(timezone.utc).isoformat()}")
            lines.append("")

            for module_name in module_names:
                module_info = self.scan_module(module_name)
                if "error" not in module_info:
                    lines.append(f"## {module_info['name']}")
                    lines.append("")
                    lines.append(f"**Package:** {module_info.get('package', '')}")
                    lines.append("")
                    lines.append(module_info.get("short_description", ""))
                    lines.append("")

                    # Classes
                    if module_info.get("classes"):
                        lines.append("### Classes")
                        lines.append("")
                        for cls in module_info["classes"]:
                            lines.append(f"#### `{cls['name']}`")
                            lines.append("")
                            lines.append(cls.get("short_description", "No description."))
                            lines.append("")

                            if cls.get("methods"):
                                for method in cls["methods"]:
                                    if method.get("is_private") and not self.include_private:
                                        continue
                                    args = ", ".join([a["name"] for a in method.get("args", [])])
                                    return_type = method.get("return_type", "")
                                    lines.append(f"- `{method['name']}({args}) -> {return_type}`: {method.get('short_description', '')}")
                        lines.append("")

                    # Functions
                    if module_info.get("functions"):
                        lines.append("### Functions")
                        lines.append("")
                        for func in module_info["functions"]:
                            if func.get("is_private") and not self.include_private:
                                continue
                            args = ", ".join([a["name"] for a in func.get("args", [])])
                            return_type = func.get("return_type", "")
                            lines.append(f"- `{func['name']}({args}) -> {return_type}`: {func.get('short_description', '')}")
                        lines.append("")

        return "\n".join(lines)

    def generate_markdown_index(self, modules: List[Dict[str, Any]]) -> str:
        """Generate a markdown index of modules.

        Args:
            modules: List of module info dictionaries

        Returns:
            Markdown index string
        """
        lines = [
            f"# {self.project_name} Documentation",
            "",
            "## Modules",
            "",
        ]

        for module in sorted(modules, key=lambda m: m.get("name", "")):
            path = module.get("path", "")
            lines.append(f"- [{module.get('name', 'Unnamed')}](./{path.replace('.py', '.md')})")

        lines.extend(["", "## Packages", "", ])

        # Group by package
        packages: Dict[str, List[Dict[str, Any]]] = {}
        for module in modules:
            pkg = module.get("package", "")
            if pkg not in packages:
                packages[pkg] = []
            packages[pkg].append(module)

        for pkg, pkg_modules in sorted(packages.items()):
            if pkg:
                lines.append(f"### {pkg}")
                for mod in sorted(pkg_modules, key=lambda m: m.get("name", "")):
                    path = mod.get("path", "")
                    lines.append(f"  - [{mod.get('name', 'Unnamed')}](./{path.replace('.py', '.md')})")

        return "\n".join(lines)

    def generate_to_file(
        self,
        content: str,
        file_path: str,
    ) -> None:
        """Write documentation content to a file.

        Args:
            content: The documentation content
            file_path: The output file path
        """
        output_path = self._output_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

    def generate_all(
        self,
        source_dir: str = "app",
        output_format: DocFormat = DocFormat.MARKDOWN,
    ) -> Dict[str, Any]:
        """Generate documentation for all modules in a directory.

        Args:
            source_dir: The source directory to scan
            output_format: The output format

        Returns:
            Summary of generated documentation
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Scan all modules
        source_path = self._workspace / source_dir
        modules = []

        for py_file in source_path.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_doc = self._parse_module_file(py_file)
            modules.append(module_doc)

            # Generate individual module docs
            relative_path = py_file.relative_to(source_path)
            output_path = self._output_dir / relative_path.with_suffix(".md")
            output_path.parent.mkdir(parents=True, exist_ok=True)

            doc_content = self._format_module_doc(module_doc, output_format)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(doc_content)

        # Generate index
        index_content = self.generate_markdown_index(modules)
        with open(self._output_dir / "index.md", "w", encoding="utf-8") as f:
            f.write(index_content)

        return {
            "total_modules": len(modules),
            "output_dir": str(self._output_dir),
            "generated_files": len(modules) + 1,  # +1 for index
        }


@dataclass
class DocGenerationResult:
    """Result of a documentation generation operation."""
    success: bool
    content: str = ""
    file_path: Optional[str] = None
    error: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)
