"""External Knowledge Import for Software Engineering Knowledge.

Imports knowledge from:
- Official documentation (package docs, language specs)
- Internet research (StackOverflow, blogs, tutorials)
- Standards bodies (RFCs, ISO, W3C)
- Vendor documentation (AWS, GCP, Azure)
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, quote_plus

import httpx
from bs4 import BeautifulSoup

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


class RateLimiter:
    """Simple rate limiter for HTTP requests."""

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0.0

    def wait(self) -> None:
        """Wait if necessary to maintain rate limit."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()


class HTTPClient:
    """Async HTTP client with rate limiting and error handling."""

    def __init__(self, timeout: float = 30.0, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        self._rate_limiters: Dict[str, RateLimiter] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Freya AI Knowledge Bot/1.0; +https://github.com/freya-ai)"
                },
            )
        return self._client

    def _get_rate_limiter(self, domain: str, rate_limit: float) -> RateLimiter:
        if domain not in self._rate_limiters:
            self._rate_limiters[domain] = RateLimiter(rate_limit)
        return self._rate_limiters[domain]

    async def get(self, url: str, rate_limit: float = 1.0, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Fetch content from URL with rate limiting and retries."""
        parsed = urlparse(url)
        domain = parsed.netloc
        rate_limiter = self._get_rate_limiter(domain, rate_limit)

        client = await self._get_client()
        request_headers = headers or {}

        for attempt in range(self.max_retries):
            rate_limiter.wait()
            try:
                response = await client.get(url, headers=request_headers)
                response.raise_for_status()
                return response.text
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                    continue
                elif e.response.status_code >= 500:  # Server error
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                return None
            except (httpx.RequestError, httpx.TimeoutException):
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
        return None

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class HTMLParser:
    """Parse HTML content using BeautifulSoup with CSS selectors."""

    @staticmethod
    def extract_content(
        html: str,
        content_selector: str,
        title_selector: str = "h1",
        section_selector: str = "section",
        base_url: str = "",
    ) -> Dict[str, Any]:
        """Extract structured content from HTML."""
        soup = BeautifulSoup(html, "lxml")

        # Extract title
        title_elem = soup.select_one(title_selector)
        title = title_elem.get_text(strip=True) if title_elem else ""

        # Extract main content
        content_elem = soup.select_one(content_selector)
        if not content_elem:
            # Fallback: try body
            content_elem = soup.select_one("body")

        content = ""
        sections = []

        if content_elem:
            # Remove navigation, headers, footers, scripts, styles
            for unwanted in content_elem.select("nav, header, footer, script, style, .navigation, .sidebar, .toc, .admonition"):
                unwanted.decompose()

            # Extract sections
            for section in content_elem.select(section_selector):
                section_title_elem = section.select_one("h1, h2, h3, h4")
                section_title = section_title_elem.get_text(strip=True) if section_title_elem else ""
                section_text = section.get_text(separator="\n", strip=True)
                if section_text:
                    sections.append({
                        "title": section_title,
                        "content": section_text[:5000],  # Limit section size
                    })

            # Get full content text
            content = content_elem.get_text(separator="\n", strip=True)

        # Extract code blocks
        code_blocks = []
        for code in content_elem.select("pre code, pre") if content_elem else []:
            code_text = code.get_text(strip=True)
            if code_text and len(code_text) > 10:
                code_blocks.append(code_text[:3000])

        # Extract links
        links = []
        for link in soup.select("a[href]") if content_elem else []:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if href and text:
                # Make absolute URL
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)
                links.append({"url": href, "text": text})

        return {
            "title": title,
            "content": content[:15000],  # Limit total content
            "sections": sections,
            "code_blocks": code_blocks,
            "links": links[:50],  # Limit links
        }


class ExternalKnowledgeImporter:
    """Import engineering knowledge from external sources."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/external_knowledge_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.registry = get_category_registry()
        self.http_client = HTTPClient()
        self.parser = HTMLParser()

    async def import_from_source(self, source_name: str, query: str, max_results: int = 10) -> ExtractionResult:
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

        try:
            # Build search URL for the source
            search_url = self._build_search_url(source, query)
            if not search_url:
                return ExtractionResult(
                    success=False,
                    items=[],
                    errors=[f"Cannot build search URL for source: {source_name}"],
                    source=source_name,
                    source_type=source.source_type,
                )

            # Fetch search results page
            html = await self.http_client.get(search_url, rate_limit=source.rate_limit)
            if not html:
                return ExtractionResult(
                    success=False,
                    items=[],
                    errors=[f"Failed to fetch search results from {source_name}"],
                    source=source_name,
                    source_type=source.source_type,
                )

            # Parse search results to get article URLs
            article_urls = self._parse_search_results(source_name, html, base_url=source.base_url)
            article_urls = article_urls[:max_results]

            # Fetch and parse each article
            items = []
            errors = []
            for url in article_urls:
                try:
                    article_html = await self.http_client.get(url, rate_limit=source.rate_limit)
                    if not article_html:
                        errors.append(f"Failed to fetch article: {url}")
                        continue

                    parsed = self.parser.extract_content(
                        article_html,
                        content_selector=source.selectors.get("content", "main"),
                        title_selector=source.selectors.get("title", "h1"),
                        section_selector=source.selectors.get("section", "section"),
                        base_url=source.base_url,
                    )

                    if parsed["content"]:
                        item = self.create_knowledge_from_content(
                            title=parsed["title"] or self._extract_title_from_url(url),
                            content=parsed["content"],
                            url=url,
                            domain=self._infer_domain(source_name, parsed),
                            knowledge_type=EngineeringKnowledgeType.REFERENCE,
                            tags=["external", "documentation", source_name] + self._extract_tags(parsed),
                            language=self._infer_language(source_name),
                        )
                        # Add sections and code blocks to metadata
                        item.source_metadata.update({
                            "sections": parsed["sections"],
                            "code_blocks": parsed["code_blocks"],
                            "links": parsed["links"],
                            "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        items.append(item)

                except Exception as e:
                    errors.append(f"Error processing {url}: {str(e)}")

            return ExtractionResult(
                success=len(items) > 0,
                items=items,
                errors=errors,
                source=source_name,
                source_type=source.source_type,
                metadata={"source_config": source.__dict__, "articles_fetched": len(items)},
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Import failed: {str(e)}"],
                source=source_name,
                source_type=source.source_type,
            )

    def _build_search_url(self, source: ExternalSource, query: str) -> Optional[str]:
        """Build search URL for a source."""
        search_endpoints = {
            "python_docs": f"{source.base_url}search.html?q={quote_plus(query)}",
            "mdn": f"{source.base_url}search?q={quote_plus(query)}",
            "rust_docs": f"{source.base_url}search.html?q={quote_plus(query)}",
            "go_docs": f"{source.base_url}search?q={quote_plus(query)}",
            "aws_docs": f"{source.base_url}search?query={quote_plus(query)}",
            "kubernetes_docs": f"{source.base_url}search?q={quote_plus(query)}",
            "terraform_docs": f"{source.base_url}search?q={quote_plus(query)}",
            "rfc_editor": f"{source.base_url}search/rfc_search_detail.php?search={quote_plus(query)}",
        }
        return search_endpoints.get(source_name if False else None)  # placeholder

    def _build_search_url(self, source: ExternalSource, query: str) -> Optional[str]:
        """Build search URL for a source."""
        base = source.base_url.rstrip("/")
        search_paths = {
            "python_docs": "/search.html",
            "mdn": "/search",
            "rust_docs": "/search.html",
            "go_docs": "/search",
            "aws_docs": "/search",
            "kubernetes_docs": "/search",
            "terraform_docs": "/search",
            "rfc_editor": "/search/rfc_search_detail.php",
        }

        # This is a simplified approach - in reality each site has different search params
        # For now, we'll use the base URL and append common search paths
        return f"{base}{search_paths.get(source.name.lower().replace(' ', '_'), '/search')}?q={quote_plus(query)}"

    def _parse_search_results(self, source_name: str, html: str, base_url: str) -> List[str]:
        """Parse search results page to extract article URLs."""
        soup = BeautifulSoup(html, "lxml")
        urls = []

        # Source-specific selectors for search results
        selectors = {
            "python_docs": "div.search-results a[href], li.search-result a[href]",
            "mdn": "article.search-result a[href], .search-result a[href]",
            "rust_docs": "div.search-results a[href]",
            "go_docs": ".search-results a[href]",
            "aws_docs": ".aws-search-results a[href]",
            "kubernetes_docs": ".search-results a[href]",
            "terraform_docs": ".search-results a[href]",
            "rfc_editor": "table.search-results a[href]",
        }

        selector = selectors.get(source_name, "a[href]")
        for link in soup.select(selector):
            href = link.get("href", "")
            if href:
                # Make absolute URL
                if href.startswith("/"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)
                elif not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(base_url, href)

                # Filter out non-article links
                if self._is_article_url(href, source_name):
                    urls.append(href)

        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls

    def _is_article_url(self, url: str, source_name: str) -> bool:
        """Check if URL is likely an article/page (not nav, API, etc.)."""
        skip_patterns = [
            r"/api/", r"\.json$", r"\.xml$", r"\.pdf$",
            r"/search", r"/login", r"/signup", r"/account",
            r"github\.com", r"twitter\.com", r"linkedin\.com",
            r"#", r"javascript:", r"mailto:",
        ]
        for pattern in skip_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return False
        return True

    def _extract_title_from_url(self, url: str) -> str:
        """Extract a readable title from URL."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            title = path.split("/")[-1]
            title = title.replace("-", " ").replace("_", " ").replace(".html", "")
            return title.title()
        return "External Documentation"

    def _infer_domain(self, source_name: str, parsed: Dict[str, Any]) -> EngineeringDomain:
        """Infer engineering domain from source and content."""
        domain_map = {
            "python_docs": EngineeringDomain.LANGUAGES,
            "mdn": EngineeringDomain.WEB_DEVELOPMENT,
            "rust_docs": EngineeringDomain.LANGUAGES,
            "go_docs": EngineeringDomain.LANGUAGES,
            "aws_docs": EngineeringDomain.CLOUD,
            "kubernetes_docs": EngineeringDomain.CLOUD,
            "terraform_docs": EngineeringDomain.DEVOPS,
            "rfc_editor": EngineeringDomain.STANDARDS,
        }
        return domain_map.get(source_name, EngineeringDomain.LIBRARIES)

    def _infer_language(self, source_name: str) -> Optional[str]:
        """Infer programming language from source."""
        lang_map = {
            "python_docs": "python",
            "mdn": "javascript",
            "rust_docs": "rust",
            "go_docs": "go",
        }
        return lang_map.get(source_name)

    def _extract_tags(self, parsed: Dict[str, Any]) -> List[str]:
        """Extract tags from parsed content."""
        tags = []
        content_lower = parsed["content"].lower()

        tag_keywords = {
            "async": ["async", "await", "asyncio"],
            "testing": ["test", "pytest", "unittest"],
            "api": ["api", "rest", "graphql", "endpoint"],
            "database": ["database", "sql", "orm", "postgresql", "mysql"],
            "security": ["security", "auth", "oauth", "encryption"],
            "performance": ["performance", "optimization", "benchmark"],
            "deployment": ["deploy", "docker", "kubernetes", "ci/cd"],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in content_lower for kw in keywords):
                tags.append(tag)

        return tags

    async def import_from_url(self, url: str) -> ExtractionResult:
        """Import knowledge from a specific URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Determine source type and category
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

        try:
            html = await self.http_client.get(url)
            if not html:
                return ExtractionResult(
                    success=False,
                    items=[],
                    errors=[f"Failed to fetch URL: {url}"],
                    source=url,
                    source_type=source_type,
                    metadata={"category": category},
                )

            # Try to find content using common selectors
            parsed_content = self.parser.extract_content(
                html,
                content_selector="main, article, div.content, div.document, div#content, div#main-content",
                title_selector="h1",
                section_selector="section, div.section",
                base_url=f"{parsed.scheme}://{parsed.netloc}",
            )

            if not parsed_content["content"]:
                return ExtractionResult(
                    success=False,
                    items=[],
                    errors=[f"No content extracted from {url}"],
                    source=url,
                    source_type=source_type,
                    metadata={"category": category},
                )

            item = self.create_knowledge_from_content(
                title=parsed_content["title"] or self._extract_title_from_url(url),
                content=parsed_content["content"],
                url=url,
                domain=self._infer_domain_from_url(url),
                knowledge_type=EngineeringKnowledgeType.REFERENCE,
                tags=["external", category] + self._extract_tags(parsed_content),
            )
            item.source_metadata.update({
                "sections": parsed_content["sections"],
                "code_blocks": parsed_content["code_blocks"],
                "links": parsed_content["links"],
                "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
            })

            return ExtractionResult(
                success=True,
                items=[item],
                errors=[],
                source=url,
                source_type=source_type,
                metadata={"category": category},
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Import failed: {str(e)}"],
                source=url,
                source_type=source_type,
                metadata={"category": category},
            )

    def _infer_domain_from_url(self, url: str) -> EngineeringDomain:
        """Infer domain from URL."""
        domain = urlparse(url).netloc.lower()
        if any(d in domain for d in ["python", "rust", "go.dev", "nodejs", "javascript", "typescript"]):
            return EngineeringDomain.LANGUAGES
        elif any(d in domain for d in ["aws", "azure", "gcp", "cloud"]):
            return EngineeringDomain.CLOUD
        elif any(d in domain for d in ["kubernetes", "docker", "terraform", "ansible"]):
            return EngineeringDomain.DEVOPS
        elif any(d in domain for d in ["react", "vue", "angular", "web", "mdn", "w3c"]):
            return EngineeringDomain.WEB_DEVELOPMENT
        elif any(d in domain for d in ["rfc", "iso", "w3c", "ecma"]):
            return EngineeringDomain.STANDARDS
        return EngineeringDomain.LIBRARIES

    async def import_package_docs(self, package_name: str, language: str = "python") -> ExtractionResult:
        """Import documentation for a specific package."""
        if language == "python":
            # Try to import from PyPI / ReadTheDocs
            urls_to_try = [
                f"https://{package_name}.readthedocs.io/",
                f"https://pypi.org/project/{package_name}/",
                f"https://github.com/{package_name}/{package_name}",
            ]
        elif language in ("javascript", "typescript"):
            urls_to_try = [
                f"https://www.npmjs.com/package/{package_name}",
                f"https://github.com/{package_name}/{package_name}",
            ]
        elif language == "rust":
            urls_to_try = [
                f"https://docs.rs/{package_name}",
                f"https://crates.io/crates/{package_name}",
            ]
        elif language == "go":
            urls_to_try = [
                f"https://pkg.go.dev/{package_name}",
            ]
        else:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Unsupported language: {language}"],
                source=f"{language}:{package_name}",
                source_type=KnowledgeSource.EXTERNAL_DOCS,
            )

        items = []
        errors = []

        for url in urls_to_try:
            try:
                result = await self.import_from_url(url)
                if result.success:
                    items.extend(result.items)
                    break  # Success with first working URL
                else:
                    errors.extend(result.errors)
            except Exception as e:
                errors.append(f"Error trying {url}: {str(e)}")

        return ExtractionResult(
            success=len(items) > 0,
            items=items,
            errors=errors,
            source=f"{language}:{package_name}",
            source_type=KnowledgeSource.EXTERNAL_DOCS,
            metadata={"package": package_name, "language": language, "urls_tried": urls_to_try},
        )

    async def import_from_standards_body(self, body: str, identifier: str) -> ExtractionResult:
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

        return await self.import_from_url(url)

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
                "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
            },
            tags=tags or ["external", "documentation"],
            language=language,
            confidence=0.75,
            validation_status=ValidationStatus.PENDING,
        )

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.close()


