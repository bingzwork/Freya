"""Documentation Extractor.

Extracts structured knowledge from documentation files:
- Markdown (.md, .markdown)
- PDF (if PDF support exists in project)

Extracts:
- Headings and sections
- Procedures
- Technical explanations
- Code examples
- Architecture descriptions
- Configuration
- Important concepts
- Warnings
- References
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logger import logger

from app.knowledge_extraction.extractors import Extractor
from app.knowledge_extraction.models import (
    KnowledgeObject,
    KnowledgeExtractionResult,
    SourceType,
    KnowledgeCategory,
)


class DocumentExtractor(Extractor):
    """Extract knowledge from documentation files (Markdown, PDF)."""

    source_type = SourceType.DOCUMENTATION
    supported_extensions = [".md", ".markdown", ".txt", ".rst"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize document extractor.

        Args:
            config: Optional configuration with keys:
                - extract_code_blocks: Whether to extract code blocks (default: True)
                - extract_tables: Whether to extract markdown tables (default: True)
                - min_section_length: Minimum section length to extract (default: 50)
                - preserve_hierarchy: Whether to preserve heading hierarchy (default: True)
        """
        super().__init__(config)
        self.extract_code_blocks = self.config.get("extract_code_blocks", True)
        self.extract_tables = self.config.get("extract_tables", True)
        self.min_section_length = self.config.get("min_section_length", 50)
        self.preserve_hierarchy = self.config.get("preserve_hierarchy", True)

        # PDF support check
        self._pdf_available = self._check_pdf_support()
        if self._pdf_available:
            self.supported_extensions.append(".pdf")

    def _check_pdf_support(self) -> bool:
        """Check if PDF parsing is available."""
        try:
            import pypdf  # type: ignore
            return True
        except ImportError:
            try:
                import pdfplumber  # type: ignore
                return True
            except ImportError:
                return False

    def extract(self, content: str, source: str, **context) -> KnowledgeExtractionResult:
        """Extract knowledge from documentation content.

        Args:
            content: Raw documentation text (Markdown, RST, or plain text).
            source: Source identifier (file path).
            **context: Additional context:
                - file_path: Full path to source file
                - project_name: Project name if available

        Returns:
            KnowledgeExtractionResult with extracted knowledge objects.
        """
        start_time = self._get_time()

        source_path = Path(source)
        extension = source_path.suffix.lower()

        # Handle PDF files
        if extension == ".pdf":
            if not self._pdf_available:
                return self._create_error_result(
                    "PDF support not available. Install pypdf or pdfplumber.",
                    source,
                    start_time,
                )
            return self._extract_from_pdf(source, start_time, context)

        # Handle text-based formats (Markdown, RST, txt)
        return self._extract_from_text(content, source, start_time, context)

    def _get_time(self) -> float:
        import time
        return time.time()

    def _extract_from_pdf(
        self,
        file_path: str,
        start_time: float,
        context: Dict[str, Any],
    ) -> KnowledgeExtractionResult:
        """Extract text from PDF and process."""
        try:
            # Try pdfplumber first (better text extraction)
            try:
                import pdfplumber  # type: ignore
                text_parts = []
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                content = "\n\n".join(text_parts)
            except ImportError:
                # Fallback to pypdf
                import pypdf  # type: ignore
                content = ""
                with open(file_path, "rb") as f:
                    reader = pypdf.PdfReader(f)
                    for page in reader.pages:
                        text = page.extract_text()
                        if text:
                            content += text + "\n\n"

            if not content.strip():
                return self._create_error_result(
                    "No text content extracted from PDF",
                    file_path,
                    start_time,
                )

            return self._extract_from_text(content, file_path, start_time, context)

        except Exception as e:
            return self._create_error_result(
                f"PDF extraction failed: {str(e)}",
                file_path,
                start_time,
                details={"exception_type": type(e).__name__},
            )

    def _extract_from_text(
        self,
        content: str,
        source: str,
        start_time: float,
        context: Dict[str, Any],
    ) -> KnowledgeExtractionResult:
        """Extract knowledge from text content (Markdown, RST, plain text)."""
        knowledge_objects = []

        # Parse document structure
        sections = self._parse_sections(content)

        for section in sections:
            # Extract main section content
            if len(section["content"]) >= self.min_section_length:
                obj = self._create_section_object(section, source, context)
                knowledge_objects.append(obj)

            # Extract code blocks within section
            if self.extract_code_blocks:
                code_objects = self._extract_code_blocks(section, source, context)
                knowledge_objects.extend(code_objects)

            # Extract tables
            if self.extract_tables:
                table_objects = self._extract_tables(section, source, context)
                knowledge_objects.extend(table_objects)

        # Also extract global code blocks not in sections
        if self.extract_code_blocks:
            global_code = self._extract_code_blocks({"content": content, "heading": ""}, source, context)
            knowledge_objects.extend(global_code)

        # Extract admonitions (warnings, notes, tips)
        admonition_objects = self._extract_admonitions(content, source, context)
        knowledge_objects.extend(admonition_objects)

        # Deduplicate
        knowledge_objects = self._deduplicate(knowledge_objects)

        return self._create_success_result(
            knowledge_objects=knowledge_objects,
            source=source,
            start_time=start_time,
            metadata={
                "sections_found": len(sections),
                "extracted_count": len(knowledge_objects),
                "file_type": Path(source).suffix,
            },
        )

    def _parse_sections(self, content: str) -> List[Dict[str, Any]]:
        """Parse document into hierarchical sections.

        Returns list of sections with:
        - heading: Section heading text
        - level: Heading level (1-6)
        - content: Section content
        - line_start: Starting line number
        """
        sections = []
        lines = content.split("\n")

        current_heading = ""
        current_level = 0
        current_content = []
        heading_line = 0

        # Markdown header pattern
        md_header_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        # RST header pattern (underlined)
        rst_header_pattern = re.compile(r"^([=\-~*+^])\1{3,}$")

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check for Markdown header
            md_match = md_header_pattern.match(line)
            if md_match:
                # Save previous section
                if current_heading or current_content:
                    sections.append({
                        "heading": current_heading,
                        "level": current_level,
                        "content": "\n".join(current_content).strip(),
                        "line_start": heading_line,
                    })

                # Start new section
                current_level = len(md_match.group(1))
                current_heading = md_match.group(2).strip()
                current_content = []
                heading_line = i
                i += 1
                continue

            # Check for RST header (underline style)
            if i + 1 < len(lines):
                rst_match = rst_header_pattern.match(lines[i + 1])
                if rst_match and line.strip():
                    # Save previous section
                    if current_heading or current_content:
                        sections.append({
                            "heading": current_heading,
                            "level": current_level,
                            "content": "\n".join(current_content).strip(),
                            "line_start": heading_line,
                        })

                    # Determine level from underline char
                    underline_char = rst_match.group(1)
                    level_map = {"=": 1, "-": 2, "~": 3, "*": 4, "+": 5, "^": 6}
                    current_level = level_map.get(underline_char, 1)
                    current_heading = line.strip()
                    current_content = []
                    heading_line = i
                    i += 2
                    continue

            current_content.append(line)
            i += 1

        # Don't forget last section
        if current_heading or current_content:
            sections.append({
                "heading": current_heading,
                "level": current_level,
                "content": "\n".join(current_content).strip(),
                "line_start": heading_line,
            })

        # If no sections found, treat whole document as one section
        if not sections:
            sections.append({
                "heading": Path(source).stem if "source" in locals() else "Document",
                "level": 0,
                "content": content.strip(),
                "line_start": 0,
            })

        return sections

    def _create_section_object(
        self,
        section: Dict[str, Any],
        source: str,
        context: Dict[str, Any],
    ) -> KnowledgeObject:
        """Create knowledge object from a document section."""
        heading = section["heading"]
        content = section["content"]
        level = section["level"]

        # Infer category from heading
        category = self._infer_category_from_heading(heading)

        # Generate title with hierarchy if enabled
        if self.preserve_hierarchy and heading:
            title = heading
        else:
            title = f"Section: {heading}" if heading else "Document Content"

        # Extract tags from content
        tags = self._extract_tags(content)
        tags.append(f"heading_level_{level}")

        # Estimate confidence based on content quality
        confidence = self._estimate_section_confidence(content, heading)

        return KnowledgeObject(
            title=title,
            summary=content[:300],
            content=content,
            source=source,
            source_type=SourceType.DOCUMENTATION,
            category=category,
            confidence=confidence,
            tags=tags,
            metadata={
                "extraction_method": "document_section",
                "heading_level": level,
                "line_start": section["line_start"],
                "project_name": context.get("project_name"),
            },
        )

    def _extract_code_blocks(
        self,
        section: Dict[str, Any],
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract code blocks from a section."""
        objects = []
        content = section["content"]

        # Match fenced code blocks: ```language\ncode\n```
        pattern = r"```(\w+)?\n(.+?)\n```"
        matches = re.finditer(pattern, content, re.DOTALL)

        for idx, match in enumerate(matches):
            language = match.group(1) or "text"
            code = match.group(2).strip()

            if len(code) < 10:
                continue

            obj = KnowledgeObject(
                title=f"Code Example: {section['heading'] or 'Document'} ({language})",
                summary=f"{language} code snippet from {section['heading'] or 'document'}",
                content=code,
                source=source,
                source_type=SourceType.DOCUMENTATION,
                category=KnowledgeCategory.ALGORITHM if language != "text" else KnowledgeCategory.EXAMPLE,
                confidence=0.8,
                language=language,
                tags=["code", "example", language, f"section_{idx}"],
                metadata={
                    "extraction_method": "code_block",
                    "parent_section": section["heading"],
                    "section_level": section.get("level", 0),
                },
            )
            objects.append(obj)

        return objects

    def _extract_tables(
        self,
        section: Dict[str, Any],
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract Markdown tables from a section."""
        objects = []
        content = section["content"]

        # Simple Markdown table pattern
        # Matches lines with | separators
        lines = content.split("\n")
        table_lines = []
        in_table = False

        for line in lines:
            if "|" in line and line.strip().startswith("|"):
                table_lines.append(line)
                in_table = True
            elif in_table and ("|" not in line or not line.strip().startswith("|")):
                if table_lines:
                    # Process collected table
                    obj = self._create_table_object(table_lines, section, source, context)
                    if obj:
                        objects.append(obj)
                    table_lines = []
                    in_table = False

        # Don't forget last table
        if table_lines:
            obj = self._create_table_object(table_lines, section, source, context)
            if obj:
                objects.append(obj)

        return objects

    def _create_table_object(
        self,
        table_lines: List[str],
        section: Dict[str, Any],
        source: str,
        context: Dict[str, Any],
    ) -> Optional[KnowledgeObject]:
        """Create knowledge object from Markdown table."""
        if len(table_lines) < 2:
            return None

        # Parse table
        headers = [c.strip() for c in table_lines[0].split("|") if c.strip()]
        if not headers:
            return None

        rows = []
        for line in table_lines[2:]:  # Skip header and separator
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells:
                rows.append(cells)

        # Note: row_count is number of data rows (excluding header and separator)
        # Some markdown tables might not have a separator row, handle gracefully
        data_row_count = len(rows)

        if data_row_count == 0:
            return None

        # Format table content
        table_content = " | ".join(headers) + "\n"
        table_content += " | ".join(["---"] * len(headers)) + "\n"
        for row in rows:
            table_content += " | ".join(row) + "\n"

        title = f"Table: {section['heading'] or 'Document'}"
        if len(headers) > 0:
            title += f" ({headers[0]}...)"

        return KnowledgeObject(
            title=title,
            summary=f"Table with {len(headers)} columns and {data_row_count} rows",
            content=table_content,
            source=source,
            source_type=SourceType.DOCUMENTATION,
            category=KnowledgeCategory.REFERENCE,
            confidence=0.75,
            tags=["table", "reference", "data"],
            metadata={
                "extraction_method": "markdown_table",
                "parent_section": section["heading"],
                "column_count": len(headers),
                "row_count": data_row_count,
                "headers": headers,
            },
        )

    def _extract_admonitions(
        self,
        content: str,
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract admonitions (notes, warnings, tips, etc.) from content.

        Supports:
        - Markdown-style: > **Note:** content
        - Custom admonition: ::: note ... :::
        - GitHub-style: > [!NOTE] content
        - Sphinx-style: .. note:: content
        """
        objects = []

        # Pattern 1: GitHub-style admonitions > [!TYPE] content
        gh_pattern = r">\s*\[!(NOTE|WARNING|TIP|IMPORTANT|CAUTION|NOTE)\]\s*(.+?)(?=\n>|\n\n|$)"
        matches = re.finditer(gh_pattern, content, re.IGNORECASE | re.DOTALL)
        for match in matches:
            ad_type = match.group(1).upper()
            ad_content = match.group(2).strip()
            if len(ad_content) >= 20:
                obj = self._create_admonition_object(ad_type, ad_content, source, context)
                objects.append(obj)

        # Pattern 2: Custom admonition blocks ::: type ... :::
        custom_pattern = r":::\s*(\w+)\s*\n(.+?)\n:::"
        matches = re.finditer(custom_pattern, content, re.DOTALL | re.IGNORECASE)
        for match in matches:
            ad_type = match.group(1).upper()
            ad_content = match.group(2).strip()
            if len(ad_content) >= 20:
                obj = self._create_admonition_object(ad_type, ad_content, source, context)
                objects.append(obj)

        # Pattern 3: Sphinx-style directives .. type:: content
        sphinx_pattern = r"^\.\.\s*(note|warning|tip|important|caution|seealso)::\s*(.+?)(?=\n\s*\n|\n\.\.|\Z)"
        matches = re.finditer(sphinx_pattern, content, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        for match in matches:
            ad_type = match.group(1).upper()
            ad_content = match.group(2).strip()
            if len(ad_content) >= 20:
                obj = self._create_admonition_object(ad_type, ad_content, source, context)
                objects.append(obj)

        return objects

    def _create_admonition_object(
        self,
        ad_type: str,
        content: str,
        source: str,
        context: Dict[str, Any],
    ) -> KnowledgeObject:
        """Create knowledge object from admonition."""
        type_mapping = {
            "NOTE": KnowledgeCategory.REFERENCE,
            "WARNING": KnowledgeCategory.WARNING,
            "TIP": KnowledgeCategory.BEST_PRACTICE,
            "IMPORTANT": KnowledgeCategory.WARNING,
            "CAUTION": KnowledgeCategory.WARNING,
            "SEEALSO": KnowledgeCategory.REFERENCE,
        }

        category = type_mapping.get(ad_type, KnowledgeCategory.OTHER)
        confidence_map = {"WARNING": 0.8, "CAUTION": 0.8, "IMPORTANT": 0.75, "TIP": 0.7, "NOTE": 0.6, "SEEALSO": 0.6}

        return KnowledgeObject(
            title=f"{ad_type.title()}: {content[:60]}",
            summary=content[:200],
            content=content,
            source=source,
            source_type=SourceType.DOCUMENTATION,
            category=category,
            confidence=confidence_map.get(ad_type, 0.6),
            tags=[ad_type.lower(), "admonition"],
            metadata={
                "extraction_method": "admonition",
                "admonition_type": ad_type,
            },
        )

    def _infer_category_from_heading(self, heading: str) -> KnowledgeCategory:
        """Infer knowledge category from section heading."""
        if not heading:
            return KnowledgeCategory.OTHER

        heading_lower = heading.lower()

        category_keywords = {
            KnowledgeCategory.PROCEDURE: [
                "install", "setup", "configure", "usage", "tutorial", "guide",
                "how to", "getting started", "quickstart", "steps"
            ],
            KnowledgeCategory.BEST_PRACTICE: [
                "best practice", "recommend", "guideline", "convention",
                "style guide", "do and don't"
            ],
            KnowledgeCategory.ALGORITHM: [
                "algorithm", "implementation", "code example", "api reference",
                "function", "class", "method"
            ],
            KnowledgeCategory.ARCHITECTURE: [
                "architect", "design", "structure", "overview", "components",
                "system", "module"
            ],
            KnowledgeCategory.TROUBLESHOOTING: [
                "troubleshoot", "debug", "error", "faq", "common issue",
                "problem", "fix"
            ],
            KnowledgeCategory.CONCEPT: [
                "concept", "definition", "terminology", "glossary", "what is"
            ],
            KnowledgeCategory.WARNING: [
                "warning", "caution", "important", "note", "limitation",
                "deprecated", "security"
            ],
            KnowledgeCategory.REFERENCE: [
                "reference", "api", "configuration", "options", "parameters",
                "settings", "environment variable"
            ],
        }

        for category, keywords in category_keywords.items():
            if any(kw in heading_lower for kw in keywords):
                return category

        return KnowledgeCategory.OTHER

    def _estimate_section_confidence(self, content: str, heading: str) -> float:
        """Estimate confidence based on content quality."""
        confidence = 0.6  # Base for documentation

        # Longer content = more confident
        if len(content) > 500:
            confidence += 0.1
        elif len(content) > 200:
            confidence += 0.05

        # Has code blocks = higher confidence
        if "```" in content:
            confidence += 0.1

        # Has structured content
        if re.search(r"^[\s]*[-*+]\s+", content, re.MULTILINE):  # Lists
            confidence += 0.05
        if "|" in content and content.count("|") > 4:  # Tables
            confidence += 0.05

        # Specific technical content
        if any(kw in content.lower() for kw in ["function", "class", "api", "config", "parameter"]):
            confidence += 0.05

        return min(confidence, 0.9)

    def _extract_tags(self, content: str) -> List[str]:
        """Extract relevant tags from content."""
        tags = []
        content_lower = content.lower()

        tag_keywords = {
            "python": ["python", "py", "pip", "venv", "django", "flask", "fastapi", "pytest"],
            "javascript": ["javascript", "js", "node", "npm", "react", "vue", "typescript", "ts", "deno"],
            "api": ["api", "rest", "graphql", "endpoint", "request", "response", "swagger", "openapi"],
            "database": ["database", "sql", "nosql", "postgres", "postgresql", "mysql", "mongodb", "redis", "sqlite"],
            "docker": ["docker", "container", "kubernetes", "k8s", "compose", "dockerfile", "kubectl"],
            "git": ["git", "commit", "branch", "merge", "rebase", "pull request", "github", "gitlab"],
            "testing": ["test", "testing", "pytest", "jest", "unit test", "integration test", "coverage"],
            "security": ["security", "auth", "authentication", "authorization", "encryption", "ssl", "tls", "oauth", "jwt"],
            "performance": ["performance", "optimize", "speed", "latency", "throughput", "cache", "benchmark"],
            "deployment": ["deploy", "deployment", "ci/cd", "ci", "cd", "pipeline", "release", "production"],
            "configuration": ["config", "configuration", "settings", "environment", "env", "yaml", "toml", "json"],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in content_lower for kw in keywords):
                tags.append(tag)

        return tags

    def _deduplicate(self, objects: List[KnowledgeObject]) -> List[KnowledgeObject]:
        """Remove duplicate knowledge objects."""
        if not objects:
            return []

        unique = []
        seen_signatures = set()

        for obj in objects:
            # Create signature from category + first 100 chars of content
            sig = f"{obj.category.value}:{obj.content[:100]}"
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                unique.append(obj)

        return unique