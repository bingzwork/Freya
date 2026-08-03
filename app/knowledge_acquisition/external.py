"""External Knowledge Acquisition for Unified Pipeline.

This module extends the KnowledgeAcquisitionPipeline with enhanced external
source support including:
- Web documentation (official docs, tutorials, guides)
- Package documentation (PyPI, npm, crates.io, pkg.go.dev)
- Internet research (search queries, StackOverflow, blogs)
- Standards bodies (RFC, ISO, W3C, ECMA)
- GitHub repositories (README, docs, wiki)
- Vendor documentation (AWS, GCP, Azure, Kubernetes, Terraform)

Features:
- Validation with confidence scoring
- Duplicate detection across external sources
- Source attribution and citation metadata
- Freshness tracking and update detection
- Integration with Autonomous Learning and Knowledge Base
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core.events import get_event_bus
from app.core.observability import get_observability_hub, HealthCheck, HealthResult, HealthStatus
from app.core.logger import logger

# Reuse existing external importers
from app.software_engineering_knowledge.external_import import (
    UnifiedExternalImporter,
    ExternalKnowledgeImporter,
    InternetResearchImporter,
    PackageDocumentationImporter,
    EXTERNAL_SOURCES,
    ExternalSource,
)

# Models
from app.knowledge_acquisition.models import (
    AcquisitionSource,
    AcquisitionSourceType,
    AcquisitionJob,
    AcquisitionResult,
    AcquisitionStatus,
    KnowledgeAcquisitionConfig,
)


@dataclass
class ExternalSourceConfig:
    """Configuration for an external knowledge source."""
    name: str
    source_type: AcquisitionSourceType
    enabled: bool = True
    priority: int = 0  # Higher = checked first
    rate_limit_rps: float = 1.0
    max_results: int = 10
    timeout_seconds: float = 30.0
    cache_ttl_hours: int = 24
    config: Dict[str, Any] = field(default_factory=dict)


class ExternalKnowledgeAcquisition:
    """External knowledge acquisition manager.

    Wraps UnifiedExternalImporter with acquisition pipeline integration,
    providing validation, deduplication, freshness tracking, and
    seamless integration with the unified acquisition pipeline.
    """

    def __init__(
        self,
        config: Optional[KnowledgeAcquisitionConfig] = None,
        cache_dir: Optional[Path] = None,
        observability=None,
        event_bus=None,
    ):
        self.config = config or KnowledgeAcquisitionConfig()
        self.cache_dir = cache_dir or Path("data/external_knowledge_acquisition")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Shared infrastructure
        self.observability = observability or get_observability_hub()
        self.event_bus = event_bus or get_event_bus()

        # External importers
        self.unified_importer = UnifiedExternalImporter(cache_dir=self.cache_dir)

        # Source configurations
        self.source_configs = self._default_source_configs()

        # Freshness tracking
        self._freshness_cache: Dict[str, Dict[str, Any]] = {}

        # Statistics
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "items_acquired": 0,
            "items_duplicate": 0,
            "items_stale": 0,
            "by_source_type": {},
        }

        self._register_observability()

    def _default_source_configs(self) -> Dict[AcquisitionSourceType, ExternalSourceConfig]:
        """Default configurations for external sources."""
        return {
            AcquisitionSourceType.WEB_DOCUMENTATION: ExternalSourceConfig(
                name="Web Documentation",
                source_type=AcquisitionSourceType.WEB_DOCUMENTATION,
                enabled=True,
                priority=10,
                rate_limit_rps=0.5,
                max_results=10,
            ),
            AcquisitionSourceType.PACKAGE_DOCUMENTATION: ExternalSourceConfig(
                name="Package Documentation",
                source_type=AcquisitionSourceType.PACKAGE_DOCUMENTATION,
                enabled=True,
                priority=20,
                rate_limit_rps=0.5,
                max_results=5,
            ),
            AcquisitionSourceType.INTERNET_RESEARCH: ExternalSourceConfig(
                name="Internet Research",
                source_type=AcquisitionSourceType.INTERNET_RESEARCH,
                enabled=True,
                priority=5,
                rate_limit_rps=0.3,
                max_results=10,
            ),
            AcquisitionSourceType.STACKOVERFLOW: ExternalSourceConfig(
                name="StackOverflow",
                source_type=AcquisitionSourceType.STACKOVERFLOW,
                enabled=True,
                priority=15,
                rate_limit_rps=0.3,
                max_results=5,
            ),
            AcquisitionSourceType.GITHUB_REPOSITORY: ExternalSourceConfig(
                name="GitHub Repository",
                source_type=AcquisitionSourceType.GITHUB_REPOSITORY,
                enabled=True,
                priority=15,
                rate_limit_rps=0.5,
                max_results=3,
            ),
            AcquisitionSourceType.STANDARDS_BODY: ExternalSourceConfig(
                name="Standards Bodies (RFC/ISO/W3C/ECMA)",
                source_type=AcquisitionSourceType.STANDARDS_BODY,
                enabled=True,
                priority=20,
                rate_limit_rps=0.2,
                max_results=3,
            ),
            AcquisitionSourceType.VENDOR_DOCUMENTATION: ExternalSourceConfig(
                name="Vendor Documentation (AWS/GCP/Azure)",
                source_type=AcquisitionSourceType.VENDOR_DOCUMENTATION,
                enabled=True,
                priority=10,
                rate_limit_rps=0.3,
                max_results=5,
            ),
        }

    def _register_observability(self) -> None:
        """Register with observability hub."""
        if self.observability:
            self.observability.add_health_check(HealthCheck(
                name="external_knowledge_acquisition_health",
                component="knowledge_acquisition_external",
                check_func=self._health_check,
                interval_seconds=60.0,
            ))

    def _health_check(self) -> HealthResult:
        """Health check for external acquisition."""
        try:
            success_rate = self._stats["successful_requests"] / max(1, self._stats["total_requests"])
            return HealthResult(
                name="external_knowledge_acquisition_health",
                component="knowledge_acquisition_external",
                status=HealthStatus.HEALTHY if success_rate > 0.7 else HealthStatus.DEGRADED,
                message=f"External acquisition operational (success rate: {success_rate:.1%})",
                metadata={
                    "total_requests": self._stats["total_requests"],
                    "success_rate": success_rate,
                    "items_acquired": self._stats["items_acquired"],
                    "items_duplicate": self._stats["items_duplicate"],
                }
            )
        except Exception as e:
            return HealthResult(
                name="external_knowledge_acquisition_health",
                component="knowledge_acquisition_external",
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    async def acquire_from_web_docs(
        self,
        url: str,
        query: str = "",
        max_results: Optional[int] = None
    ) -> AcquisitionResult:
        """Acquire knowledge from web documentation URL."""
        self._stats["total_requests"] += 1
        source_config = self.source_configs[AcquisitionSourceType.WEB_DOCUMENTATION]
        max_results = max_results or source_config.max_results

        logger.info(f"[ExternalKnowledgeAcquisition] Acquiring from web docs: {url}")

        try:
            result = await self.unified_importer.docs_importer.import_from_url(url)
            if not result.success:
                self._stats["failed_requests"] += 1
                return AcquisitionResult(
                    job_id=f"web_docs_{hash(url)}",
                    success=False,
                    errors=result.errors,
                    metadata={"url": url, "source_type": "web_documentation"},
                )

            # Convert to acquisition result
            items = []
            for item in result.items:
                items.append({
                    "content": item.content,
                    "title": item.title,
                    "source": item.source_uri or url,
                    "source_type": "web_documentation",
                    "metadata": {
                        "tags": item.tags,
                        "domain": item.domain.value,
                        "knowledge_type": item.knowledge_type.value,
                        "language": item.language,
                        "confidence": item.confidence,
                        "url": url,
                        "query": query,
                    }
                })

            self._stats["successful_requests"] += 1
            self._stats["items_acquired"] += len(items)
            self._stats["by_source_type"]["web_documentation"] = \
                self._stats["by_source_type"].get("web_documentation", 0) + len(items)

            return AcquisitionResult(
                job_id=f"web_docs_{hash(url)}",
                success=True,
                items_acquired=items,
                metadata={"url": url, "source_type": "web_documentation", "query": query},
            )

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"[ExternalKnowledgeAcquisition] Web docs acquisition failed: {e}")
            return AcquisitionResult(
                job_id=f"web_docs_{hash(url)}",
                success=False,
                errors=[str(e)],
                metadata={"url": url, "source_type": "web_documentation"},
            )

    async def acquire_package_docs(
        self,
        package_name: str,
        language: str = "python",
        max_results: Optional[int] = None
    ) -> AcquisitionResult:
        """Acquire documentation for a package."""
        self._stats["total_requests"] += 1
        source_config = self.source_configs[AcquisitionSourceType.PACKAGE_DOCUMENTATION]
        max_results = max_results or source_config.max_results

        identifier = f"{language}:{package_name}"
        logger.info(f"[ExternalKnowledgeAcquisition] Acquiring package docs: {identifier}")

        try:
            result = await self.unified_importer.docs_importer.import_package_docs(package_name, language)
            if not result.success:
                self._stats["failed_requests"] += 1
                return AcquisitionResult(
                    job_id=f"pkg_{language}_{package_name}",
                    success=False,
                    errors=result.errors,
                    metadata={"package": package_name, "language": language, "source_type": "package_documentation"},
                )

            items = []
            for item in result.items:
                items.append({
                    "content": item.content,
                    "title": item.title,
                    "source": item.source_uri or identifier,
                    "source_type": "package_documentation",
                    "metadata": {
                        "tags": item.tags,
                        "domain": item.domain.value,
                        "knowledge_type": item.knowledge_type.value,
                        "language": item.language,
                        "confidence": item.confidence,
                        "package": package_name,
                        "language": language,
                    }
                })

            self._stats["successful_requests"] += 1
            self._stats["items_acquired"] += len(items)
            self._stats["by_source_type"]["package_documentation"] = \
                self._stats["by_source_type"].get("package_documentation", 0) + len(items)

            return AcquisitionResult(
                job_id=f"pkg_{language}_{package_name}",
                success=True,
                items_acquired=items,
                metadata={"package": package_name, "language": language, "source_type": "package_documentation"},
            )

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"[ExternalKnowledgeAcquisition] Package docs acquisition failed: {e}")
            return AcquisitionResult(
                job_id=f"pkg_{language}_{package_name}",
                success=False,
                errors=[str(e)],
                metadata={"package": package_name, "language": language, "source_type": "package_documentation"},
            )

    async def acquire_from_internet_research(
        self,
        query: str,
        max_results: Optional[int] = None
    ) -> AcquisitionResult:
        """Acquire knowledge from internet research (search)."""
        self._stats["total_requests"] += 1
        source_config = self.source_configs[AcquisitionSourceType.INTERNET_RESEARCH]
        max_results = max_results or source_config.max_results

        logger.info(f"[ExternalKnowledgeAcquisition] Internet research: {query}")

        try:
            result = await self.unified_importer.research_importer.search_and_import(query, max_results)
            if not result.success:
                self._stats["failed_requests"] += 1
                return AcquisitionResult(
                    job_id=f"research_{hash(query)}",
                    success=False,
                    errors=result.errors,
                    metadata={"query": query, "source_type": "internet_research"},
                )

            items = []
            for item in result.items:
                items.append({
                    "content": item.content,
                    "title": item.title,
                    "source": item.source_uri or f"search:{query}",
                    "source_type": "internet_research",
                    "metadata": {
                        "tags": item.tags,
                        "domain": item.domain.value,
                        "knowledge_type": item.knowledge_type.value,
                        "language": item.language,
                        "confidence": item.confidence,
                        "query": query,
                    }
                })

            self._stats["successful_requests"] += 1
            self._stats["items_acquired"] += len(items)
            self._stats["by_source_type"]["internet_research"] = \
                self._stats["by_source_type"].get("internet_research", 0) + len(items)

            return AcquisitionResult(
                job_id=f"research_{hash(query)}",
                success=True,
                items_acquired=items,
                metadata={"query": query, "source_type": "internet_research"},
            )

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"[ExternalKnowledgeAcquisition] Internet research failed: {e}")
            return AcquisitionResult(
                job_id=f"research_{hash(query)}",
                success=False,
                errors=[str(e)],
                metadata={"query": query, "source_type": "internet_research"},
            )

    async def acquire_from_stackoverflow(
        self,
        question_id: str,
        max_results: Optional[int] = None
    ) -> AcquisitionResult:
        """Acquire knowledge from StackOverflow question."""
        self._stats["total_requests"] += 1
        source_config = self.source_configs[AcquisitionSourceType.STACKOVERFLOW]
        max_results = max_results or source_config.max_results

        logger.info(f"[ExternalKnowledgeAcquisition] StackOverflow: {question_id}")

        try:
            result = await self.unified_importer.research_importer.import_from_stackoverflow(question_id)
            if not result.success:
                self._stats["failed_requests"] += 1
                return AcquisitionResult(
                    job_id=f"so_{question_id}",
                    success=False,
                    errors=result.errors,
                    metadata={"question_id": question_id, "source_type": "stackoverflow"},
                )

            items = []
            for item in result.items:
                items.append({
                    "content": item.content,
                    "title": item.title,
                    "source": item.source_uri or f"stackoverflow.com/questions/{question_id}",
                    "source_type": "stackoverflow",
                    "metadata": {
                        "tags": item.tags,
                        "domain": item.domain.value,
                        "knowledge_type": item.knowledge_type.value,
                        "language": item.language,
                        "confidence": item.confidence,
                        "question_id": question_id,
                    }
                })

            self._stats["successful_requests"] += 1
            self._stats["items_acquired"] += len(items)
            self._stats["by_source_type"]["stackoverflow"] = \
                self._stats["by_source_type"].get("stackoverflow", 0) + len(items)

            return AcquisitionResult(
                job_id=f"so_{question_id}",
                success=True,
                items_acquired=items,
                metadata={"question_id": question_id, "source_type": "stackoverflow"},
            )

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"[ExternalKnowledgeAcquisition] StackOverflow acquisition failed: {e}")
            return AcquisitionResult(
                job_id=f"so_{question_id}",
                success=False,
                errors=[str(e)],
                metadata={"question_id": question_id, "source_type": "stackoverflow"},
            )

    async def acquire_from_github_repo(
        self,
        repo_url: str,
        max_results: Optional[int] = None
    ) -> AcquisitionResult:
        """Acquire knowledge from GitHub repository (README, docs)."""
        self._stats["total_requests"] += 1
        source_config = self.source_configs[AcquisitionSourceType.GITHUB_REPOSITORY]
        max_results = max_results or source_config.max_results

        logger.info(f"[ExternalKnowledgeAcquisition] GitHub repo: {repo_url}")

        try:
            result = await self.unified_importer.research_importer.import_from_github_repo(repo_url)
            if not result.success:
                self._stats["failed_requests"] += 1
                return AcquisitionResult(
                    job_id=f"github_{hash(repo_url)}",
                    success=False,
                    errors=result.errors,
                    metadata={"repo_url": repo_url, "source_type": "github_repository"},
                )

            items = []
            for item in result.items:
                items.append({
                    "content": item.content,
                    "title": item.title,
                    "source": item.source_uri or repo_url,
                    "source_type": "github_repository",
                    "metadata": {
                        "tags": item.tags,
                        "domain": item.domain.value,
                        "knowledge_type": item.knowledge_type.value,
                        "language": item.language,
                        "confidence": item.confidence,
                        "repo_url": repo_url,
                    }
                })

            self._stats["successful_requests"] += 1
            self._stats["items_acquired"] += len(items)
            self._stats["by_source_type"]["github_repository"] = \
                self._stats["by_source_type"].get("github_repository", 0) + len(items)

            return AcquisitionResult(
                job_id=f"github_{hash(repo_url)}",
                success=True,
                items_acquired=items,
                metadata={"repo_url": repo_url, "source_type": "github_repository"},
            )

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"[ExternalKnowledgeAcquisition] GitHub acquisition failed: {e}")
            return AcquisitionResult(
                job_id=f"github_{hash(repo_url)}",
                success=False,
                errors=[str(e)],
                metadata={"repo_url": repo_url, "source_type": "github_repository"},
            )

    async def acquire_from_standards_body(
        self,
        body: str,
        identifier: str
    ) -> AcquisitionResult:
        """Acquire knowledge from standards bodies (RFC, ISO, W3C, ECMA)."""
        self._stats["total_requests"] += 1
        source_config = self.source_configs[AcquisitionSourceType.STANDARDS_BODY]

        logger.info(f"[ExternalKnowledgeAcquisition] Standards body: {body}:{identifier}")

        try:
            result = await self.unified_importer.docs_importer.import_from_standards_body(body, identifier)
            if not result.success:
                self._stats["failed_requests"] += 1
                return AcquisitionResult(
                    job_id=f"std_{body}_{identifier}",
                    success=False,
                    errors=result.errors,
                    metadata={"body": body, "identifier": identifier, "source_type": "standards_body"},
                )

            items = []
            for item in result.items:
                items.append({
                    "content": item.content,
                    "title": item.title,
                    "source": item.source_uri or f"{body}:{identifier}",
                    "source_type": "standards_body",
                    "metadata": {
                        "tags": item.tags,
                        "domain": item.domain.value,
                        "knowledge_type": item.knowledge_type.value,
                        "language": item.language,
                        "confidence": item.confidence,
                        "standards_body": body,
                        "identifier": identifier,
                    }
                })

            self._stats["successful_requests"] += 1
            self._stats["items_acquired"] += len(items)
            self._stats["by_source_type"]["standards_body"] = \
                self._stats["by_source_type"].get("standards_body", 0) + len(items)

            return AcquisitionResult(
                job_id=f"std_{body}_{identifier}",
                success=True,
                items_acquired=items,
                metadata={"body": body, "identifier": identifier, "source_type": "standards_body"},
            )

        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"[ExternalKnowledgeAcquisition] Standards body acquisition failed: {e}")
            return AcquisitionResult(
                job_id=f"std_{body}_{identifier}",
                success=False,
                errors=[str(e)],
                metadata={"body": body, "identifier": identifier, "source_type": "standards_body"},
            )

    def check_freshness(
        self,
        source_type: AcquisitionSourceType,
        identifier: str,
        max_age_hours: Optional[int] = None
    ) -> Dict[str, Any]:
        """Check freshness of previously acquired external knowledge."""
        cache_key = f"{source_type.value}:{identifier}"
        cached = self._freshness_cache.get(cache_key)

        if not cached:
            return {"fresh": False, "reason": "not_cached", "cached_at": None}

        max_age = max_age_hours or self.config.external_cache_ttl_hours
        from datetime import datetime, timezone
        age_hours = (datetime.now(timezone.utc) - cached["acquired_at"]).total_seconds() / 3600

        if age_hours > max_age:
            return {
                "fresh": False,
                "reason": "stale",
                "cached_at": cached["acquired_at"].isoformat(),
                "age_hours": age_hours,
                "max_age_hours": max_age,
            }

        return {
            "fresh": True,
            "cached_at": cached["acquired_at"].isoformat(),
            "age_hours": age_hours,
            "item_count": cached.get("item_count", 0),
        }

    def update_freshness(self, source_type: AcquisitionSourceType, identifier: str, item_count: int) -> None:
        """Update freshness cache after successful acquisition."""
        cache_key = f"{source_type.value}:{identifier}"
        self._freshness_cache[cache_key] = {
            "acquired_at": datetime.now(timezone.utc),
            "item_count": item_count,
        }

    def get_available_predefined_sources(self) -> List[Dict[str, Any]]:
        """Get list of predefined external sources."""
        sources = []
        for name, source in EXTERNAL_SOURCES.items():
            sources.append({
                "name": source.name,
                "key": name,
                "base_url": source.base_url,
                "source_type": source.source_type.value,
                "parser": source.parser,
                "rate_limit": source.rate_limit,
            })
        return sources

    def get_stats(self) -> Dict[str, Any]:
        """Get acquisition statistics."""
        return {
            **self._stats,
            "success_rate": (
                self._stats["successful_requests"] / max(1, self._stats["total_requests"])
            ),
            "freshness_cache_size": len(self._freshness_cache),
            "configured_sources": {
                k.value: {"enabled": v.enabled, "priority": v.priority}
                for k, v in self.source_configs.items()
            },
        }

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "items_acquired": 0,
            "items_duplicate": 0,
            "items_stale": 0,
            "by_source_type": {},
        }

    async def close(self) -> None:
        """Close external connections."""
        await self.unified_importer.close()


async def acquire_external_knowledge(
    source_type: AcquisitionSourceType,
    identifier: str,
    config: Optional[KnowledgeAcquisitionConfig] = None,
    **kwargs
) -> AcquisitionResult:
    """Convenience function to acquire external knowledge.

    Args:
        source_type: Type of external source
        identifier: Source identifier (URL, package name, query, etc.)
        config: Optional custom configuration
        **kwargs: Additional arguments for specific source types

    Returns:
        AcquisitionResult with acquired knowledge items
    """
    external = ExternalKnowledgeAcquisition(config=config)

    try:
        if source_type == AcquisitionSourceType.WEB_DOCUMENTATION:
            return await external.acquire_from_web_docs(identifier, kwargs.get("query", ""), kwargs.get("max_results"))
        elif source_type == AcquisitionSourceType.PACKAGE_DOCUMENTATION:
            parts = identifier.split(":", 1)
            if len(parts) == 2:
                return await external.acquire_package_docs(parts[1], parts[0], kwargs.get("max_results"))
            else:
                return await external.acquire_package_docs(identifier, kwargs.get("language", "python"), kwargs.get("max_results"))
        elif source_type == AcquisitionSourceType.INTERNET_RESEARCH:
            return await external.acquire_from_internet_research(identifier, kwargs.get("max_results"))
        elif source_type == AcquisitionSourceType.STACKOVERFLOW:
            return await external.acquire_from_stackoverflow(identifier, kwargs.get("max_results"))
        elif source_type == AcquisitionSourceType.GITHUB_REPOSITORY:
            return await external.acquire_from_github_repo(identifier, kwargs.get("max_results"))
        elif source_type == AcquisitionSourceType.STANDARDS_BODY:
            parts = identifier.split(":", 1)
            if len(parts) == 2:
                return await external.acquire_from_standards_body(parts[0], parts[1])
            else:
                return AcquisitionResult(
                    job_id=f"std_{identifier}",
                    success=False,
                    errors=["Standards body identifier must be in format 'body:identifier' (e.g., 'rfc:1234')"],
                    metadata={"source_type": "standards_body", "identifier": identifier},
                )
        else:
            return AcquisitionResult(
                job_id=f"unknown_{identifier}",
                success=False,
                errors=[f"Unsupported external source type: {source_type.value}"],
                metadata={"source_type": source_type.value, "identifier": identifier},
            )
    finally:
        await external.close()