class InternetResearchImporter:
    """Import knowledge from internet research (search results, articles, etc.)."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/internet_research_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.registry = get_category_registry()
        self.http_client = HTTPClient()
        self.parser = HTMLParser()

    async def search_and_import(self, query: str, max_results: int = 5) -> ExtractionResult:
        """Search the web and import top results as knowledge."""
        # Use DuckDuckGo HTML scraping for search (no API key required)
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

        try:
            html = await self.http_client.get(search_url, rate_limit=0.5)
            if not html:
                return ExtractionResult(
                    success=False,
                    items=[],
                    errors=[f"Failed to fetch search results for: {query}"],
                    source=f"search:{query}",
                    source_type=KnowledgeSource.INTERNET_RESEARCH,
                )

            # Parse search results
            soup = BeautifulSoup(html, "lxml")
            result_links = []

            # DuckDuckGo result selectors
            for link in soup.select("a.result__url, a.result__snippet, .result__title a, .links_main a"):
                href = link.get("href", "")
                if href and href.startswith("http"):
                    # Skip known non-content domains
                    parsed = urlparse(href)
                    skip_domains = ["youtube.com", "twitter.com", "x.com", "linkedin.com", "facebook.com", "instagram.com"]
                    if parsed.netloc not in skip_domains:
                        result_links.append(href)

            # Deduplicate
            seen = set()
            unique_links = []
            for link in result_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)

            unique_links = unique_links[:max_results]

            # Fetch and import each result
            items = []
            errors = []
            for url in unique_links:
                try:
                    result = await self.import_from_url(url)
                    if result.success:
                        items.extend(result.items)
                    else:
                        errors.extend(result.errors)
                except Exception as e:
                    errors.append(f"Error importing {url}: {str(e)}")

            return ExtractionResult(
                success=len(items) > 0,
                items=items,
                errors=errors,
                source=f"search:{query}",
                source_type=KnowledgeSource.INTERNET_RESEARCH,
                metadata={"query": query, "results_found": len(unique_links)},
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                items=[],
                errors=[f"Search failed: {str(e)}"],
                source=f"search:{query}",
                source_type=KnowledgeSource.INTERNET_RESEARCH,
            )

    async def import_from_stackoverflow(self, question_id: str) -> ExtractionResult:
        """Import a StackOverflow Q&A as engineering knowledge."""
        url = f"https://stackoverflow.com/questions/{question_id}"
        return await self.import_from_url(url)

    async def import_from_github_repo(self, repo_url: str) -> ExtractionResult:
        """Import knowledge from a GitHub repository (README, docs, wiki)."""
        # Normalize to GitHub URL
        if not repo_url.startswith("http"):
            repo_url = f"https://github.com/{repo_url}"

        # Try to fetch README
        readme_urls = [
            repo_url.rstrip("/") + "/blob/main/README.md",
            repo_url.rstrip("/") + "/blob/master/README.md",
            repo_url.rstrip("/") + "/blob/main/README.rst",
            repo_url.rstrip("/") + "/blob/master/README.rst",
        ]

        items = []
        errors = []

        for url in readme_urls:
            try:
                result = await self.import_from_url(url)
                if result.success:
                    items.extend(result.items)
                    break
                else:
                    errors.extend(result.errors)
            except Exception as e:
                errors.append(f"Error fetching {url}: {str(e)}")

        return ExtractionResult(
            success=len(items) > 0,
            items=items,
            errors=errors,
            source=repo_url,
            source_type=KnowledgeSource.EXTERNAL_DOCS,
            metadata={"repo_url": repo_url},
        )

    async def import_from_url(self, url: str) -> ExtractionResult:
        """Import knowledge from a specific URL."""
        return await ExternalKnowledgeImporter().import_from_url(url)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.http_client.close()


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

    async def import_from_source(self, source_type: KnowledgeSource, identifier: str, **kwargs) -> ExtractionResult:
        """Import from a specific external source type."""
        if source_type == KnowledgeSource.EXTERNAL_DOCS:
            # Try as package first
            if ":" in identifier:
                lang, pkg = identifier.split(":", 1)
                if lang == "python":
                    return self.package_importer.import_python_package_docs(pkg)
                elif lang in ("javascript", "typescript", "npm"):
                    return await self.docs_importer.import_package_docs(pkg, lang)
                elif lang == "rust":
                    return await self.docs_importer.import_package_docs(pkg, lang)
                elif lang == "go":
                    return await self.docs_importer.import_package_docs(pkg, lang)

            # Try as URL
            if identifier.startswith("http"):
                return await self.docs_importer.import_from_url(identifier)

            # Try as predefined source
            return await self.docs_importer.import_from_source(identifier, kwargs.get("query", ""))

        elif source_type == KnowledgeSource.INTERNET_RESEARCH:
            if identifier.startswith("http"):
                return await self.research_importer.import_from_url(identifier)
            elif "stackoverflow" in identifier:
                return await self.research_importer.import_from_stackoverflow(identifier)
            elif "github.com" in identifier:
                return await self.research_importer.import_from_github_repo(identifier)
            else:
                return await self.research_importer.search_and_import(identifier)

        return ExtractionResult(
            success=False,
            items=[],
            errors=[f"Unsupported source type: {source_type}"],
            source=identifier,
            source_type=source_type,
        )

    async def close(self) -> None:
        """Close all HTTP clients."""
        await self.docs_importer.close()
        await self.research_importer.close()