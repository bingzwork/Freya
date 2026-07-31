"""External Knowledge Import for Software Engineering Knowledge.

Imports knowledge from:
- Official documentation (package docs, language specs)
- Internet research (StackOverflow, blogs, tutorials)
- Standards bodies (RFCs, ISO, W3C)
- Vendor documentation (AWS, GCP, Azure)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.software_engineering_knowledge.models import (
    EngineeringDomain,
    EngineeringKnowledgeItem,
    EngineeringKnowledgeType,
    ExtractionResult,
    KnowledgeSource,
    ValidationStatus,
)
from app.software_engineering_knowledge.categories import get_category_registry


@dataclass
class ExternalSource:
    """Configuration for an external knowledge source."""
    name: str
    base_url: str
    source_type: KnowledgeSource
    parser: str  # "html", "markdown", "json", "rst"
    selectors: Dict[str, str] = field(default_factory=dict)  # CSS selectors for content
    rate_limit: float = 1.0  # requests per second
    requires_auth: bool = False
    headers: Dict[str, str] = field(default_factory=dict)


# Predefined external sources
EXTERNAL_SOURCES = {
    "python_docs": ExternalSource(
        name="Python Official Documentation",
        base_url="https://docs.python.org/3/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "div.document",
            "title": "h1",
            "section": "div.section",
        },
        rate_limit=0.5,
    ),
    "mdn": ExternalSource(
        name="MDN Web Docs",
        base_url="https://developer.mozilla.org/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "article.main-page-content",
            "title": "h1",
            "section": "section",
        },
        rate_limit=0.5,
    ),
    "rust_docs": ExternalSource(
        name="Rust Documentation",
        base_url="https://doc.rust-lang.org/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "main.content",
            "title": "h1",
            "section": "section",
        },
        rate_limit=0.5,
    ),
    "go_docs": ExternalSource(
        name="Go Documentation",
        base_url="https://go.dev/doc/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "main",
            "title": "h1",
        },
        rate_limit=0.5,
    ),
    "aws_docs": ExternalSource(
        name="AWS Documentation",
        base_url="https://docs.aws.amazon.com/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "div#main-content",
            "title": "h1",
        },
        rate_limit=0.3,
    ),
    "kubernetes_docs": ExternalSource(
        name="Kubernetes Documentation",
        base_url="https://kubernetes.io/docs/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "main.content",
            "title": "h1",
        },
        rate_limit=0.5,
    ),
    "terraform_docs": ExternalSource(
        name="Terraform Documentation",
        base_url="https://developer.hashicorp.com/terraform/docs",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "main",
            "title": "h1",
        },
        rate_limit=0.5,
    ),
    "rfc_editor": ExternalSource(
        name="RFC Editor",
        base_url="https://www.rfc-editor.org/",
        source_type=KnowledgeSource.EXTERNAL_DOCS,
        parser="html",
        selectors={
            "content": "div#content",
            "title": "h1",
        },
        rate_limit=0.3,
    ),
}


class ExternalKnowledgeImporter:
    """Import engineering knowledge from external sources."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/external_knowledge_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.registry = get_category_registry()

    def import_from_source(self, source_name: str, query: str, max_results: int = 10) -> ExtractionResult:
        """Import knowledge from a predefined external source."""
        source = EXTERNAL_SOURCES.get(source_name)
        if not source:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Unknown source: {source_name}"],
                source=source_name,
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )

        # This would normally fetch from the web
        # For now, return placeholder showing structure
        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Web fetching not implemented. Source {source_name} configured but requires HTTP client."],
            source=source_name,
            source_type=source.source_type,
            metadata={"source_config": source.__dict__},
        )

    def import_from_url(self, url: str) -> ExtractionResult:
        """Import knowledge from a specific URL."""
        # Parse URL to determine source type
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Determine source category
        if any(d in domain for d in ["stackoverflow.com", "stackexchange.com"]):
            source_type = KnowledgeSource.INTERNET_RESEARCH
            category = "stackoverflow"
        elif any(d in domain for d in ["github.com", "gitlab.com", "bitbucket.org"]):
            source_type = KnowledgeSource.EXTERNAL_DOCS
            category = "repository"
        elif "docs." in domain or "documentation" in domain:
            source_type = KnowledgeSource.EXTERNAL_DOCS
            category = "documentation"
        elif any(d in domain for d in ["medium.com", "dev.to", "blog", "newsletter"]):
            source_type = KnowledgeSource.INTERNET_RESEARCH
            category = "blog"
        else:
            source_type = KnowledgeSource.EXTERNAL_DOCS
            category = "web"

        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Direct URL import not implemented for {url}"],
            source=url,
            source_type=source_type,
            metadata={"category": category},
        )

    def import_package_docs(self, package_name: str, language: str = "python") -> ExtractionResult:
        """Import documentation for a specific package."""
        if language == "python":
            # Would use pydoc, inspect, or fetch from PyPI/ReadTheDocs
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Python package doc import not implemented for {package_name}"],
                source=f"pypi:{package_name}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )
        elif language in ("javascript", "typescript"):
            # Would fetch from npmjs.com or GitHub
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"NPM package doc import not implemented for {package_name}"],
                source=f"npm:{package_name}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )
        elif language == "rust":
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Crate doc import not implemented for {package_name}"],
                source=f"crates:{package_name}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )
        elif language == "go":
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Go package doc import not implemented for {package_name}"],
                source=f"pkg.go.dev:{package_name}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )

        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Unsupported language: {language}"],
            source=f"{language}:{package_name}",
            source_type=KnowledgeSource.EXTERNAL_DOCS,
        )

    def import_from_standards_body(self, body: str, identifier: str) -> ExtractionResult:
        """Import from standards bodies (RFC, ISO, W3C, ECMA)."""
        standards_sources = {
            "rfc": f"https://www.rfc-editor.org/rfc/rfc{identifier}.txt",
            "iso": f"https://www.iso.org/standard/{identifier}.html",
            "w3c": f"https://www.w3.org/TR/{identifier}/",
            "ecma": f"https://ecma-international.org/publications-and-standards/standards/ecma-{identifier}/",
        }

        url = standards_sources.get(body.lower())
        if not url:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Unknown standards body: {body}"],
                source=f"{body}:{identifier}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )

        return self.import_from_url(url)

    def create_knowledge_from_content(
        self,
        title: str,
        content: str,
        url: str,
        domain: EngineeringDomain,
        knowledge_type: EngineeringKnowledgeType = EngineeringKnowledgeType.REFERENCE,
        tags: Optional[List[str]] = None,
        language: Optional[str] = None,
    ) -> EngineeringKnowledgeItem:
        """Create a knowledge item from fetched content."""
        parsed = urlparse(url)
        source_domain = parsed.netloc

        return EngineeringKnowledgeItem(
            title=title,
            summary=content[:300],
            content=content,
            domain=domain,
            sub_category="external_docs",
            knowledge_type=knowledge_type,
            source=KnowledgeSource.EXTERNAL_DOCS,
            source_uri=url,
            source_metadata={
                "source_domain": source_domain,
                "fetch_timestamp": "",
            },
            tags=tags or ["external", "documentation"],
            language=language,
            confidence=0.75,
            validation_status=ValidationStatus.PENDING,
        )


