"""Project Metadata and Dependency Detection for World Model.

This module provides comprehensive parsing of project configuration files
(pyproject.toml, package.json, Cargo.toml, go.mod, pom.xml, etc.) and
dependency lockfiles (requirements.txt, package-lock.json, yarn.lock,
Cargo.lock, go.sum, etc.) to populate the World Model with rich project
metadata and dependency information.
"""

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from xml.etree import ElementTree as ET

from app.core.logger import logger


@dataclass
class ProjectMetadata:
    """Comprehensive project metadata extracted from configuration files."""
    # Basic identification
    name: str = ""
    version: str = ""
    description: str = ""
    license: str = ""
    authors: List[str] = field(default_factory=list)
    maintainers: List[str] = field(default_factory=list)
    homepage: str = ""
    repository: str = ""
    documentation: str = ""

    # Language and ecosystem
    primary_language: str = ""
    build_system: str = ""
    package_manager: str = ""
    framework: str = ""
    runtime_version: str = ""  # e.g., Python >=3.10, Node >=18

    # Project structure
    entry_points: List[str] = field(default_factory=list)
    modules: List[str] = field(default_factory=list)
    source_directories: List[str] = field(default_factory=list)
    test_directories: List[str] = field(default_factory=list)

    # Python-specific
    python_requires: str = ""
    classifiers: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    # JavaScript/Node-specific
    engines: Dict[str, str] = field(default_factory=dict)
    scripts: Dict[str, str] = field(default_factory=dict)
    browsers_list: List[str] = field(default_factory=list)

    # Rust-specific
    rust_edition: str = ""
    cargo_features: Dict[str, List[str]] = field(default_factory=dict)

    # Go-specific
    go_version: str = ""
    module_path: str = ""

    # Java/Maven-specific
    group_id: str = ""
    artifact_id: str = ""
    packaging: str = "jar"
    parent_pom: Optional[Dict[str, str]] = None

    # Raw configuration for advanced use
    raw_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DependencyInfo:
    """Information about a single dependency."""
    name: str
    version_spec: str = ""  # Original specifier (e.g., ">=1.0", "^2.0", "~1.2.3")
    requested_version: str = ""  # For lockfiles: exact pinned version
    resolved_version: str = ""  # Actually resolved version
    dependency_type: str = "runtime"  # runtime, dev, optional, peer, build, test
    source: str = ""  # pypi, npm, cargo, maven, github, path, etc.
    license: str = ""
    description: str = ""
    repository: str = ""
    homepage: str = ""
    is_direct: bool = True  # Direct vs transitive
    is_outdated: bool = False
    latest_version: str = ""
    vulnerability_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version_spec": self.version_spec,
            "requested_version": self.requested_version,
            "resolved_version": self.resolved_version,
            "dependency_type": self.dependency_type,
            "source": self.source,
            "license": self.license,
            "description": self.description,
            "repository": self.repository,
            "homepage": self.homepage,
            "is_direct": self.is_direct,
            "is_outdated": self.is_outdated,
            "latest_version": self.latest_version,
            "vulnerability_count": self.vulnerability_count,
        }


