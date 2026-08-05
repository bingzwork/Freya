"""Tests for ExternalServiceRegistry."""

import os
import tempfile
from pathlib import Path

import pytest

from app.services.external_registry import (
    ExternalServiceRegistry,
    ServiceMetadata,
    ServiceType,
    ServiceProvider,
    ServiceHealth,
    ServiceCapability,
)
from app.monitoring.network_monitor import NetworkMonitor, CheckType, ServiceStatus


class TestExternalServiceRegistry:
    """Test ExternalServiceRegistry functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.registry = ExternalServiceRegistry()
        self.network_monitor = NetworkMonitor(workspace=".")

    def teardown_method(self):
        """Clean up test fixtures."""
        pass

    def test_auto_discover_ollama(self):
        """Test Ollama auto-discovery."""
        # Ensure clean state
        os.environ.pop("OLLAMA_HOST", None)
        os.environ.pop("OLLAMA_BASE_URL", None)

        discovered = self.registry.discover_ollama()
        assert len(discovered) >= 1
        assert discovered[0].service_type == ServiceType.OLLAMA
        assert discovered[0].provider == ServiceProvider.OLLAMA
        assert discovered[0].display_name == "Ollama (Local)"
        assert discovered[0].is_default is True

    def test_auto_discover_openai(self):
        """Test OpenAI auto-discovery."""
        # Without API key, should return empty
        os.environ.pop("OPENAI_API_KEY", None)
        discovered = self.registry.discover_openai()
        assert len(discovered) == 0

        # With API key
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            discovered = self.registry.discover_openai()
            assert len(discovered) == 1
            assert discovered[0].service_type == ServiceType.OPENAI
            assert discovered[0].provider == ServiceProvider.OPENAI
            assert discovered[0].credentials.bearer_token == "test-key"
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    def test_auto_discover_anthropic(self):
        """Test Anthropic auto-discovery."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        discovered = self.registry.discover_anthropic()
        assert len(discovered) == 0

        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        try:
            discovered = self.registry.discover_anthropic()
            assert len(discovered) == 1
            assert discovered[0].service_type == ServiceType.ANTHROPIC
            assert discovered[0].provider == ServiceProvider.ANTHROPIC
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_auto_discover_github(self):
        """Test GitHub auto-discovery."""
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GITHUB_PAT", None)
        discovered = self.registry.discover_github()
        assert len(discovered) == 0

        os.environ["GITHUB_TOKEN"] = "test-token"
        try:
            discovered = self.registry.discover_github()
            assert len(discovered) == 1
            assert discovered[0].service_type == ServiceType.GITHUB
            assert discovered[0].provider == ServiceProvider.GITHUB
        finally:
            os.environ.pop("GITHUB_TOKEN", None)

    def test_auto_discover_redis(self):
        """Test Redis auto-discovery."""
        os.environ.pop("REDIS_URL", None)
        os.environ.pop("REDIS_HOST", None)
        discovered = self.registry.discover_redis()
        assert len(discovered) == 0

        os.environ["REDIS_URL"] = "redis://localhost:6379/0"
        try:
            discovered = self.registry.discover_redis()
            assert len(discovered) == 1
            assert discovered[0].service_type == ServiceType.CACHE
            assert discovered[0].provider == ServiceProvider.REDIS
        finally:
            os.environ.pop("REDIS_URL", None)

    def test_auto_discover_and_register(self):
        """Test auto-discover and register all services."""
        # Clean environment
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "REDIS_URL"]:
            os.environ.pop(key, None)

        discovered = self.registry.auto_discover_and_register()
        # Should at least discover local Ollama
        assert len(discovered) >= 1
        ollama_services = [s for s in discovered if s.service_type == ServiceType.OLLAMA]
        assert len(ollama_services) >= 1

    def test_duplicate_prevention(self):
        """Test that duplicate services are not registered."""
        # Clean environment
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "REDIS_URL"]:
            os.environ.pop(key, None)

        # First discovery
        self.registry.auto_discover_and_register()
        count1 = len(self.registry.list())

        # Second discovery - should not add duplicates
        self.registry.auto_discover_and_register()
        count2 = len(self.registry.list())

        assert count1 == count2

    def test_register_default_services(self):
        """Test registering default services."""
        registry = ExternalServiceRegistry()
        defaults = registry.register_default_services()
        # Should register Ollama if running, or at least attempt
        # Note: This might be empty if Ollama isn't running, which is fine
        assert isinstance(defaults, list)

    def test_crud_operations(self):
        """Test basic CRUD operations."""
        service = ServiceMetadata(
            display_name="Test Service",
            service_type=ServiceType.CUSTOM,
            provider=ServiceProvider.UNKNOWN,
            endpoint=None,
        )
        service_id = service.service_id

        # Register
        self.registry.register(service)
        assert self.registry.get(service_id) is not None

        # List
        services = self.registry.list()
        assert len(services) == 1

        # Update health
        result = self.registry.update_health(service_id, ServiceHealth.HEALTHY)
        assert result is True
        assert self.registry.get(service_id).health == ServiceHealth.HEALTHY

        # Update latency
        result = self.registry.update_latency(service_id, 100.0)
        assert result is True
        assert self.registry.get(service_id).metrics.avg_latency_ms > 0

        # Query by capability
        service_with_cap = ServiceMetadata(
            display_name="Test with Cap",
            service_type=ServiceType.CUSTOM,
            provider=ServiceProvider.UNKNOWN,
            capabilities={ServiceCapability.TEXT_GENERATION},
        )
        self.registry.register(service_with_cap)
        results = self.registry.query_by_capability(ServiceCapability.TEXT_GENERATION)
        assert len(results) == 1
        assert results[0].service_id == service_with_cap.service_id

        # Unregister
        result = self.registry.unregister(service_id)
        assert result is True
        assert self.registry.get(service_id) is None

        # Unregister non-existent
        result = self.registry.unregister("non-existent")
        assert result is False

    def test_persistence(self):
        """Test save/load from file."""
        service = ServiceMetadata(
            display_name="Persist Test",
            service_type=ServiceType.CUSTOM,
            provider=ServiceProvider.UNKNOWN,
        )
        self.registry.register(service)
        service_id = service.service_id

        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            # Save
            result = self.registry.save_to_file(str(registry_path))
            assert result is True
            assert registry_path.exists()

            # Load into new registry
            new_registry = ExternalServiceRegistry()
            count = new_registry.load_from_file(str(registry_path))
            assert count == 1

            loaded_service = new_registry.get(service_id)
            assert loaded_service is not None
            assert loaded_service.display_name == "Persist Test"

    def test_network_monitor_integration(self):
        """Test integration with NetworkMonitor."""
        self.registry.set_network_monitor(self.network_monitor)

        # Register a service with health check enabled
        service = ServiceMetadata(
            display_name="Test HTTP Service",
            service_type=ServiceType.REMOTE_API,
            provider=ServiceProvider.UNKNOWN,
            health_check_enabled=True,
            health_check_interval_seconds=60.0,
            health_check_timeout_seconds=10.0,
            health_check_path="/health",
            expected_status_codes=[200],
        )
        self.registry.register(service)
        service_id = service.service_id

        # Sync with NetworkMonitor
        self.registry.sync_with_network_monitor()

        # Verify service is registered in NetworkMonitor
        nm_service = self.network_monitor.get_service(service_id)
        assert nm_service is not None
        assert nm_service.name == service_id
        assert len(nm_service.endpoints) == 1
        assert nm_service.endpoints[0].url == service.endpoint.url

    def test_network_monitor_sync_updates(self):
        """Test that sync updates existing services."""
        self.registry.set_network_monitor(self.network_monitor)

        service = ServiceMetadata(
            display_name="Test Service",
            service_type=ServiceType.REMOTE_API,
            provider=ServiceProvider.UNKNOWN,
            health_check_enabled=True,
        )
        self.registry.register(service)
        service_id = service.service_id

        # First sync
        self.registry.sync_with_network_monitor()
        nm_service1 = self.network_monitor.get_service(service_id)
        assert nm_service1 is not None

        # Update service
        service.endpoint.url = "https://updated.example.com"
        # Second sync - should update
        self.registry.sync_with_network_monitor()
        nm_service2 = self.network_monitor.get_service(service_id)
        assert nm_service2 is not None
        assert nm_service2.endpoints[0].url == "https://updated.example.com"

    def test_health_monitoring_start(self):
        """Test starting health monitoring."""
        self.registry.set_network_monitor(self.network_monitor)
        self.registry.start_health_monitoring()
        # Should not raise any errors
        assert True

    def test_service_is_healthy(self):
        """Test ServiceMetadata.is_healthy method."""
        service = ServiceMetadata(
            display_name="Healthy Service",
            service_type=ServiceType.CUSTOM,
            provider=ServiceProvider.UNKNOWN,
            is_enabled=True,
            health=ServiceHealth.HEALTHY,
            availability=ServiceAvailability.AVAILABLE,
            auth_status=AuthStatus.NOT_REQUIRED,
        )
        assert service.is_healthy() is True

        service.health = ServiceHealth.UNHEALTHY
        assert service.is_healthy() is False

        service.health = ServiceHealth.HEALTHY
        service.is_enabled = False
        assert service.is_healthy() is False

    def test_effective_priority(self):
        """Test get_effective_priority method."""
        service = ServiceMetadata(
            display_name="Priority Test",
            service_type=ServiceType.CUSTOM,
            provider=ServiceProvider.UNKNOWN,
            priority=100,
        )
        assert service.get_effective_priority() == 100

        service.health = ServiceHealth.DEGRADED
        assert service.get_effective_priority() == 200

        service.health = ServiceHealth.UNHEALTHY
        assert service.get_effective_priority() == 1100

    def test_to_from_dict(self):
        """Test serialization/deserialization."""
        service = ServiceMetadata(
            display_name="Serialization Test",
            service_type=ServiceType.OPENAI,
            provider=ServiceProvider.OPENAI,
            version="v1",
            capabilities={ServiceCapability.TEXT_GENERATION, ServiceCapability.CHAT_COMPLETION},
            supported_models=["gpt-4o", "gpt-4"],
            is_default=True,
            priority=50,
            tags={"cloud", "llm"},
            metadata={"region": "us-east-1"},
        )

        # Convert to dict
        data = service.to_dict()
        assert data["service_id"] == service.service_id
        assert data["display_name"] == "Serialization Test"
        assert data["service_type"] == "openai"
        assert data["provider"] == "openai"
        assert "text_generation" in data["capabilities"]
        assert "chat_completion" in data["capabilities"]
        assert data["is_default"] is True

        # Convert back
        service2 = ServiceMetadata.from_dict(data)
        assert service2.service_id == service.service_id
        assert service2.display_name == service.display_name
        assert service2.service_type == service.service_type
        assert service2.provider == service.provider
        assert service2.capabilities == service.capabilities
        assert service2.is_default == service.is_default