class InternetResearchImporter:
    """Import knowledge from internet research (search results, articles, etc.)."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/internet_research_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.registry = get_category_registry()

    def search_and_import(self, query: str, max_results: int = 5) -> ExtractionResult:
        """Search the web and import top results as knowledge."""
        # Would integrate with search API (Google, Bing, DuckDuckGo, etc.)
        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Internet search not implemented for query: {query}"],
            source=f"search:{query}",
            source_type=KnowledgeSource.INTERNET_RESEARCH,
        )

    def import_from_stackoverflow(self, question_id: str) -> ExtractionResult:
        """Import a StackOverflow Q&A as engineering knowledge."""
        url = f"https://stackoverflow.com/questions/{question_id}"
        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"StackOverflow import not implemented for {question_id}"],
            source=url,
            source_type=KnowledgeSource.INTERNET_RESEARCH,
        )

    def import_from_github_repo(self, repo_url: str) -> ExtractionResult:
        """Import knowledge from a GitHub repository (README, docs, wiki)."""
        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"GitHub repo import not implemented for {repo_url}"],
            source=repo_url,
            source_type=KnowledgeSource.EXTERNAL_DOCS,
        )


class PackageDocumentationImporter:
    """Import documentation from installed packages/local documentation."""

    def __init__(self):
        self.registry = get_category_registry()

    def import_python_package_docs(self, package_name: str) -> ExtractionResult:
        """Import documentation from an installed Python package."""
        import importlib
        import inspect

        items = []
        errors = []

        try:
            module = importlib.import_module(package_name)
        except ImportError as e:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Cannot import package {package_name}: {e}"],
                source=f"python:{package_name}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )

        # Extract module docstring
        if module.__doc__:
            item = EngineeringKnowledgeItem(
                title=f"{package_name} Package Documentation",
                summary=module.__doc__[:200].strip(),
                content=module.__doc__.strip(),
                domain=EngineeringDomain.LIBRARIES,
                sub_category="package_docs",
                knowledge_type=EngineeringKnowledgeType.EXPLANATION,
                source=KnowledgeSource.EXTERNAL_DOCS,
                source_uri=f"python:{package_name}",
                source_metadata={"module": package_name, "type": "module_docstring"},
                tags=["python", "package", "documentation"],
                language="python",
                confidence=0.9,
                validation_status=ValidationStatus.PENDING,
            )
            items.append(item)

        # Extract public classes/functions
        for name in dir(module):
            if name.startswith("_"):
                continue
            obj = getattr(module, name)
            if inspect.isclass(obj) or inspect.isfunction(obj):
                doc = inspect.getdoc(obj)
                if doc:
                    item = EngineeringKnowledgeItem(
                        title=f"{package_name}.{name}",
                        summary=doc[:200].strip(),
                        content=doc.strip(),
                        domain=EngineeringDomain.LIBRARIES,
                        sub_category="api_reference",
                        knowledge_type=EngineeringKnowledgeType.REFERENCE,
                        source=KnowledgeSource.EXTERNAL_DOCS,
                        source_uri=f"python:{package_name}.{name}",
                        source_metadata={"module": package_name, "object": name, "type": type(obj).__name__},
                        tags=["python", "package", "api", name],
                        language="python",
                        confidence=0.85,
                        validation_status=ValidationStatus.PENDING,
                    )
                    items.append(item)

        return ExtractionResult(
            success=len(errors) == 0,
            items=items,
            errors=errors,
            source=f"python:{package_name}",
            source_type=KnowledgeSource.EXTERNAL_DOCS,
            metadata={"objects_documented": len(items)},
        )

    def import_rust_crate_docs(self, crate_name: str) -> ExtractionResult:
        """Import documentation from a Rust crate (via docs.rs or local cargo doc)."""
        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Rust crate doc import not implemented for {crate_name}"],
            source=f"crates:{crate_name}",
            source_type=KnowledgeSource.EXTERNAL_DOCS,
        )


# === Unified External Importer ===

class UnifiedExternalImporter:
    """Unified interface for all external knowledge imports."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/external_knowledge")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.docs_importer = ExternalKnowledgeImporter(cache_dir)
        self.research_importer = InternetResearchImporter(cache_dir)
        self.package_importer = PackageDocumentationImporter()

    def import_from_source(self, source_type: KnowledgeSource, identifier: str, **kwargs) -> ExtractionResult:
        """Import from a specific external source type."""
        if source_type == KnowledgeSource.EXTERNAL_DOCS:
            # Try as package first
            if ":" in identifier:
                lang, pkg = identifier.split(":", 1)
                if lang == "python":
                    return self.package_importer.import_python_package_docs(pkg)
                elif lang in ("javascript", "typescript", "npm"):
                    return self.docs_importer.import_package_docs(pkg, lang)
                elif lang == "rust":
                    return self.docs_importer.import_package_docs(pkg, lang)
                elif lang == "go":
                    return self.docs_importer.import_package_docs(pkg, lang)

            # Try as URL
            if identifier.startswith("http"):
                return self.docs_importer.import_from_url(identifier)

            # Try as predefined source
            return self.docs_importer.import_from_source(identifier, kwargs.get("query", ""))

        elif source_type == KnowledgeSource.INTERNET_RESEARCH:
            if identifier.startswith("http"):
                return self.research_importer.import_from_url(identifier)
            elif "stackoverflow" in identifier:
                return self.research_importer.import_from_stackoverflow(identifier)
            elif "github.com" in identifier:
                return self.research_importer.import_from_github_repo(identifier)
            else:
                return self.research_importer.search_and_import(identifier)

        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Unsupported source type: {source_type}"],
            source=identifier,
            source_type=source_type,
        )