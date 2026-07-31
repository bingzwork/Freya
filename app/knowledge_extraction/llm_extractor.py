"""LLM Response Extractor.

Extracts structured knowledge from LLM outputs including:
- Freya responses
- Stronger LLM responses
- Reasoning summaries
- Tool explanations
- Generated plans
- Generated documentation

Identifies useful knowledge such as:
- Facts
- Explanations
- Procedures
- Algorithms
- Best practices
- Recommendations
- Workflows
- Troubleshooting steps
- Software engineering concepts
"""

import re
from typing import Any, Dict, List, Optional

from app.knowledge_extraction.extractors import Extractor
from app.knowledge_extraction.models import (
    KnowledgeObject,
    KnowledgeExtractionResult,
    SourceType,
    KnowledgeCategory,
)


class LLMExtractor(Extractor):
    """Extract knowledge from LLM responses.

    Uses pattern matching and heuristics to identify structured knowledge
    in LLM outputs while ignoring conversational filler.
    """

    source_type = SourceType.LLM_RESPONSE
    supported_extensions = []  # Not file-based

    # Patterns for different knowledge types
    PATTERNS = {
        KnowledgeCategory.FACT: [
            r"(?:^|\n)(?:Fact|Note):\s*(.+)",
            r"(?:^|\n)(?:It is|It's|This is)\s+(?:a\s+)?(?:fact|known|true|established)",
        ],
        KnowledgeCategory.EXPLANATION: [
            r"(?:^|\n)(?:Explanation|How it works|This works by):\s*(.+)",
            r"(?:^|\n)(?:The reason|This is because|Because)\s+(.+)",
        ],
        KnowledgeCategory.PROCEDURE: [
            r"(?:^|\n)(?:Steps?|Procedure|To\s+\w+):\s*(.+)",
            r"(?:^|\n)(?:\d+\.\s+.+)(?:\n\d+\.\s+.+)+",  # Numbered lists
            r"(?:^|\n)(?:First|Then|Next|Finally)[,:]\s*(.+)",
        ],
        KnowledgeCategory.ALGORITHM: [
            r"(?:^|\n)(?:Algorithm|Pseudocode|Implementation):\s*(.+)",
            r"```[\w]*\n.+?\n```",  # Code blocks
        ],
        KnowledgeCategory.BEST_PRACTICE: [
            r"(?:^|\n)(?:Best practice|Recommendation|Should|Always|Never):\s*(.+)",
            r"(?:^|\n)(?:It is recommended|You should|Avoid)\s+(.+)",
        ],
        KnowledgeCategory.RECOMMENDATION: [
            r"(?:^|\n)(?:I recommend|Suggest|Consider|Try):\s*(.+)",
            r"(?:^|\n)(?:Better approach|Alternative):\s*(.+)",
        ],
        KnowledgeCategory.WORKFLOW: [
            r"(?:^|\n)(?:Workflow|Process|Pipeline):\s*(.+)",
            r"(?:^|\n)(?:Step \d+|Phase \d+):\s*(.+)",
        ],
        KnowledgeCategory.TROUBLESHOOTING: [
            r"(?:^|\n)(?:Troubleshooting|Debug|Fix|Error|Issue):\s*(.+)",
            r"(?:^|\n)(?:Common (?:issue|problem|error)|If (?:you see|this happens)):\s*(.+)",
        ],
        KnowledgeCategory.CONCEPT: [
            r"(?:^|\n)(?:Concept|Definition|Term):\s*(.+)",
            r"(?:^|\n)(?:\w+)\s+is\s+(?:a|an|the)\s+(.+)",
        ],
        KnowledgeCategory.WARNING: [
            r"(?:^|\n)(?:Warning|Caution|Note|Important):\s*(.+)",
            r"(?:^|\n)(?:Don't|Do not|Avoid|Never)\s+(.+)",
        ],
    }

    # Patterns to identify and ignore conversational filler
    FILLER_PATTERNS = [
        r"^(Hello|Hi|Hey|Thanks|Thank you|Sure|Okay|OK|Great|Good|Certainly|Absolutely)",
        r"(?:Happy to help|Let me know|Feel free|Here to help)",
        r"^(As an AI|I'm an AI|I don't have|I cannot|I can't)",
        r"^(Here is|Here's|Below is|Following is)",
        r"^(In summary|To summarize|In conclusion|Overall)",
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize LLM extractor.

        Args:
            config: Optional configuration with keys:
                - min_content_length: Minimum content length to consider (default: 50)
                - confidence_threshold: Minimum confidence to include (default: 0.3)
                - extract_code_blocks: Whether to extract code blocks (default: True)
        """
        super().__init__(config)
        self.min_content_length = self.config.get("min_content_length", 50)
        self.confidence_threshold = self.config.get("confidence_threshold", 0.3)
        self.extract_code_blocks = self.config.get("extract_code_blocks", True)

        # Compile patterns
        self._filler_regex = re.compile("|".join(self.FILLER_PATTERNS), re.IGNORECASE | re.MULTILINE)

    def extract(self, content: str, source: str, **context) -> KnowledgeExtractionResult:
        """Extract knowledge from LLM response content.

        Args:
            content: Raw LLM response text.
            source: Source identifier (conversation ID, message ID, etc.).
            **context: Additional context:
                - model: Model that generated the response
                - conversation_id: Conversation identifier
                - prompt: Original prompt (for context)

        Returns:
            KnowledgeExtractionResult with extracted knowledge objects.
        """
        start_time = self._get_time()

        if not content or len(content.strip()) < self.min_content_length:
            return self._create_error_result(
                "Content too short for meaningful extraction",
                source,
                start_time,
            )

        # Normalize content - remove common leading indentation
        normalized_content = self._normalize_content(content)

        # Remove conversational filler
        filtered_content = self._remove_filler(normalized_content)

        if len(filtered_content.strip()) < self.min_content_length:
            return self._create_error_result(
                "Content too short after removing filler",
                source,
                start_time,
            )

        knowledge_objects = []

        # Extract different types of knowledge
        knowledge_objects.extend(self._extract_by_patterns(filtered_content, source, context))
        knowledge_objects.extend(self._extract_code_blocks(filtered_content, source, context))
        knowledge_objects.extend(self._extract_structured_sections(filtered_content, source, context))
        knowledge_objects.extend(self._extract_key_value_pairs(filtered_content, source, context))

        # Deduplicate similar objects
        knowledge_objects = self._deduplicate(knowledge_objects)

        # Filter by confidence
        knowledge_objects = [
            obj for obj in knowledge_objects
            if obj.confidence >= self.confidence_threshold
        ]

        return self._create_success_result(
            knowledge_objects=knowledge_objects,
            source=source,
            start_time=start_time,
            metadata={
                "original_length": len(content),
                "filtered_length": len(filtered_content),
                "extracted_count": len(knowledge_objects),
            },
        )

    def _normalize_content(self, content: str) -> str:
        """Remove common leading indentation from content."""
        lines = content.split("\n")
        if not lines:
            return content

        # Find minimum indentation (excluding empty lines)
        min_indent = None
        for line in lines:
            stripped = line.lstrip()
            if stripped:
                indent = len(line) - len(stripped)
                if min_indent is None or indent < min_indent:
                    min_indent = indent

        if min_indent and min_indent > 0:
            # Remove common indentation
            normalized_lines = []
            for line in lines:
                if line.startswith(" " * min_indent):
                    normalized_lines.append(line[min_indent:])
                else:
                    normalized_lines.append(line)
            return "\n".join(normalized_lines)

        return content

    def _get_time(self) -> float:
        import time
        return time.time()

    def _remove_filler(self, content: str) -> str:
        """Remove conversational filler from content."""
        lines = content.split("\n")
        filtered_lines = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                filtered_lines.append(line)
                continue

            # Skip lines matching filler patterns
            if self._filler_regex.match(line_stripped):
                continue

            filtered_lines.append(line)

        return "\n".join(filtered_lines)

    def _extract_by_patterns(
        self,
        content: str,
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract knowledge using category patterns."""
        objects = []

        for category, patterns in self.PATTERNS.items():
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                for match in matches:
                    extracted = match.group(1) if match.groups() else match.group(0)
                    extracted = extracted.strip()

                    if len(extracted) < 20:  # Too short to be useful
                        continue

                    # Create knowledge object
                    obj = KnowledgeObject(
                        title=self._generate_title(extracted, category),
                        summary=extracted[:200],
                        content=extracted,
                        source=source,
                        source_type=SourceType.LLM_RESPONSE,
                        category=category,
                        confidence=self._estimate_confidence(extracted, category),
                        language=context.get("language"),
                        tags=self._extract_tags(extracted),
                        metadata={
                            "extraction_method": "pattern_matching",
                            "pattern_category": category.value,
                            "model": context.get("model"),
                            "conversation_id": context.get("conversation_id"),
                        },
                    )
                    objects.append(obj)

        return objects

    def _extract_code_blocks(
        self,
        content: str,
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract code blocks as algorithms/implementations."""
        if not self.extract_code_blocks:
            return []

        objects = []
        # Match code blocks with optional language
        pattern = r"```(\w+)?\n(.+?)\n```"
        matches = re.finditer(pattern, content, re.DOTALL)

        for match in matches:
            language = match.group(1) or "text"
            code = match.group(2).strip()

            if len(code) < 10:
                continue

            obj = KnowledgeObject(
                title=f"Code Example ({language})",
                summary=f"{language} code snippet ({len(code)} chars)",
                content=code,
                source=source,
                source_type=SourceType.LLM_RESPONSE,
                category=KnowledgeCategory.ALGORITHM if language != "text" else KnowledgeCategory.EXAMPLE,
                confidence=0.7,
                language=language,
                tags=["code", "example", language],
                metadata={
                    "extraction_method": "code_block",
                    "model": context.get("model"),
                },
            )
            objects.append(obj)

        return objects

    def _extract_structured_sections(
        self,
        content: str,
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract structured sections (headers, bullet points, etc.)."""
        objects = []

        # Markdown headers
        header_pattern = r"^(#{1,3})\s+(.+)$"
        lines = content.split("\n")

        current_section = ""
        current_content = []
        current_level = 0

        for line in lines:
            header_match = re.match(header_pattern, line)
            if header_match:
                # Save previous section
                if current_section and current_content:
                    full_content = "\n".join(current_content).strip()
                    if len(full_content) >= 30:
                        obj = KnowledgeObject(
                            title=current_section,
                            summary=full_content[:200],
                            content=full_content,
                            source=source,
                            source_type=SourceType.LLM_RESPONSE,
                            category=self._infer_category_from_title(current_section),
                            confidence=0.6,
                            tags=self._extract_tags(full_content),
                            metadata={
                                "extraction_method": "section_header",
                                "header_level": current_level,
                            },
                        )
                        objects.append(obj)

                # Start new section
                current_level = len(header_match.group(1))
                current_section = header_match.group(2).strip()
                current_content = []
            else:
                current_content.append(line)

        # Don't forget last section
        if current_section and current_content:
            full_content = "\n".join(current_content).strip()
            if len(full_content) >= 30:
                obj = KnowledgeObject(
                    title=current_section,
                    summary=full_content[:200],
                    content=full_content,
                    source=source,
                    source_type=SourceType.LLM_RESPONSE,
                    category=self._infer_category_from_title(current_section),
                    confidence=0.6,
                    tags=self._extract_tags(full_content),
                    metadata={"extraction_method": "section_header"},
                )
                objects.append(obj)

        # Bullet point lists
        bullet_pattern = r"^[\s]*[-*+]\s+(.+)$"
        bullets = re.findall(bullet_pattern, content, re.MULTILINE)
        if len(bullets) >= 3:  # Only if substantial list
            full_content = "\n".join(f"- {b}" for b in bullets)
            obj = KnowledgeObject(
                title="Bullet List",
                summary=f"List of {len(bullets)} items",
                content=full_content,
                source=source,
                source_type=SourceType.LLM_RESPONSE,
                category=KnowledgeCategory.PROCEDURE,
                confidence=0.5,
                tags=["list", "procedure"],
                metadata={"extraction_method": "bullet_list", "item_count": len(bullets)},
            )
            objects.append(obj)

        return objects

    def _extract_key_value_pairs(
        self,
        content: str,
        source: str,
        context: Dict[str, Any],
    ) -> List[KnowledgeObject]:
        """Extract key-value pairs (definitions, parameters, etc.)."""
        objects = []

        # Pattern: "Key: Value" or "Key = Value" or "**Key:** Value"
        kv_pattern = r"(?:^|\n)(?:\*\*)?([A-Za-z][A-Za-z0-9\s]{2,30})(?:\*\*)?(?:\s*[:=]\s*)(.+)"
        matches = re.finditer(kv_pattern, content, re.MULTILINE)

        pairs = []
        for match in matches:
            key = match.group(1).strip()
            value = match.group(2).strip()

            # Filter out conversational phrases
            if any(skip in key.lower() for skip in ["i ", "you ", "we ", "the ", "this ", "that "]):
                continue
            if len(key) > 40 or len(value) < 5:
                continue

            pairs.append((key, value))

        if len(pairs) >= 2:
            content_str = "\n".join(f"{k}: {v}" for k, v in pairs)
            obj = KnowledgeObject(
                title="Key-Value Pairs",
                summary=f"{len(pairs)} definitions/parameters extracted",
                content=content_str,
                source=source,
                source_type=SourceType.LLM_RESPONSE,
                category=KnowledgeCategory.DEFINITION,
                confidence=0.5,
                tags=["definitions", "parameters"],
                metadata={
                    "extraction_method": "key_value_pairs",
                    "pair_count": len(pairs),
                },
            )
            objects.append(obj)

        return objects

    def _generate_title(self, content: str, category: KnowledgeCategory) -> str:
        """Generate a title from content and category."""
        # Take first sentence or first 60 chars
        first_sentence = content.split(".")[0].strip()
        if len(first_sentence) > 60:
            first_sentence = first_sentence[:60] + "..."

        category_prefix = {
            KnowledgeCategory.FACT: "Fact: ",
            KnowledgeCategory.EXPLANATION: "Explanation: ",
            KnowledgeCategory.PROCEDURE: "Procedure: ",
            KnowledgeCategory.ALGORITHM: "Algorithm: ",
            KnowledgeCategory.BEST_PRACTICE: "Best Practice: ",
            KnowledgeCategory.RECOMMENDATION: "Recommendation: ",
            KnowledgeCategory.WORKFLOW: "Workflow: ",
            KnowledgeCategory.TROUBLESHOOTING: "Troubleshooting: ",
            KnowledgeCategory.CONCEPT: "Concept: ",
            KnowledgeCategory.WARNING: "Warning: ",
        }.get(category, "")

        return f"{category_prefix}{first_sentence}"

    def _estimate_confidence(self, content: str, category: KnowledgeCategory) -> float:
        """Estimate confidence of extraction."""
        base_confidence = {
            KnowledgeCategory.FACT: 0.7,
            KnowledgeCategory.EXPLANATION: 0.6,
            KnowledgeCategory.PROCEDURE: 0.65,
            KnowledgeCategory.ALGORITHM: 0.75,
            KnowledgeCategory.BEST_PRACTICE: 0.7,
            KnowledgeCategory.RECOMMENDATION: 0.6,
            KnowledgeCategory.WORKFLOW: 0.6,
            KnowledgeCategory.TROUBLESHOOTING: 0.65,
            KnowledgeCategory.CONCEPT: 0.55,
            KnowledgeCategory.WARNING: 0.7,
        }.get(category, 0.5)

        # Adjust based on content characteristics
        if len(content) > 200:
            base_confidence += 0.05
        if any(word in content.lower() for word in ["example", "code", "function", "class", "algorithm"]):
            base_confidence += 0.05
        if re.search(r"\d+\.\s+", content):  # Numbered steps
            base_confidence += 0.1

        return min(base_confidence, 0.95)

    def _infer_category_from_title(self, title: str) -> KnowledgeCategory:
        """Infer knowledge category from section title."""
        title_lower = title.lower()

        category_keywords = {
            KnowledgeCategory.PROCEDURE: ["step", "procedure", "how to", "tutorial", "guide", "instruction"],
            KnowledgeCategory.BEST_PRACTICE: ["best practice", "recommend", "should", "guideline"],
            KnowledgeCategory.TROUBLESHOOTING: ["troubleshoot", "debug", "error", "fix", "issue", "problem"],
            KnowledgeCategory.ALGORITHM: ["algorithm", "implementation", "code", "function", "class"],
            KnowledgeCategory.EXPLANATION: ["explanation", "how it works", "overview", "understanding"],
            KnowledgeCategory.CONCEPT: ["concept", "definition", "what is", "introduction"],
            KnowledgeCategory.WARNING: ["warning", "caution", "important", "note"],
            KnowledgeCategory.WORKFLOW: ["workflow", "pipeline", "process", "flow"],
        }

        for category, keywords in category_keywords.items():
            if any(kw in title_lower for kw in keywords):
                return category

        return KnowledgeCategory.OTHER

    def _extract_tags(self, content: str) -> List[str]:
        """Extract relevant tags from content."""
        tags = []
        content_lower = content.lower()

        tag_keywords = {
            "python": ["python", "py", "pip", "venv", "django", "flask", "fastapi"],
            "javascript": ["javascript", "js", "node", "npm", "react", "vue", "typescript", "ts"],
            "api": ["api", "rest", "graphql", "endpoint", "request", "response"],
            "database": ["database", "sql", "nosql", "postgres", "mysql", "mongodb", "redis"],
            "docker": ["docker", "container", "kubernetes", "k8s", "compose"],
            "git": ["git", "commit", "branch", "merge", "rebase", "pull request"],
            "testing": ["test", "testing", "pytest", "jest", "unit test", "integration test"],
            "security": ["security", "auth", "authentication", "authorization", "encryption", "ssl"],
            "performance": ["performance", "optimize", "speed", "latency", "throughput", "cache"],
            "debugging": ["debug", "error", "exception", "traceback", "log", "stack trace"],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in content_lower for kw in keywords):
                tags.append(tag)

        return tags

    def _deduplicate(self, objects: List[KnowledgeObject]) -> List[KnowledgeObject]:
        """Remove duplicate or very similar knowledge objects."""
        if not objects:
            return []

        unique = []
        seen_content = set()

        for obj in objects:
            # Create a signature for deduplication
            sig = f"{obj.category.value}:{obj.content[:100]}"
            if sig not in seen_content:
                seen_content.add(sig)
                unique.append(obj)

        return unique