@dataclass
class DependencySet:
    """A collection of dependencies grouped by type."""
    runtime: List[DependencyInfo] = field(default_factory=list)
    development: List[DependencyInfo] = field(default_factory=list)
    optional: List[DependencyInfo] = field(default_factory=list)
    peer: List[DependencyInfo] = field(default_factory=list)
    build: List[DependencyInfo] = field(default_factory=list)
    test: List[DependencyInfo] = field(default_factory=list)

    def all(self) -> List[DependencyInfo]:
        """Get all dependencies."""
        return (
            self.runtime + self.development + self.optional +
            self.peer + self.build + self.test
        )

    def by_name(self, name: str) -> Optional[DependencyInfo]:
        """Find a dependency by name."""
        for dep in self.all():
            if dep.name.lower() == name.lower():
                return dep
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime": [d.to_dict() for d in self.runtime],
            "development": [d.to_dict() for d in self.development],
            "optional": [d.to_dict() for d in self.optional],
            "peer": [d.to_dict() for d in self.peer],
            "build": [d.to_dict() for d in self.build],
            "test": [d.to_dict() for d in self.test],
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the dependency set."""
        all_deps = self.all()
        outdated = sum(1 for d in all_deps if d.is_outdated)
        vulnerable = sum(1 for d in all_deps if d.vulnerability_count > 0)
        direct = sum(1 for d in all_deps if d.is_direct)
        transitive = len(all_deps) - direct
        return {
            "total": len(all_deps),
            "direct": direct,
            "transitive": transitive,
            "outdated": outdated,
            "vulnerable": vulnerable,
            "by_type": {
                "runtime": len(self.runtime),
                "development": len(self.development),
                "optional": len(self.optional),
                "peer": len(self.peer),
                "build": len(self.build),
                "test": len(self.test),
            }
        }


# ============================================================================
# Project Metadata Parsers
# ============================================================================

class ProjectMetadataParser:
    """Parse project metadata from various configuration files."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def parse_all(self) -> ProjectMetadata:
        """Parse all available project configuration files and merge results."""
        metadata = ProjectMetadata()

        # Parse in priority order (more specific first)
        parsers = [
            ("pyproject.toml", self._parse_pyproject_toml),
            ("package.json", self._parse_package_json),
            ("Cargo.toml", self._parse_cargo_toml),
            ("go.mod", self._parse_go_mod),
            ("pom.xml", self._parse_pom_xml),
            ("build.gradle", self._parse_gradle),
            ("build.gradle.kts", self._parse_gradle_kts),
            ("setup.py", self._parse_setup_py),
            ("setup.cfg", self._parse_setup_cfg),
            ("Pipfile", self._parse_pipfile),
            ("composer.json", self._parse_composer_json),
            ("mix.exs", self._parse_mix_exs),
        ]

        for filename, parser in parsers:
            filepath = self.workspace / filename
            if filepath.exists():
                try:
                    parsed = parser(filepath)
                    if parsed:
                        metadata = self._merge_metadata(metadata, parsed)
                        # Track which config files were found
                        if filename not in metadata.raw_config:
                            metadata.raw_config["config_files"] = metadata.raw_config.get("config_files", [])
                        metadata.raw_config["config_files"].append(filename)
                except Exception as e:
                    logger.warning(f"Failed to parse {filename}: {e}")

        return metadata

    def _merge_metadata(self, base: ProjectMetadata, new: ProjectMetadata) -> ProjectMetadata:
        """Merge new metadata into base, preferring non-empty values from new."""
        for field_name in base.__dataclass_fields__:
            base_val = getattr(base, field_name)
            new_val = getattr(new, field_name)

            # For lists/sets, merge
            if isinstance(base_val, list) and isinstance(new_val, list):
                merged = list(base_val)
                for item in new_val:
                    if item not in merged:
                        merged.append(item)
                setattr(base, field_name, merged)
            # For dicts, merge
            elif isinstance(base_val, dict) and isinstance(new_val, dict):
                merged = dict(base_val)
                merged.update(new_val)
                setattr(base, field_name, merged)
            # For scalars, prefer new if non-empty
            elif new_val and (not base_val or base_val in ("", "unknown", "none detected")):
                setattr(base, field_name, new_val)

        return base

    def _parse_pyproject_toml(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse pyproject.toml (PEP 517/518/621)."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse pyproject.toml: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["pyproject_toml"] = data

        # [project] section (PEP 621)
        project = data.get("project", {})
        if project:
            meta.name = project.get("name", "")
            meta.version = project.get("version", "")
            meta.description = project.get("description", "")
            meta.license = project.get("license", {}).get("text", "") if isinstance(project.get("license"), dict) else project.get("license", "")
            meta.authors = [a.get("name", "") for a in project.get("authors", []) if isinstance(a, dict)]
            meta.maintainers = [m.get("name", "") for m in project.get("maintainers", []) if isinstance(m, dict)]
            meta.homepage = project.get("urls", {}).get("Homepage", "")
            meta.repository = project.get("urls", {}).get("Repository", "")
            meta.documentation = project.get("urls", {}).get("Documentation", "")
            meta.python_requires = project.get("requires-python", "")
            meta.classifiers = project.get("classifiers", [])
            meta.keywords = project.get("keywords", [])
            meta.entry_points = list(project.get("scripts", {}).keys())
            meta.entry_points.extend(project.get("gui-scripts", {}).keys())

            # Detect framework from dependencies
            deps = project.get("dependencies", [])
            if "fastapi" in " ".join(deps).lower():
                meta.framework = "FastAPI"
            elif "django" in " ".join(deps).lower():
                meta.framework = "Django"
            elif "flask" in " ".join(deps).lower():
                meta.framework = "Flask"

        # [build-system] section (PEP 517/518)
        build = data.get("build-system", {})
        if build:
            meta.build_system = build.get("build-backend", "")
            requires = build.get("requires", [])
            if any("poetry" in r for r in requires):
                meta.package_manager = "poetry"
            elif any("flit" in r for r in requires):
                meta.package_manager = "flit"
            elif any("setuptools" in r for r in requires):
                meta.package_manager = meta.package_manager or "setuptools"

        # [tool.poetry] section
        poetry = data.get("tool", {}).get("poetry", {})
        if poetry:
            meta.package_manager = "poetry"
            if not meta.name:
                meta.name = poetry.get("name", "")
            if not meta.version:
                meta.version = poetry.get("version", "")
            if not meta.description:
                meta.description = poetry.get("description", "")
            meta.authors = poetry.get("authors", [])
            meta.license = poetry.get("license", "")
            meta.homepage = poetry.get("homepage", "")
            meta.repository = poetry.get("repository", "")
            meta.documentation = poetry.get("documentation", "")
            meta.keywords = poetry.get("keywords", [])

        # [tool.setuptools] / [tool.setuptools.*]
        setuptools = data.get("tool", {}).get("setuptools", {})
        if setuptools:
            meta.package_manager = meta.package_manager or "setuptools"
            if not meta.entry_points:
                meta.entry_points = list(setuptools.get("scripts", {}).keys())

        # [tool.pdm]
        if "pdm" in data.get("tool", {}):
            meta.package_manager = "pdm"

        # [tool.hatch]
        if "hatch" in data.get("tool", {}):
            meta.package_manager = meta.package_manager or "hatch"

        # [project.optional-dependencies]
        if "optional-dependencies" in project:
            meta.modules.extend(list(project["optional-dependencies"].keys()))

        meta.primary_language = "Python"
        return meta

    def _parse_package_json(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse package.json."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse package.json: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["package_json"] = data

        meta.name = data.get("name", "")
        meta.version = data.get("version", "")
        meta.description = data.get("description", "")
        meta.license = data.get("license", "")
        meta.homepage = data.get("homepage", "")
        meta.repository = data.get("repository", {}).get("url", "") if isinstance(data.get("repository"), dict) else data.get("repository", "")
        meta.documentation = data.get("documentation", "")

        # Authors
        authors = data.get("author", {})
        if isinstance(authors, str):
            meta.authors = [authors]
        elif isinstance(authors, dict):
            meta.authors = [f"{authors.get('name', '')} <{authors.get('email', '')}>".strip()]
        meta.maintainers = [m.get("name", "") for m in data.get("maintainers", []) if isinstance(m, dict)]

        # Scripts and entry points
        meta.scripts = data.get("scripts", {})
        meta.entry_points = list(meta.scripts.keys())

        # Engines
        meta.engines = data.get("engines", {})
        if "node" in meta.engines:
            meta.runtime_version = f"Node {meta.engines['node']}"

        # Dependencies for framework detection
        all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        frameworks = []
        if "next" in all_deps: frameworks.append("Next.js")
        if "react" in all_deps: frameworks.append("React")
        if "vue" in all_deps: frameworks.append("Vue")
        if "svelte" in all_deps: frameworks.append("Svelte")
        if "express" in all_deps: frameworks.append("Express")
        if "fastapi" in all_deps: frameworks.append("FastAPI")
        if "django" in all_deps: frameworks.append("Django")
        if "flask" in all_deps: frameworks.append("Flask")
        if "angular" in " ".join(all_deps.keys()):
            frameworks.append("Angular")
        meta.framework = ", ".join(frameworks) if frameworks else "none detected"

        # Detect package manager from lockfile presence
        if (self.workspace / "pnpm-lock.yaml").exists():
            meta.package_manager = "pnpm"
        elif (self.workspace / "yarn.lock").exists():
            meta.package_manager = "yarn"
        else:
            meta.package_manager = "npm"

        # Build system
        build_tools = ["webpack", "vite", "rollup", "esbuild", "parcel", "snowpack"]
        for tool in build_tools:
            if tool in all_deps or tool in data.get("scripts", {}):
                meta.build_system = tool
                break

        meta.browsers_list = data.get("browserslist", [])
        meta.primary_language = "JavaScript" if "typescript" not in all_deps else "TypeScript"

        return meta

    def _parse_cargo_toml(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse Cargo.toml."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse Cargo.toml: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["cargo_toml"] = data

        package = data.get("package", {})
        meta.name = package.get("name", "")
        meta.version = package.get("version", "")
        meta.description = package.get("description", "")
        meta.license = package.get("license", "")
        meta.homepage = package.get("homepage", "")
        meta.repository = package.get("repository", "")
        meta.documentation = package.get("documentation", "")
        meta.authors = package.get("authors", [])
        meta.keywords = package.get("keywords", [])
        meta.cargo_features = data.get("features", {})
        meta.rust_edition = package.get("edition", "2018")
        meta.package_manager = "cargo"
        meta.build_system = "cargo"
        meta.primary_language = "Rust"

        # Entry points from [[bin]]
        for bin_config in data.get("bin", []):
            if isinstance(bin_config, dict):
                path_attr = bin_config.get("path", "")
                if path_attr:
                    meta.entry_points.append(path_attr)

        return meta

    def _parse_go_mod(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse go.mod."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read go.mod: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["go_mod"] = content

        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("module "):
                meta.module_path = line[7:].strip()
                meta.name = meta.module_path.split("/")[-1]
            elif line.startswith("go "):
                meta.go_version = line[3:].strip()
                meta.runtime_version = f"Go {meta.go_version}"

        meta.package_manager = "go modules"
        meta.build_system = "go"
        meta.primary_language = "Go"
        return meta

    def _parse_pom_xml(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse Maven pom.xml."""
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        except Exception as e:
            logger.warning(f"Failed to parse pom.xml: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["pom_xml"] = ET.tostring(root, encoding="unicode")

        def get_text(xpath: str) -> str:
            elem = root.find(xpath, ns)
            return elem.text.strip() if elem is not None and elem.text else ""

        meta.group_id = get_text("m:groupId") or get_text("m:parent/m:groupId")
        meta.artifact_id = get_text("m:artifactId")
        meta.name = meta.artifact_id
        meta.version = get_text("m:version") or get_text("m:parent/m:version")
        meta.packaging = get_text("m:packaging") or "jar"
        meta.description = get_text("m:description")
        meta.homepage = get_text("m:url")
        meta.repository = get_text("m:scm/m:url")

        # Parent POM
        parent = root.find("m:parent", ns)
        if parent is not None:
            meta.parent_pom = {
                "group_id": parent.findtext("m:groupId", default="", namespaces=ns),
                "artifact_id": parent.findtext("m:artifactId", default="", namespaces=ns),
                "version": parent.findtext("m:version", default="", namespaces=ns),
            }

        # Properties for versions
        props = root.find("m:properties", ns)
        if props is not None:
            for prop in props:
                tag = prop.tag.split("}")[-1]
                meta.raw_config[f"property_{tag}"] = prop.text

        # Java version
        java_version = get_text("m:properties/m:maven.compiler.source") or get_text("m:properties/m:java.version")
        if java_version:
            meta.runtime_version = f"Java {java_version}"

        # Detect framework from dependencies
        deps = root.findall("m:dependencies/m:dependency", ns)
        dep_names = [d.findtext("m:artifactId", default="", namespaces=ns) for d in deps]
        frameworks = []
        if "spring-boot-starter" in " ".join(dep_names):
            frameworks.append("Spring Boot")
        if "spring-web" in dep_names or "spring-webmvc" in dep_names:
            frameworks.append("Spring MVC")
        if "quarkus-core" in dep_names:
            frameworks.append("Quarkus")
        if "micronaut-core" in dep_names:
            frameworks.append("Micronaut")
        meta.framework = ", ".join(frameworks) if frameworks else "none detected"

        meta.package_manager = "maven"
        meta.build_system = "maven"
        meta.primary_language = "Java"
        return meta

    def _parse_gradle(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse build.gradle (Groovy DSL)."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read build.gradle: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["build_gradle"] = content

        # Simple regex-based extraction for Gradle Groovy DSL
        patterns = {
            "group": r"group\s*[=:]\s*[\"']([^\"']+)[\"']",
            "version": r"version\s*[=:]\s*[\"']([^\"']+)[\"']",
            "description": r"description\s*[=:]\s*[\"']([^\"']+)[\"']",
            "source_compatibility": r"sourceCompatibility\s*[=:]\s*[\"']([^\"']+)[\"']",
            "target_compatibility": r"targetCompatibility\s*[=:]\s*[\"']([^\"']+)[\"']",
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                if key == "group":
                    meta.group_id = match.group(1)
                elif key == "version":
                    meta.version = match.group(1)
                elif key == "description":
                    meta.description = match.group(1)
                elif key in ("source_compatibility", "target_compatibility"):
                    meta.runtime_version = f"Java {match.group(1)}"

        # Detect plugins
        if "org.springframework.boot" in content:
            meta.framework = "Spring Boot"
        elif "io.spring.dependency-management" in content:
            meta.framework = meta.framework + ", Spring" if meta.framework else "Spring"
        if "com.android.application" in content or "com.android.library" in content:
            meta.framework = meta.framework + ", Android" if meta.framework else "Android"

        meta.package_manager = "gradle"
        meta.build_system = "gradle"
        meta.primary_language = "Java"  # Could be Kotlin/Groovy too

        # Check for kotlin
        if "kotlin(" in content or "id \"org.jetbrains.kotlin" in content:
            meta.primary_language = "Kotlin"

        return meta

    def _parse_gradle_kts(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse build.gradle.kts (Kotlin DSL)."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read build.gradle.kts: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["build_gradle_kts"] = content

        # Kotlin DSL patterns
        patterns = {
            "group": r'group\s*=\s*"([^"]+)"',
            "version": r'version\s*=\s*"([^"]+)"',
            "description": r'description\s*=\s*"([^"]+)"',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                if key == "group":
                    meta.group_id = match.group(1)
                elif key == "version":
                    meta.version = match.group(1)
                elif key == "description":
                    meta.description = match.group(1)

        if "org.springframework.boot" in content:
            meta.framework = "Spring Boot"
        if 'kotlin("' in content or 'id("org.jetbrains.kotlin' in content:
            meta.primary_language = "Kotlin"
        else:
            meta.primary_language = "Java"

        meta.package_manager = "gradle"
        meta.build_system = "gradle"
        return meta

    def _parse_setup_py(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse setup.py (legacy Python)."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read setup.py: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["setup_py"] = content

        # Use regex for common patterns (not executing the file)
        patterns = {
            "name": r'name\s*=\s*["\']([^"\']+)["\']',
            "version": r'version\s*=\s*["\']([^"\']+)["\']',
            "description": r'description\s*=\s*["\']([^"\']+)["\']',
            "author": r'author\s*=\s*["\']([^"\']+)["\']',
            "author_email": r'author_email\s*=\s*["\']([^"\']+)["\']',
            "url": r'url\s*=\s*["\']([^"\']+)["\']',
            "license": r'license\s*=\s*["\']([^"\']+)["\']',
            "python_requires": r'python_requires\s*=\s*["\']([^"\']+)["\']',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                if key == "name":
                    meta.name = match.group(1)
                elif key == "version":
                    meta.version = match.group(1)
                elif key == "description":
                    meta.description = match.group(1)
                elif key in ("author", "author_email"):
                    meta.authors.append(match.group(1))
                elif key == "url":
                    meta.homepage = match.group(1)
                elif key == "license":
                    meta.license = match.group(1)
                elif key == "python_requires":
                    meta.python_requires = match.group(1)

        # Find install_requires
        install_requires_match = re.search(r"install_requires\s*=\s*\[(.*?)\]", content, re.DOTALL)
        if install_requires_match:
            deps_str = install_requires_match.group(1)
            deps = re.findall(r'["\']([^"\']+)["\']', deps_str)
            meta.modules = deps

        meta.package_manager = "pip"
        meta.build_system = "setuptools"
        meta.primary_language = "Python"
        return meta

    def _parse_setup_cfg(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse setup.cfg."""
        try:
            import configparser
            config = configparser.ConfigParser()
            config.read(path)
        except Exception as e:
            logger.warning(f"Failed to parse setup.cfg: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["setup_cfg"] = dict(config._sections) if hasattr(config, '_sections') else {}

        if "metadata" in config:
            m = config["metadata"]
            meta.name = m.get("name", "")
            meta.version = m.get("version", "")
            meta.description = m.get("description", "")
            meta.author = m.get("author", "")
            meta.author_email = m.get("author_email", "")
            meta.homepage = m.get("url", "") or m.get("home_page", "")
            meta.license = m.get("license", "") or m.get("license_file", "")
            meta.python_requires = m.get("python_requires", "")
            meta.classifiers = [c.strip() for c in m.get("classifiers", "").split("\n") if c.strip()]

        if "options" in config:
            o = config["options"]
            install_requires = o.get("install_requires", "")
            if install_requires:
                meta.modules = [d.strip() for d in install_requires.split("\n") if d.strip()]

        meta.package_manager = "pip"
        meta.build_system = "setuptools"
        meta.primary_language = "Python"
        return meta

    def _parse_pipfile(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse Pipfile."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse Pipfile: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["pipfile"] = data
        meta.package_manager = "pipenv"
        meta.build_system = "pipenv"
        meta.primary_language = "Python"

        # Extract from [packages] and [dev-packages]
        packages = data.get("packages", {})
        dev_packages = data.get("dev-packages", {})
        meta.modules = list(packages.keys()) + list(dev_packages.keys())

        if "requires" in data:
            meta.python_requires = data["requires"].get("python_version", "")

        return meta

    def _parse_composer_json(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse composer.json (PHP)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to parse composer.json: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["composer_json"] = data
        meta.name = data.get("name", "")
        meta.version = data.get("version", "")
        meta.description = data.get("description", "")
        meta.license = ", ".join(data.get("license", [])) if isinstance(data.get("license"), list) else data.get("license", "")
        meta.authors = [f"{a.get('name', '')} <{a.get('email', '')}>".strip() for a in data.get("authors", [])]
        meta.homepage = data.get("homepage", "")
        meta.documentation = data.get("support", {}).get("docs", "") if isinstance(data.get("support"), dict) else ""
        meta.repository = data.get("support", {}).get("source", "") if isinstance(data.get("support"), dict) else ""
        meta.package_manager = "composer"
        meta.build_system = "composer"
        meta.primary_language = "PHP"

        # Detect framework
        reqs = {**data.get("require", {}), **data.get("require-dev", {})}
        if "laravel/framework" in reqs:
            meta.framework = "Laravel"
        elif "symfony/framework-bundle" in reqs:
            meta.framework = "Symfony"
        elif "codeigniter4/framework" in reqs:
            meta.framework = "CodeIgniter"
        elif "yiisoft/yii2" in reqs:
            meta.framework = "Yii2"

        return meta

    def _parse_mix_exs(self, path: Path) -> Optional[ProjectMetadata]:
        """Parse mix.exs (Elixir)."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read mix.exs: {e}")
            return None

        meta = ProjectMetadata()
        meta.raw_config["mix_exs"] = content
        meta.package_manager = "mix"
        meta.build_system = "mix"
        meta.primary_language = "Elixir"

        # Simple regex extraction
        patterns = {
            "app": r'app:\s*:([a-zA-Z_][a-zA-Z0-9_]*)',
            "version": r'version:\s*"([^"]+)"',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                if key == "app":
                    meta.name = match.group(1)
                elif key == "version":
                    meta.version = match.group(1)

        return meta


# ============================================================================
# Dependency Lockfile Parsers
# ============================================================================

class DependencyParser:
    """Parse dependency lockfiles and manifest files to extract resolved dependencies."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()

    def parse_all(self) -> DependencySet:
        """Parse all available lockfiles and return consolidated dependency set."""
        deps = DependencySet()

        # Try lockfiles first (most accurate - they have resolved versions)
        lockfile_parsers = [
            ("requirements.txt", self._parse_requirements_txt, "manifest"),
            ("pyproject.toml", self._parse_pyproject_deps, "manifest"),
            ("Pipfile.lock", self._parse_pipfile_lock, "lockfile"),
            ("poetry.lock", self._parse_poetry_lock, "lockfile"),
            ("pdm.lock", self._parse_pdm_lock, "lockfile"),
            ("uv.lock", self._parse_uv_lock, "lockfile"),
            ("package-lock.json", self._parse_package_lock_json, "lockfile"),
            ("yarn.lock", self._parse_yarn_lock, "lockfile"),
            ("pnpm-lock.yaml", self._parse_pnpm_lock, "lockfile"),
            ("Cargo.lock", self._parse_cargo_lock, "lockfile"),
            ("go.sum", self._parse_go_sum, "lockfile"),
            ("pom.xml", self._parse_pom_deps, "manifest"),
            ("build.gradle", self._parse_gradle_deps, "manifest"),
            ("composer.lock", self._parse_composer_lock, "lockfile"),
            ("mix.lock", self._parse_mix_lock, "lockfile"),
        ]

        for filename, parser, deptype in lockfile_parsers:
            filepath = self.workspace / filename
            if filepath.exists():
                try:
                    parsed = parser(filepath, deptype)
                    if parsed:
                        deps = self._merge_deps(deps, parsed)
                except Exception as e:
                    logger.warning(f"Failed to parse {filename}: {e}")

        return deps

    def _merge_deps(self, base: DependencySet, new: DependencySet) -> DependencySet:
        """Merge new dependencies into base, deduplicating by name."""
        all_new_deps = new.all()
        for dep in all_new_deps:
            target_list = getattr(base, dep.dependency_type, base.runtime)
            # Check if already exists
            existing = next((d for d in target_list if d.name.lower() == dep.name.lower()), None)
            if existing:
                # Merge: prefer lockfile data (resolved_version), keep manifest version_spec
                if dep.resolved_version and not existing.resolved_version:
                    existing.resolved_version = dep.resolved_version
                if dep.requested_version and not existing.requested_version:
                    existing.requested_version = dep.requested_version
                if dep.license and not existing.license:
                    existing.license = dep.license
                if dep.description and not existing.description:
                    existing.description = dep.description
                if dep.repository and not existing.repository:
                    existing.repository = dep.repository
            else:
                target_list.append(dep)
        return base

    # --- Python Parsers ---

    def _parse_requirements_txt(self, path: Path, deptype: str) -> DependencySet:
        """Parse requirements.txt."""
        deps = DependencySet()
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return deps

        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Handle -r, -c, --index-url, etc.
            if line.startswith("-") and not line.startswith("--"):
                continue

            # Parse package spec
            # Formats: package, package==1.0, package>=1.0, package~=1.0, package[extra]==1.0
            dep = self._parse_python_spec(line, "runtime" if deptype == "manifest" else "runtime")
            if dep:
                dep.is_direct = (deptype == "manifest")
                deps.runtime.append(dep)

        return deps

    def _parse_pyproject_deps(self, path: Path, deptype: str) -> DependencySet:
        """Parse dependencies from pyproject.toml."""
        deps = DependencySet()
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return deps

        project = data.get("project", {})
        # Main dependencies
        for spec in project.get("dependencies", []):
            dep = self._parse_python_spec(spec, "runtime")
            if dep:
                dep.is_direct = True
                deps.runtime.append(dep)

        # Optional dependencies
        for extra_name, specs in project.get("optional-dependencies", {}).items():
            for spec in specs:
                dep = self._parse_python_spec(spec, "optional")
                if dep:
                    dep.is_direct = True
                    deps.optional.append(dep)

        # Development dependencies from [tool.*] sections
        for tool_name in ("poetry", "pdm", "hatch", "flit"):
            tool = data.get("tool", {}).get(tool_name, {})
            if tool:
                for group_name in ("dev-dependencies", "development-dependencies", "dev"):
                    group = tool.get(group_name, {})
                    if isinstance(group, dict):
                        for name, spec in group.items():
                            if isinstance(spec, str):
                                dep = self._parse_python_spec(f"{name}{spec}", "development")
                            else:
                                dep = self._parse_python_spec(name, "development")
                            if dep:
                                dep.is_direct = True
                                deps.development.append(dep)

        return deps

    def _parse_pipfile_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse Pipfile.lock."""
        deps = DependencySet()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return deps

        for section_name, target_type in [("default", "runtime"), ("develop", "development")]:
            packages = data.get(section_name, {})
            for name, info in packages.items():
                if not isinstance(info, dict):
                    continue
                dep = DependencyInfo(
                    name=name.lower(),
                    requested_version=info.get("version", "").lstrip("=="),
                    resolved_version=info.get("version", "").lstrip("=="),
                    dependency_type=target_type,
                    source="pypi",
                    is_direct=True,
                )
                # Check for hashes to confirm resolved
                if "hashes" in info:
                    dep.resolved_version = info["version"].lstrip("==")
                getattr(deps, target_type).append(dep)

        return deps

    def _parse_poetry_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse poetry.lock."""
        deps = DependencySet()
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return deps

        for package in data.get("package", []):
            dep_type = "development" if package.get("category") == "dev" else "runtime"
            dep = DependencyInfo(
                name=package.get("name", "").lower(),
                version_spec=package.get("version", ""),  # This is the resolved version in poetry.lock
                resolved_version=package.get("version", ""),
                requested_version="",  # We'd need pyproject.toml for requested
                dependency_type=dep_type,
                source="pypi",
                description=package.get("description", ""),
                is_direct=package.get("optional", False) is False,  # Not quite right, but close
            )
            getattr(deps, dep_type).append(dep)

        return deps

    def _parse_pdm_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse pdm.lock."""
        deps = DependencySet()
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return deps

        for package in data.get("package", []):
            dep_type = "development" if package.get("dev", False) else "runtime"
            dep = DependencyInfo(
                name=package.get("name", "").lower(),
                resolved_version=package.get("version", ""),
                requested_version="",
                dependency_type=dep_type,
                source="pypi",
                is_direct=not package.get("dev", False),  # Approximation
            )
            getattr(deps, dep_type).append(dep)

        return deps

    def _parse_uv_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse uv.lock (PEP 751)."""
        deps = DependencySet()
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return deps

        # uv.lock format: [[package]] with name, version, dependencies
        for package in data.get("package", []):
            # Check if it's a direct dependency (has marker like "direct = true")
            is_direct = package.get("direct", False)
            dep_type = "development" if package.get("dev", False) else "runtime"
            dep = DependencyInfo(
                name=package.get("name", "").lower(),
                resolved_version=package.get("version", ""),
                requested_version="",
                dependency_type=dep_type,
                source="pypi",
                is_direct=is_direct,
            )
            getattr(deps, dep_type).append(dep)

        return deps

    def _parse_python_spec(self, spec: str, dep_type: str) -> Optional[DependencyInfo]:
        """Parse a Python dependency specification (from requirements.txt, pyproject.toml, etc.)."""
        spec = spec.strip()
        if not spec or spec.startswith("#"):
            return None

        # Handle extras: package[extra1,extra2]>=1.0
        extras = ""
        extras_match = re.search(r"\[([^\]]+)\]", spec)
        if extras_match:
            extras = extras_match.group(1)
            spec = spec.replace(f"[{extras}]", "")

        # Parse version specifiers
        # Patterns: ==, >=, <=, >, <, ~=, !=, ===
        version_pattern = r"^([A-Za-z0-9_.-]+)\s*((?:===|==|>=|<=|>|<|~=|!=)\s*[A-Za-z0-9_.\-+*!]+)?"
        match = re.match(version_pattern, spec)
        if not match:
            return None

        name = match.group(1).lower()
        version_spec = match.group(2).strip() if match.group(2) else ""

        return DependencyInfo(
            name=name,
            version_spec=version_spec,
            requested_version=version_spec.replace("==", "").replace(">=", "").replace("<=", "").strip(),
            dependency_type=dep_type,
            source="pypi",
            is_direct=True,
        )

    # --- JavaScript/Node Parsers ---

    def _parse_package_lock_json(self, path: Path, deptype: str) -> DependencySet:
        """Parse package-lock.json (npm v7+)."""
        deps = DependencySet()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return deps

        # npm v7+ format: packages object
        packages = data.get("packages", {})
        if not packages and "dependencies" in data:
            # npm v6 format
            packages = {"/": data}

        for pkg_path, pkg_info in packages.items():
            if pkg_path == "":
                pkg_path = "/"
            if pkg_path == "/":
                continue  # Root package

            name = pkg_path.split("/")[-1] if pkg_path != "/" else ""
            if name.startswith("node_modules/"):
                name = name[len("node_modules/"):]

            # Determine if dev dependency
            is_dev = pkg_info.get("dev", False) or pkg_info.get("devDependencies", False)
            dep_type = "development" if is_dev else "runtime"

            dep = DependencyInfo(
                name=name,
                resolved_version=pkg_info.get("version", ""),
                requested_version="",  # Need package.json for this
                dependency_type=dep_type,
                source="npm",
                description=pkg_info.get("description", ""),
                license=pkg_info.get("license", ""),
                repository=pkg_info.get("repository", {}).get("url", "") if isinstance(pkg_info.get("repository"), dict) else pkg_info.get("repository", ""),
                is_direct=not pkg_info.get("dev", False) and not pkg_info.get("optional", False),  # Approximation
            )
            getattr(deps, dep_type).append(dep)

        # Also check for peerDependencies at root
        root_deps = data.get("dependencies", {})
        for name, version in root_deps.items():
            dep = DependencyInfo(
                name=name,
                resolved_version=version,
                requested_version="",
                dependency_type="peer",
                source="npm",
                is_direct=True,
            )
            deps.peer.append(dep)

        return deps

    def _parse_yarn_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse yarn.lock."""
        deps = DependencySet()
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return deps

        # Yarn v1 lockfile format parsing
        # Each entry: "package@version:\n  version \"x.y.z\"\n  dependencies:\n    dep \"version\""
        # This is simplified - a full parser would be more complex
        current_pkg = None
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if not line.startswith("  ") and ":" in line and not line.startswith("  "):
                # New package entry: "package@version:"
                current_pkg = line[:-1]  # Remove trailing colon
                continue

            if current_pkg and line.startswith("version "):
                version = line[8:].strip().strip('"')
                # Parse package name from "name@version" or "name@namespace/name@version"
                # Format: "package-name@^1.0.0" or "@scope/name@^1.0.0"
                match = re.match(r'^(.+)@(.+)$', current_pkg)
                if match:
                    name = match.group(1)
                    dep = DependencyInfo(
                        name=name,
                        resolved_version=version,
                        requested_version="",  # Need package.json
                        dependency_type="runtime",  # Can't easily tell from yarn.lock v1
                        source="npm",
                        is_direct=False,  # yarn.lock has all transitive
                    )
                    deps.runtime.append(dep)
                current_pkg = None

        return deps

    def _parse_pnpm_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse pnpm-lock.yaml."""
        deps = DependencySet()
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            return deps

        packages = data.get("packages", {})
        for name, info in packages.items():
            if not isinstance(info, dict):
                continue
            dep_type = "development" if info.get("dev", False) else "runtime"
            if info.get("optional", False):
                dep_type = "optional"
            dep = DependencyInfo(
                name=name.split("/")[-1] if "/" in name else name,
                resolved_version=info.get("version", ""),
                requested_version="",
                dependency_type=dep_type,
                source="npm",
                is_direct=not info.get("dev", False) and not info.get("optional", False),
            )
            getattr(deps, dep_type).append(dep)

        return deps

    # --- Rust Parser ---

    def _parse_cargo_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse Cargo.lock."""
        deps = DependencySet()
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return deps

        for package in data.get("package", []):
            dep = DependencyInfo(
                name=package.get("name", "").lower(),
                resolved_version=package.get("version", ""),
                requested_version="",  # Need Cargo.toml
                dependency_type="runtime",  # Cargo doesn't distinguish dev in lockfile
                source="crates.io",
                description=package.get("description", ""),
                repository=package.get("repository", ""),
                homepage=package.get("homepage", ""),
                is_direct=False,  # Cargo.lock includes transitive
            )
            deps.runtime.append(dep)

        return deps

    # --- Go Parser ---

    def _parse_go_sum(self, path: Path, deptype: str) -> DependencySet:
        """Parse go.sum."""
        deps = DependencySet()
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return deps

        seen = set()
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                version = parts[1]
                key = (name, version)
                if key not in seen:
                    seen.add(key)
                    dep = DependencyInfo(
                        name=name,
                        resolved_version=version,
                        requested_version="",  # Need go.mod
                        dependency_type="runtime",
                        source="go proxy",
                        is_direct=False,
                    )
                    deps.runtime.append(dep)

        return deps

    # --- Java/Maven Parsers ---

    def _parse_pom_deps(self, path: Path, deptype: str) -> DependencySet:
        """Parse dependencies from pom.xml."""
        deps = DependencySet()
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        except Exception:
            return deps

        for dep_elem in root.findall("m:dependencies/m:dependency", ns):
            group_id = dep_elem.findtext("m:groupId", default="", namespaces=ns)
            artifact_id = dep_elem.findtext("m:artifactId", default="", namespaces=ns)
            version = dep_elem.findtext("m:version", default="", namespaces=ns)
            scope = dep_elem.findtext("m:scope", default="compile", namespaces=ns)
            optional = dep_elem.findtext("m:optional", default="false", namespaces=ns) == "true"

            name = f"{group_id}:{artifact_id}"
            dep_type = "runtime"
            if scope == "test":
                dep_type = "test"
            elif scope == "provided":
                dep_type = "build"
            elif optional:
                dep_type = "optional"

            dep = DependencyInfo(
                name=name,
                requested_version=version,
                resolved_version=version,
                dependency_type=dep_type,
                source="maven",
                is_direct=True,
            )
            getattr(deps, dep_type).append(dep)

        return deps

    def _parse_gradle_deps(self, path: Path, deptype: str) -> DependencySet:
        """Parse dependencies from build.gradle (simplified regex-based)."""
        deps = DependencySet()
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return deps

        # Patterns for Gradle dependency declarations
        patterns = [
            r"(implementation|api|compile)\s+[\"']([^\"']+):([^\"']+):([^\"']+)[\"']",
            r"(testImplementation|testCompile)\s+[\"']([^\"']+):([^\"']+):([^\"']+)[\"']",
            r"(compileOnly|provided)\s+[\"']([^\"']+):([^\"']+):([^\"']+)[\"']",
            r"(runtimeOnly)\s+[\"']([^\"']+):([^\"']+):([^\"']+)[\"']",
        ]

        scope_map = {
            "implementation": "runtime",
            "api": "runtime",
            "compile": "runtime",
            "testImplementation": "test",
            "testCompile": "test",
            "compileOnly": "build",
            "provided": "build",
            "runtimeOnly": "runtime",
        }

        for pattern in patterns:
            for match in re.finditer(pattern, content):
                scope = match.group(1)
                group_id = match.group(2)
                artifact_id = match.group(3)
                version = match.group(4)
                dep_type = scope_map.get(scope, "runtime")

                name = f"{group_id}:{artifact_id}"
                dep = DependencyInfo(
                    name=name,
                    requested_version=version,
                    resolved_version=version,
                    dependency_type=dep_type,
                    source="maven",
                    is_direct=True,
                )
                getattr(deps, dep_type).append(dep)

        return deps

    # --- PHP Parser ---

    def _parse_composer_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse composer.lock."""
        deps = DependencySet()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return deps

        packages = data.get("packages", []) + data.get("packages-dev", [])
        is_dev_section = len(data.get("packages", [])) > 0

        for pkg in packages:
            dep_type = "development" if pkg.get("dev", False) or (not is_dev_section) else "runtime"
            dep = DependencyInfo(
                name=pkg.get("name", ""),
                resolved_version=pkg.get("version", ""),
                requested_version=pkg.get("version", ""),  # composer.lock has exact versions
                dependency_type=dep_type,
                source="packagist",
                description=pkg.get("description", ""),
                license=", ".join(pkg.get("license", [])) if isinstance(pkg.get("license"), list) else pkg.get("license", ""),
                homepage=pkg.get("homepage", ""),
                repository=pkg.get("source", {}).get("url", "") if isinstance(pkg.get("source"), dict) else "",
                is_direct=True,  # composer.lock only has direct deps
            )
            getattr(deps, dep_type).append(dep)

        return deps

    # --- Elixir Parser ---

    def _parse_mix_lock(self, path: Path, deptype: str) -> DependencySet:
        """Parse mix.lock."""
        deps = DependencySet()
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            return deps

        for name, info in data.items():
            if not isinstance(info, dict):
                continue
            dep = DependencyInfo(
                name=name,
                resolved_version=info.get("version", ""),
                requested_version="",
                dependency_type="runtime",
                source="hex",
                is_direct=True,
            )
            deps.runtime.append(dep)

        return deps


# ============================================================================
# Integration with World Model
# ============================================================================

@dataclass
class ProjectDependencies:
    """Container for project metadata and dependencies."""
    metadata: ProjectMetadata
    dependencies: DependencySet

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "name": self.metadata.name,
                "version": self.metadata.version,
                "description": self.metadata.description,
                "license": self.metadata.license,
                "authors": self.metadata.authors,
                "homepage": self.metadata.homepage,
                "repository": self.metadata.repository,
                "documentation": self.metadata.documentation,
                "primary_language": self.metadata.primary_language,
                "build_system": self.metadata.build_system,
                "package_manager": self.metadata.package_manager,
                "framework": self.metadata.framework,
                "runtime_version": self.metadata.runtime_version,
                "entry_points": self.metadata.entry_points,
                "scripts": self.metadata.scripts,
                "keywords": self.metadata.keywords,
                "classifiers": self.metadata.classifiers,
            },
            "dependencies": self.dependencies.to_dict(),
            "dependency_stats": self.dependencies.get_stats(),
        }

    def get_context_for_task(self, task_type: str) -> Dict[str, Any]:
        """Get relevant dependency context for a task type."""
        stats = self.dependencies.get_stats()

        context = {
            "project": {
                "name": self.metadata.name,
                "language": self.metadata.primary_language,
                "build_system": self.metadata.build_system,
                "package_manager": self.metadata.package_manager,
                "framework": self.metadata.framework,
            },
            "dependency_summary": stats,
        }

        # Add relevant dependencies based on task type
        relevant_deps = []
        if task_type in ("build", "install", "deploy"):
            relevant_deps.extend(self.dependencies.runtime)
            relevant_deps.extend(self.dependencies.build)
        elif task_type == "test":
            relevant_deps.extend(self.dependencies.test)
            relevant_deps.extend(self.dependencies.dev)
        elif task_type in ("lint", "analyze"):
            relevant_deps.extend(self.dependencies.development)

        if relevant_deps:
            context["key_dependencies"] = [
                {"name": d.name, "version": d.resolved_version or d.requested_version, "type": d.dependency_type}
                for d in relevant_deps[:20]  # Limit
            ]

        return context


def detect_project_metadata(workspace: str = ".") -> ProjectMetadata:
    """Convenience function to detect project metadata."""
    parser = ProjectMetadataParser(workspace)
    return parser.parse_all()


def detect_dependencies(workspace: str = ".") -> DependencySet:
    """Convenience function to detect dependencies."""
    parser = DependencyParser(workspace)
    return parser.parse_all()


def detect_full_project(workspace: str = ".") -> ProjectDependencies:
    """Convenience function to detect full project info (metadata + dependencies)."""
    metadata = detect_project_metadata(workspace)
    dependencies = detect_dependencies(workspace)
    return ProjectDependencies(metadata=metadata, dependencies=dependencies)


# ============================================================================
# Enhancement for WorldModel class
# ============================================================================

def enhance_world_model_with_project_data(world_model_instance, workspace: str = "."):
    """Add project metadata and dependency detection to a WorldModel instance.

    This can be called after creating a WorldModel to augment it with
    detailed project and dependency information.
    """
    project_data = detect_full_project(workspace)

    # Add to the instance
    world_model_instance.project_metadata = project_data.metadata
    world_model_instance.project_dependencies = project_data.dependencies

    # Also add a method to get project context
    def get_project_context(self, task_type: str = "unknown") -> Dict[str, Any]:
        return self.project_dependencies.get_context_for_task(task_type)

    import types
    world_model_instance.get_project_context = types.MethodType(get_project_context, world_model_instance)

    return world_model_instance