class TestServiceRegistryWithEnvironment:
    """Test registry with various environment configurations."""

    def setup_method(self):
        """Save original environment."""
        self.original_env = dict(os.environ)

    def teardown_method(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_qdrant_discovery(self):
        """Test Qdrant discovery from env."""
        registry = ExternalServiceRegistry()
        os.environ["QDRANT_URL"] = "http://localhost:6333"
        os.environ["QDRANT_API_KEY"] = "test-key"

        discovered = registry.discover_qdrant()
        assert len(discovered) == 1
        assert discovered[0].service_type == ServiceType.VECTOR_DATABASE
        assert discovered[0].provider == ServiceProvider.QDRANT
        assert discovered[0].credentials.api_key == "test-key"

    def test_pinecone_discovery(self):
        """Test Pinecone discovery from env."""
        registry = ExternalServiceRegistry()
        os.environ["PINECONE_API_KEY"] = "test-key"
        os.environ["PINECONE_ENVIRONMENT"] = "us-west1-gcp"

        discovered = registry.discover_pinecone()
        assert len(discovered) == 1
        assert discovered[0].provider == ServiceProvider.PINECONE

    def test_minio_discovery(self):
        """Test MinIO discovery from env."""
        registry = ExternalServiceRegistry()
        os.environ["MINIO_ENDPOINT"] = "localhost:9000"
        os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
        os.environ["MINIO_SECRET_KEY"] = "minioadmin"

        discovered = registry.discover_minio()
        assert len(discovered) == 1
        assert discovered[0].provider == ServiceProvider.MINIO

    def test_s3_discovery(self):
        """Test S3 discovery from env."""
        registry = ExternalServiceRegistry()
        os.environ["AWS_ACCESS_KEY_ID"] = "test-key"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret"
        os.environ["AWS_REGION"] = "us-west-2"

        discovered = registry.discover_s3()
        assert len(discovered) == 1
        assert discovered[0].provider == ServiceProvider.S3

    def test_postgresql_discovery(self):
        """Test PostgreSQL discovery from env."""
        registry = ExternalServiceRegistry()
        os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/db"

        discovered = registry.discover_postgresql()
        assert len(discovered) == 1
        assert discovered[0].service_type == ServiceType.SQL_DATABASE
        assert discovered[0].provider == ServiceProvider.POSTGRESQL


# Import for tests
from app.world_model.services import ServiceAvailability, AuthStatus

if __name__ == "__main__":
    pytest.main([__file__, "-v"])