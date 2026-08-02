"""Autonomous Research Loop

This module automatically researches and learns when knowledge gaps are detected.
It searches trusted sources, extracts information, validates it, and stores it
to fill identified knowledge gaps.
"""

import asyncio
import httpx
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from urllib.parse import quote_plus

from app.core.logger import logger
from app.memory.experience_memory import ExperienceMemory
from app.memory.engineering_lessons import EngineeringLessonStorage
from app.memory.long_term_memory import LongTermMemory
from app.memory.semantic_memory import SemanticMemory
from app.memory.validation import KnowledgeValidator
from app.knowledge_extraction.pipeline import KnowledgeExtractionPipeline
from app.knowledge_extraction.models import KnowledgeObject, KnowledgeCategory, SourceType
from app.autonomous_learning.models import (
    ResearchTask,
    ResearchSource,
    ResearchStatus,
    KnowledgeGap,
    AutonomousLearningConfig
)
from app.autonomous_learning.gap_detection import KnowledgeGapDetector
from app.software_engineering_knowledge.external_import import ExternalKnowledgeImporter, EXTERNAL_SOURCES


class AutonomousResearchLoop:
    """Performs autonomous research to fill knowledge gaps.

    Process:
    1. Take detected knowledge gaps
    2. Search trusted sources for information
    3. Extract knowledge from search results
    4. Validate extracted knowledge
    5. Store validated knowledge
    6. Mark gaps as resolved or update progress
    """

    def __init__(
        self,
        knowledge_extractor: KnowledgeExtractionPipeline,
        knowledge_validator: KnowledgeValidator,
        experience_memory: ExperienceMemory,
        engineering_lessons: EngineeringLessonStorage,
        long_term_memory: LongTermMemory,
        semantic_memory: SemanticMemory,
        gap_detector: Optional[KnowledgeGapDetector] = None,
        config: Optional[AutonomousLearningConfig] = None,
    ):
        """Initialize the autonomous research loop.

        Args:
            knowledge_extractor: Pipeline for extracting knowledge from sources
            knowledge_validator: Validates knowledge before storage
            experience_memory: Storage for experiences
            engineering_lessons: Storage for engineering lessons
            long_term_memory: Storage for long-term knowledge
            semantic_memory: Storage for semantic knowledge
            gap_detector: Detects knowledge gaps (optional, for direct gap retrieval)
            config: Research configuration
        """
        self.knowledge_extractor = knowledge_extractor
        self.knowledge_validator = knowledge_validator
        self.experience_memory = experience_memory
        self.engineering_lessons = engineering_lessons
        self.long_term_memory = long_term_memory
        self.semantic_memory = semantic_memory
        self.gap_detector = gap_detector
        self.config = config or AutonomousLearningConfig()

        # Initialize external importers
        self.external_importer = ExternalKnowledgeImporter()

        # Research state
        self._lock = asyncio.Lock()
        self._active_research: Dict[str, ResearchTask] = {}
        self._research_history: List[ResearchTask] = []

    def research_knowledge_gaps(self, gaps: Optional[List[KnowledgeGap]] = None) -> List[ResearchTask]:
        """Research knowledge to fill detected gaps.

        Args:
            gaps: Optional list of gaps to research (if None, gets from detector)

        Returns:
            List of ResearchTask objects representing research efforts
        """
        # Use asyncio.run for synchronous interface (can be called from sync code)
        return asyncio.run(self._research_knowledge_gaps_async(gaps))

    async def _research_knowledge_gaps_async(self, gaps: Optional[List[KnowledgeGap]] = None) -> List[ResearchTask]:
        """Async version of research knowledge gaps."""
        async with self._lock:
            try:
                logger.info("Starting autonomous research loop")

                # Get gaps to research
                if gaps is None:
                    if self.gap_detector:
                        gaps = self.gap_detector.detect_gaps()
                    else:
                        logger.warning("No gap detector provided and no gaps specified")
                        return []
                else:
                    # Use provided gaps
                    pass

                if not gaps:
                    logger.info("No knowledge gaps to research")
                    return []

                # Filter gaps that need research
                researchable_gaps = self._filter_researchable_gaps(gaps)

                if not researchable_gaps:
                    logger.info("No researchable gaps found")
                    return []

                # Limit concurrent research
                max_concurrent = self.config.max_concurrent_research
                gaps_to_research = researchable_gaps[:max_concurrent]

                # Create and start research tasks
                research_tasks = []
                for gap in gaps_to_research:
                    task = self._create_research_task(gap)
                    if task:
                        self._active_research[task.id] = task
                        research_tasks.append(task)

                # Execute research tasks asynchronously
                completed_tasks = []
                for task in research_tasks:
                    try:
                        completed_task = await self._execute_research_task_async(task)
                        completed_tasks.append(completed_task)
                        # Move to history
                        if task.id in self._active_research:
                            del self._active_research[task.id]
                        self._research_history.append(completed_task)
                    except Exception as e:
                        logger.error(f"Error executing research task {task.id}: {e}")
                        task.status = ResearchStatus.FAILED
                        task.error_message = str(e)
                        task.completed_at = datetime.now(timezone.utc)
                        completed_tasks.append(task)

                logger.info(f"Completed research on {len(completed_tasks)} gaps")
                return completed_tasks

            except Exception as e:
                logger.error(f"Error in autonomous research loop: {e}")
                return []

    def _filter_researchable_gaps(self, gaps: List[KnowledgeGap]) -> List[KnowledgeGap]:
        """Filter gaps that are suitable for autonomous research.

        Args:
            gaps: List of all detected gaps

        Returns:
            List of gaps suitable for research
        """
        researchable = []

        try:
            for gap in gaps:
                # Skip gaps that are already being researched or resolved
                if gap.status in [GapStatus.RESEARCHING, GapStatus.VALIDATING, GapStatus.RESOLVED]:
                    continue

                # Skip gaps with low confidence
                if gap.confidence < self.config.min_gap_confidence:
                    continue

                # Skip gaps that have exceeded max research attempts
                if gap.research_attempts >= gap.max_research_attempts:
                    gap.status = GapStatus.REJECTED
                    gap.resolution_notes = "Exceeded maximum research attempts"
                    continue

                # Check if we have trusted sources for this gap category
                if self._has_trusted_sources_for_gap(gap):
                    researchable.append(gap)

        except Exception as e:
            logger.error(f"Error filtering researchable gaps: {e}")

        return researchable

    def _has_trusted_sources_for_gap(self, gap: KnowledgeGap) -> bool:
        """Check if we have trusted sources suitable for researching this gap.

        Args:
            gap: The knowledge gap to check

        Returns:
            bool: True if we have suitable trusted sources
        """
        try:
            # If no trusted sources configured, we can't research
            if not self.config.trusted_sources:
                return False

            # Map gap categories to suitable source types
            category_source_mapping = {
                "framework": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.PACKAGE_DOCUMENTATION],
                "tool": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.PACKAGE_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY],
                "concept": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.STANDARDS_SPECIFICATIONS, ResearchSource.TECHNICAL_BLOG],
                "pattern": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY, ResearchSource.TECHNICAL_BLOG],
                "technology": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.VENDOR_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY],
                "documentation": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.STANDARDS_SPECIFICATIONS],
                "api": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.VENDOR_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY],
                "library": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.PACKAGE_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY],
                "failure_pattern": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY, ResearchSource.TECHNICAL_BLOG],
                "optimization": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY, ResearchSource.TECHNICAL_BLOG],
                "success_rate": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.STANDARDS_SPECIFICATIONS],
                "explicit_request": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.VENDOR_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY],
                "documentation_gap": [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.STANDARDS_SPECIFICATIONS],
            }

            suitable_sources = category_source_mapping.get(
                gap.category,
                [ResearchSource.OFFICIAL_DOCUMENTATION, ResearchSource.GITHUB_REPOSITORY]  # Default
            )

            # Check if any suitable sources are in our trusted sources
            trusted_source_set = set(self.config.trusted_sources)
            suitable_source_set = set(suitable_sources)

            return bool(trusted_source_set & suitable_source_set)

        except Exception as e:
            logger.error(f"Error checking trusted sources for gap: {e}")
            return False

    def _create_research_task(self, gap: KnowledgeGap) -> Optional[ResearchTask]:
        """Create a research task for a knowledge gap.

        Args:
            gap: The knowledge gap to research

        Returns:
            ResearchTask object or None if creation failed
        """
        try:
            # Generate search query from gap
            query = self._generate_search_query(gap)

            # Determine suitable sources
            target_sources = self._select_target_sources(gap)

            # Create research task
            task = ResearchTask(
                gap_id=gap.id,
                query=query,
                target_sources=target_sources,
                max_results_per_source=5,  # Reasonable limit
                language_hint="en",
                status=ResearchStatus.PENDING,
                metadata={
                    "gap_title": gap.title,
                    "gap_category": gap.category,
                    "gap_priority": gap.priority.value
                }
            )

            # Update gap status
            gap.status = GapStatus.RESEARCHING
            gap.research_task_id = task.id
            gap.research_attempts += 1
            gap.updated_at = datetime.now(timezone.utc)

            logger.debug(f"Created research task {task.id} for gap {gap.id}")
            return task

        except Exception as e:
            logger.error(f"Error creating research task for gap {gap.id}: {e}")
            return None

    def _generate_search_query(self, gap: KnowledgeGap) -> str:
        """Generate a search query from a knowledge gap.

        Args:
            gap: The knowledge gap to create a query for

        Returns:
            Search query string
        """
        try:
            query_parts = []

            # Start with the gap title/description
            if gap.title:
                query_parts.append(gap.title)

            # Add missing concepts
            if gap.missing_concepts:
                query_parts.extend(gap.missing_concepts[:3])  # Limit to top 3

            # Add missing tools
            if gap.missing_tools:
                query_parts.extend(gap.missing_tools[:3])

            # Add missing frameworks
            if gap.missing_frameworks:
                query_parts.extend(gap.missing_frameworks[:3])

            # Add context from related task types or goals
            if gap.related_task_types:
                query_parts.extend(gap.related_task_types[:2])

            # Join and clean up
            query = " ".join(query_parts)
            query = query.strip()

            # If query is too short, add some default terms
            if len(query) < 10:
                query = f"{gap.category} knowledge {gap.title}"

            return query

        except Exception as e:
            logger.error(f"Error generating search query for gap {gap.id}: {e}")
            return gap.title or f"{gap.category} knowledge"

    def _select_target_sources(self, gap: KnowledgeGap) -> List[ResearchSource]:
        """Select appropriate trusted sources for researching a gap.

        Args:
            gap: The knowledge gap to research

        Returns:
            List of ResearchSource objects to search
        """
        try:
            # Map gap categories to preferred source types
            category_source_preferences = {
                "framework": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.PACKAGE_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY
                ],
                "tool": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.PACKAGE_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY,
                    ResearchSource.VENDOR_DOCUMENTATION
                ],
                "concept": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.STANDARDS_SPECIFICATIONS,
                    ResearchSource.TECHNICAL_BLOG
                ],
                "pattern": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY,
                    ResearchSource.TECHNICAL_BLOG
                ],
                "technology": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.VENDOR_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY
                ],
                "documentation": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.STANDARDS_SPECIFICATIONS
                ],
                "api": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.VENDOR_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY
                ],
                "library": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.PACKAGE_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY
                ],
                # Default for other categories
                "default": [
                    ResearchSource.OFFICIAL_DOCUMENTATION,
                    ResearchSource.GITHUB_REPOSITORY,
                    ResearchSource.TECHNICAL_BLOG
                ]
            }

            # Get preferred sources for this gap category
            preferred_sources = category_source_preferences.get(
                gap.category,
                category_source_preferences["default"]
            )

            # Filter to only trusted sources
            trusted_sources = set(self.config.trusted_sources)
            selected_sources = [source for source in preferred_sources if source in trusted_sources]

            # If no preferred sources are trusted, fall back to any trusted sources
            if not selected_sources and trusted_sources:
                selected_sources = list(trusted_sources)[:3]  # Take first 3 trusted sources

            return selected_sources

        except Exception as e:
            logger.error(f"Error selecting target sources for gap {gap.id}: {e}")
            # Return first few trusted sources as fallback
            return self.config.trusted_sources[:3] if self.config.trusted_sources else []

    def _execute_research_task(self, task: ResearchTask) -> ResearchTask:
        """Execute a single research task.

        Args:
            task: The research task to execute

        Returns:
            Updated ResearchTask object
        """
        try:
            logger.info(f"Executing research task {task.id} for gap {task.gap_id}")
            task.status = ResearchStatus.SEARCHING
            task.started_at = datetime.now(timezone.utc)

            # Search trusted sources
            search_results = self._search_trusted_sources(task)
            task.search_results = search_results

            if not search_results:
                task.status = ResearchStatus.FAILED
                task.error_message = "No search results found"
                task.completed_at = datetime.now(timezone.utc)
                return task

            # Extract knowledge from search results
            task.status = ResearchStatus.EXTRACTING
            extracted_knowledge = self._extract_knowledge_from_results(search_results)
            task.extracted_knowledge = extracted_knowledge

            if not extracted_knowledge:
                task.status = ResearchStatus.FAILED
                task.error_message = "No knowledge could be extracted from search results"
                task.completed_at = datetime.now(timezone.utc)
                return task

            # Validate extracted knowledge
            task.status = ResearchStatus.VALIDATING
            validated_knowledge = self._validate_extracted_knowledge(extracted_knowledge)
            task.validated_knowledge = validated_knowledge

            if not validated_knowledge:
                task.status = ResearchStatus.FAILED
                task.error_message = "No extracted knowledge passed validation"
                task.completed_at = datetime.now(timezone.utc)
                return task

            # Store validated knowledge
            task.status = ResearchStatus.STORING
            stored_knowledge_ids = self._store_research_knowledge(validated_knowledge, task)
            task.stored_knowledge_ids = stored_knowledge_ids

            # Update gap with research results
            self._update_gap_with_results(task)

            # Mark task as completed
            task.status = ResearchStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc)

            logger.info(f"Research task {task.id} completed successfully")
            return task

        except Exception as e:
            logger.error(f"Error executing research task {task.id}: {e}")
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.now(timezone.utc)
            return task

    def _search_trusted_sources(self, task: ResearchTask) -> List[Dict[str, Any]]:
        """Search trusted sources for information.

        Args:
            task: The research task containing search parameters

        Returns:
            List of search result dictionaries
        """
        # Run async search synchronously
        return asyncio.run(self._search_trusted_sources_async(task))

    async def _search_trusted_sources_async(self, task: ResearchTask) -> List[Dict[str, Any]]:
        """Async version of search trusted sources."""
        search_results = []

        try:
            query = task.query
            logger.debug(f"Searching trusted sources for: {query}")

            # Search each trusted source
            for source in task.target_sources:
                # Map ResearchSource to search strategy
                if source == ResearchSource.OFFICIAL_DOCUMENTATION:
                    # Try official documentation sources
                    results = await self._search_official_docs(query)
                    search_results.extend(results)
                elif source == ResearchSource.GITHUB_REPOSITORY:
                    # Search GitHub repositories
                    results = await self._search_github(query)
                    search_results.extend(results)
                elif source == ResearchSource.STACKOVERFLOW:
                    # Search StackOverflow
                    results = await self._search_stackoverflow(query)
                    search_results.extend(results)
                elif source == ResearchSource.TECHNICAL_BLOG:
                    # Search technical blogs via general search
                    results = await self._search_general_web(query)
                    search_results.extend(results)
                elif source == ResearchSource.VENDOR_DOCUMENTATION:
                    # Search vendor documentation
                    results = await self._search_vendor_docs(query)
                    search_results.extend(results)
                elif source == ResearchSource.STANDARDS_SPECIFICATIONS:
                    # Search standards/specifications
                    results = await self._search_standards(query)
                    search_results.extend(results)
                elif source == ResearchSource.PACKAGE_DOCUMENTATION:
                    # Search package documentation
                    results = await self._search_package_docs(query)
                    search_results.extend(results)

                # Respect max results per source
                if len(search_results) >= task.max_results_per_source * len(task.target_sources):
                    break

        except Exception as e:
            logger.error(f"Error searching trusted sources: {e}")

        return search_results[:task.max_results_per_source * len(task.target_sources)]  # Limit results

    def _create_mock_search_results(self, query: str, source: ResearchSource) -> List[Dict[str, Any]]:
        """Create mock search results for demonstration purposes.

        In a real implementation, this would be replaced with actual API calls.

        Args:
            query: The search query
            source: The source to search

        Returns:
            List of mock search result dictionaries
        """
        # This is a placeholder - in reality, you would integrate with:
        # - Google Custom Search API
        # - GitHub API
        # - Stack Exchange API
        # - Documentation sites (readthedocs, etc.)
        # - Package registries (npm, pypi, etc.)
        # - Official vendor sites

        mock_results = []

        try:
            # Create 1-3 mock results per source
            num_results = min(3, max(1, len(query) // 10))  # Based on query length

            for i in range(num_results):
                result = {
                    "title": f"{query} - Result {i+1} from {source.value}",
                    "url": f"https://example.com/{source.value}/{quote_plus(query)}/{i+1}",
                    "snippet": f"This is a mock search result for '{query}' from {source.value}. "
                             f"It contains relevant information about the topic that could be used "
                             f"to fill knowledge gaps.",
                    "source": source.value,
                    "relevance_score": 0.8 - (i * 0.1),  # Decreasing relevance
                    "content": f"Mock content for {query} from {source.value}. "
                             f"This would contain detailed information, tutorials, documentation, "
                             f"or code examples related to the search query.",
                    "published_date": datetime.now(timezone.utc).isoformat(),
                    "author": f"Example Author from {source.value}"
                }
                mock_results.append(result)

        except Exception as e:
            logger.error(f"Error creating mock search results: {e}")

        return mock_results

    async def _search_official_docs(self, query: str) -> List[Dict[str, Any]]:
        """Search official documentation sources."""
        results = []

        # Use our external importer to search documentation sources
        try:
            # Try multiple documentation sources
            doc_sources = ["python_docs", "mdn", "rust_docs", "go_docs"]

            for source_name in doc_sources:
                if source_name in EXTERNAL_SOURCES:
                    # Use the external importer to search this source
                    importer = ExternalKnowledgeImporter()
                    try:
                        # For now, we'll fetch the search results and extract URLs
                        result = await importer.import_from_source(source_name, query, max_results=3)
                        if result.success and result.items:
                            # Convert knowledge items to search result format
                            for item in result.items:
                                results.append({
                                    "title": item.title,
                                    "url": item.source_uri,
                                    "snippet": item.summary,
                                    "source": source_name,
                                    "relevance_score": item.confidence,
                                    "content": item.content[:1000] + "..." if len(item.content) > 1000 else item.content
                                })
                    finally:
                        await importer.close()
        except Exception as e:
            logger.error(f"Error searching official docs: {e}")

        return results

    async def _search_github(self, query: str) -> List[Dict[str, Any]]:
        """Search GitHub repositories."""
        results = []

        try:
            # GitHub search API (public, no auth needed for basic search)
            url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&sort=stars&order=desc"

            # Use a simple HTTP client for this
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers={"Accept": "application/vnd.github.v3+json"})
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get("items", [])[:5]:  # Limit to top 5
                        results.append({
                            "title": item["full_name"],
                            "url": item["html_url"],
                            "snippet": item.get("description", ""),
                            "source": "github",
                            "relevance_score": min(item["stargazers_count"] / 1000.0, 1.0),  # Normalize stars
                            "content": f"Repository: {item['full_name']}\nDescription: {item.get('description', '')}\nLanguage: {item.get('language', 'Unknown')}\nStars: {item['stargazers_count']}"
                        })
        except Exception as e:
            logger.error(f"Error searching GitHub: {e}")

        return results

    async def _search_stackoverflow(self, query: str) -> List[Dict[str, Any]]:
        """Search StackOverflow questions."""
        results = []

        try:
            # StackExchange API
            url = f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q={quote_plus(query)}&site=stackoverflow&pagesize=5"

            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get("items", []):
                        results.append({
                            "title": item["title"],
                            "url": item["link"],
                            "snippet": item.get("excerpt", ""),
                            "source": "stackoverflow",
                            "relevance_score": min(item["score"] / 10.0, 1.0),  # Normalize score
                            "content": f"Question: {item['title']}\nTags: {', '.join([tag['name'] for tag in item.get('tags', [])])}\nScore: {item['score']}\nAnswers: {item.get('answer_count', 0)}"
                        })
        except Exception as e:
            logger.error(f"Error searching StackOverflow: {e}")

        return results

    async def _search_general_web(self, query: str) -> List[Dict[str, Any]]:
        """Search general web using DuckDuckGo."""
        results = []

        try:
            # DuckDuckGo HTML search
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if response.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Extract results
                    for result in soup.select('.result__body')[:5]:
                        title_elem = result.select_one('.result__title')
                        snippet_elem = result.select_one('.result__snippet')
                        link_elem = result.select_one('.result__url')

                        if title_elem and link_elem:
                            title = title_elem.get_text(strip=True)
                            url_elem = link_elem.get('href', '')
                            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                            results.append({
                                "title": title,
                                "url": url_elem,
                                "snippet": snippet,
                                "source": "duckduckgo",
                                "relevance_score": 0.7,  # Default relevance for web search
                                "content": f"Title: {title}\nSnippet: {snippet}\nURL: {url_elem}"
                            })
        except Exception as e:
            logger.error(f"Error searching general web: {e}")

        return results

    async def _search_vendor_docs(self, query: str) -> List[Dict[str, Any]]:
        """Search vendor documentation (AWS, Azure, GCP, etc.)."""
        results = []

        try:
            # Try major cloud provider documentation
            vendors = [
                ("aws", "https://docs.aws.amazon.com/"),
                ("azure", "https://learn.microsoft.com/en-us/azure/"),
                ("gcp", "https://cloud.google.com/docs/")
            ]

            for vendor, base_url in vendors:
                try:
                    # Try to search within the vendor docs (this is simplified)
                    search_url = f"{base_url}search/{quote_plus(query)}"
                    async with httpx.AsyncClient() as client:
                        response = await client.get(search_url, follow_redirects=True)
                        if response.status_code == 200 and len(response.text) > 1000:  # Basic validity check
                            results.append({
                                "title": f"{vendor.upper()} Documentation: {query}",
                                "url": str(response.url),
                                "snippet": f"Documentation from {vendor.upper()} about {query}",
                                "source": vendor,
                                "relevance_score": 0.8,
                                "content": f"Documentation from {vendor.upper()} regarding {query}. Content extracted from {response.url}"
                            })
                except:
                    continue  # Try next vendor
        except Exception as e:
            logger.error(f"Error searching vendor docs: {e}")

        return results

    async def _search_standards(self, query: str) -> List[Dict[str, Any]]:
        """Search standards and specifications (RFC, W3C, etc.)."""
        results = []

        try:
            # Try RFC search
            if "rfc" in query.lower() or "request for comments" in query.lower():
                # Extract potential RFC number
                import re
                rfc_match = re.search(r'rfc\s*(\d+)', query.lower())
                if rfc_match:
                    rfc_num = rfc_match.group(1)
                    url = f"https://www.rfc-editor.org/rfc/rfc{rfc_num}.txt"
                    results.append({
                        "title": f"RFC {rfc_num}",
                        "url": url,
                        "snippet": f"Request for Comments {rfc_num}",
                        "source": "rfc-editor",
                        "relevance_score": 0.9,
                        "content": f"RFC {rfc_num} document from RFC Editor"
                    })

            # Add more standards sources as needed
        except Exception as e:
            logger.error(f"Error searching standards: {e}")

        return results

    async def _search_package_docs(self, query: str) -> List[Dict[str, Any]]:
        """Search package documentation (PyPI, npm, crates.io, etc.)."""
        results = []

        try:
            # Try PyPI for Python packages
            url = f"https://pypi.org/pypi/{quote_plus(query)}/json"
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    info = data.get("info", {})
                    results.append({
                        "title": info.get("name", query),
                        "url": info.get("home_page", f"https://pypi.org/project/{query}/"),
                        "snippet": info.get("summary", ""),
                        "source": "pypi",
                        "relevance_score": 0.8,
                        "content": f"Package: {info.get('name')}\nVersion: {info.get('version')}\nSummary: {info.get('summary')}\nAuthor: {info.get('author')}\nLicense: {info.get('license')}"
                    })
        except Exception as e:
            logger.error(f"Error searching package docs: {e}")

        return results

    def _extract_knowledge_from_results(self, search_results: List[Dict[str, Any]]) -> List[KnowledgeObject]:
        """Extract knowledge objects from search results.

        Args:
            search_results: List of search result dictionaries

        Returns:
            List of KnowledgeObject instances
        """
        knowledge_objects = []

        try:
            for result in search_results:
                try:
                    # Convert search result to knowledge object
                    ko = KnowledgeObject(
                        title=result.get("title", "Unknown"),
                        summary=result.get("snippet", "")[:200],
                        content=result.get("content", ""),
                        source=result.get("url", ""),
                        source_type=self._map_source_to_source_type(result.get("source", "")),
                        category=self._infer_knowledge_category(result),
                        tags=[
                            f"source_{result.get('source', 'unknown')}",
                            "researched",
                            f"relevance_{int(result.get('relevance_score', 0.5) * 100)}"
                        ],
                        confidence=result.get("relevance_score", 0.5),
                        metadata={
                            "source_type": "research",
                            "original_search_result": result,
                            "extracted_at": datetime.now(timezone.utc).isoformat()
                        }
                    )
                    knowledge_objects.append(ko)

                except Exception as e:
                    logger.error(f"Error extracting knowledge from search result: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting knowledge from search results: {e}")

        return knowledge_objects

    def _map_source_to_source_type(self, source_str: str) -> SourceType:
        """Map source string to SourceType enum.

        Args:
            source_str: Source string from search result

        Returns:
            SourceType enum value
        """
        source_lower = source_str.lower()

        mapping = {
            "official_documentation": SourceType.DOCUMENTATION,
            "package_documentation": SourceType.DOCUMENTATION,
            "vendor_documentation": SourceType.DOCUMENTATION,
            "github_repository": SourceType.SOURCE_CODE,
            "technical_blog": SourceType.ARTICLE,
            "standards_specifications": SourceType.STANDARDS,
            "rfc_standard": SourceType.STANDARDS,
            "w3c_standard": SourceType.STANDARDS,
            "iso_standard": SourceType.STANDARDS,
            "academic_paper": SourceType.ARTICLE,
            "community_forum": SourceType.COMMUNITY
        }

        for key, source_type in mapping.items():
            if key in source_lower:
                return source_type

        return SourceType.UNKNOWN

    def _infer_knowledge_category(self, search_result: Dict[str, Any]) -> KnowledgeCategory:
        """Infer knowledge category from search result.

        Args:
            search_result: Search result dictionary

        Returns:
            KnowledgeCategory enum value
        """
        try:
            title = search_result.get("title", "").lower()
            snippet = search_result.get("snippet", "").lower()
            content = search_result.get("content", "").lower()
            source = search_result.get("source", "").lower()

            combined_text = f"{title} {snippet} {content} {source}"

            # Check for category indicators
            if any(word in combined_text for word in ["framework", "library", "sdk", "platform"]):
                return KnowledgeCategory.FRAMEWORK
            elif any(word in combined_text for word in ["tool", "utility", "program", "application"]):
                return KnowledgeCategory.TOOL
            elif any(word in combined_text for word in ["concept", "theory", "principle", "understanding"]):
                return KnowledgeCategory.CONCEPT
            elif any(word in combined_text for word in ["pattern", "best practice", "idiom"]):
                return KnowledgeCategory.BEST_PRACTICE
            elif any(word in combined_text for word in ["warning", "caution", "pitfall", "anti-pattern"]):
                return KnowledgeCategory.WARNING
            elif any(word in combined_text for word in ["recommendation", "suggestion", "advice"]):
                return KnowledgeCategory.RECOMMENDATION
            elif any(word in combined_text for word in ["decision", "choice", "selection"]):
                return KnowledgeCategory.DECISION
            elif any(word in combined_text for word in ["troubleshoot", "debug", "fix", "solution"]):
                return KnowledgeCategory.TROUBLESHOOTING
            elif any(word in combined_text for word in ["algorithm", "method", "procedure"]):
                return KnowledgeCategory.ALGORITHM
            elif any(word in combined_text for word in ["definition", "define", "meaning"]):
                return KnowledgeCategory.DEFINITION
            elif any(word in combined_text for word in ["example", "sample", "tutorial"]):
                return KnowledgeCategory.EXAMPLE
            elif any(word in combined_text for word in ["api", "endpoint", "interface"]):
                return KnowledgeCategory.API
            else:
                return KnowledgeCategory.OTHER

        except Exception as e:
            logger.error(f"Error inferring knowledge category: {e}")
            return KnowledgeCategory.OTHER

    def _validate_extracted_knowledge(self, extracted_knowledge: List[KnowledgeObject]) -> List[KnowledgeObject]:
        """Validate extracted knowledge using the knowledge validator.

        Args:
            extracted_knowledge: List of extracted KnowledgeObject instances

        Returns:
            List of validated KnowledgeObject instances
        """
        validated_knowledge = []

        try:
            for ko in extracted_knowledge:
                try:
                    # Convert KnowledgeObject to validation format
                    validation_sources = []

                    # Add source from the knowledge object
                    if ko.source:
                        source_type = self._map_source_to_source_type(ko.source)
                        validation_source = type('ValidationSource', (), {
                            'source_type': source_type,
                            'identifier': ko.source,
                            'content': ko.content[:500],
                            'confidence': ko.confidence
                        })()
                        validation_sources.append(validation_source)

                    # Validate the knowledge using the actual validator
                    # Create a temporary knowledge item for validation
                    from app.software_engineering_knowledge.models import EngineeringKnowledgeItem, ValidationStatus
                    temp_item = EngineeringKnowledgeItem(
                        title=ko.title,
                        summary=ko.summary,
                        content=ko.content,
                        domain=ko.category.value if hasattr(ko.category, 'value') else str(ko.category),
                        sub_category="research",
                        knowledge_type=ko.category.value if hasattr(ko.category, 'value') else str(ko.category),
                        source=KnowledgeSource.EXPERIENCE_MEMORY,  # Using experience memory as source for research
                        source_uri=ko.source or "",
                        source_metadata=ko.metadata,
                        tags=ko.tags,
                        confidence=ko.confidence
                    )

                    validation_result = self.knowledge_validator.validate(temp_item)

                    if validation_result.is_valid:
                        # Add validation metadata
                        ko.metadata["validation"] = {
                            "passed": True,
                            "confidence": validation_result.confidence,
                            "validated_at": datetime.now(timezone.utc).isoformat()
                        }
                        validated_knowledge.append(ko)
                    else:
                        logger.debug(f"Knowledge object {ko.id} failed validation: {validation_result.notes}")

                except Exception as e:
                    logger.error(f"Error validating knowledge object {ko.id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error validating extracted knowledge: {e}")

        return validated_knowledge

    def _store_research_knowledge(self, validated_knowledge: List[KnowledgeObject], task: ResearchTask) -> List[str]:
        """Store validated knowledge from research.

        Args:
            validated_knowledge: List of validated KnowledgeObject instances
            task: The research task that produced this knowledge

        Returns:
            List of stored knowledge IDs
        """
        stored_ids = []

        try:
            for ko in validated_knowledge:
                try:
                    # Store as engineering lesson (high confidence research)
                    lesson = self.engineering_lessons.store(
                        title=ko.title,
                        description=ko.summary,
                        lesson_type="best_practice" if ko.confidence > 0.8 else "recommendation",
                        category=ko.metadata.get("source_type", "researched"),
                        tags=ko.tags + ["researched", "auto_stored"],
                        confidence=ko.confidence,
                        rationale=ko.content,
                        metadata=ko.metadata
                    )

                    if lesson:
                        stored_ids.append(lesson.id)

                        # Record knowledge storage from research
                        # In a full implementation, would use learning event system

                except Exception as e:
                    logger.error(f"Error storing researched knowledge object {ko.id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error storing research knowledge: {e}")

        return stored_ids

    def _update_gap_with_results(self, task: ResearchTask) -> None:
        """Update the knowledge gap with research results.

        Args:
            task: The completed research task
        """
        try:
            # Find the gap (would normally come from gap detector or storage)
            # For now, we'll simulate updating gap status
            logger.info(f"Research task {task.id} completed with {len(task.stored_knowledge_ids)} knowledge items stored")

            # In a full implementation, would:
            # 1. Retrieve the gap from gap detector or storage
            # 2. Update gap status to RESOLVED if sufficient knowledge was stored
            # 3. Add resolution notes and knowledge items created
            # 4. Update gap metadata

            # Simulate gap update
            if task.stored_knowledge_ids:
                logger.info(f"Gap {task.gap_id} would be marked as resolved with {len(task.stored_knowledge_ids)} new knowledge items")

        except Exception as e:
            logger.error(f"Error updating gap with research results: {e}")

    def get_research_statistics(self) -> Dict[str, Any]:
        """Get statistics about research activities.

        Returns:
            Dictionary containing research statistics
        """
        try:
            with self._lock:
                active_count = len(self._active_research)
                history_count = len(self._research_history)

                # Count by status
                status_counts = {}
                for task in self._research_history:
                    status = task.status.value
                    status_counts[status] = status_counts.get(status, 0) + 1

                return {
                    "active_research_tasks": active_count,
                    "completed_research_tasks": history_count,
                    "research_by_status": status_counts,
                    "total_researched": active_count + history_count
                }

        except Exception as e:
            logger.error(f"Error getting research statistics: {e}")
            return {"error": str(e)}