"""Tests for the Capability Routing System."""

import pytest
from app.capabilities.router import Capability, CapabilityResult, CapabilityRouter, NoCapabilityError, route_query, router
from app.capabilities.formatter import ResponseFormatter, format_capability_result, formatter
from app.capabilities.handlers import (
    get_python_version,
    get_os_info,
    get_current_model,
    get_ollama_status,
    get_git_status,
    get_working_directory,
    get_memory_usage,
    get_disk_usage,
    RuntimeCapabilityHandler,
    OllamaCapabilityHandler,
    GitCapabilityHandler,
    SystemCapabilityHandler,
)
from app.intent.classifier import IntentType, classify_intent


class TestCapability:
    """Tests for the Capability class."""

    def test_capability_creation(self):
        """Test creating a capability."""
        cap = Capability(
            name="test_capability",
            description="A test capability",
            handler=lambda ctx: CapabilityResult(success=True, data={"test": "value"}),
            patterns=[r"test\s+pattern"],
            keywords=["test", "pattern"],
            intent_types=["system_status"],
        )
        assert cap.name == "test_capability"
        assert cap.description == "A test capability"
        assert len(cap.patterns) == 1
        assert len(cap.keywords) == 2
        assert len(cap.intent_types) == 1

    def test_capability_matches_pattern(self):
        """Test capability matching with patterns."""
        cap = Capability(
            name="test_capability",
            description="A test capability",
            handler=lambda ctx: CapabilityResult(success=True),
            patterns=[r"hello\s+world"],
            intent_types=["system_status"],
        )
        matched, confidence = cap.matches("hello world", intent_type="system_status")
        assert matched is True
        assert confidence >= 0.95

    def test_capability_matches_keyword(self):
        """Test capability matching with keywords."""
        cap = Capability(
            name="test_capability",
            description="A test capability",
            handler=lambda ctx: CapabilityResult(success=True),
            keywords=["hello"],
            intent_types=["system_status"],
        )
        matched, confidence = cap.matches("hello there", intent_type="system_status")
        assert matched is True
        assert confidence > 0.5

    def test_capability_no_match_wrong_intent(self):
        """Test capability doesn't match with wrong intent type."""
        cap = Capability(
            name="test_capability",
            description="A test capability",
            handler=lambda ctx: CapabilityResult(success=True),
            intent_types=["system_status"],
        )
        matched, confidence = cap.matches("hello", intent_type="task")
        assert matched is False
        assert confidence == 0.0


class TestCapabilityResult:
    """Tests for the CapabilityResult dataclass."""

    def test_capability_result_creation(self):
        """Test creating a capability result."""
        result = CapabilityResult(
            success=True,
            data={"key": "value"},
            message="Test message",
            capability_name="test_cap",
            execution_time=0.5,
        )
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.message == "Test message"
        assert result.capability_name == "test_cap"
        assert result.execution_time == 0.5

    def test_capability_result_to_dict(self):
        """Test converting capability result to dict."""
        result = CapabilityResult(
            success=True,
            data={"key": "value"},
            message="Test message",
            capability_name="test_cap",
            execution_time=0.5,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == {"key": "value"}
        assert d["message"] == "Test message"
        assert d["capability"] == "test_cap"
        assert d["execution_time"] == 0.5


class TestCapabilityRouter:
    """Tests for the CapabilityRouter class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_router = CapabilityRouter()

    def test_router_register(self):
        """Test registering a capability."""
        cap = Capability(
            name="test_cap",
            description="Test capability",
            handler=lambda ctx: CapabilityResult(success=True),
        )
        self.test_router.register(cap)
        assert "test_cap" in self.test_router.get_capabilities()

    def test_router_find_matching(self):
        """Test finding matching capabilities."""
        cap = Capability(
            name="test_cap",
            description="Test capability",
            handler=lambda ctx: CapabilityResult(success=True),
            patterns=[r"test\s+query"],
            intent_types=["system_status"],
        )
        self.test_router.register(cap)
        matches = self.test_router.find_matching("test query", intent_type="system_status")
        assert len(matches) >= 1
        assert matches[0][0] == "test_cap"

    def test_router_route(self):
        """Test routing a query to a capability."""
        cap = Capability(
            name="test_cap",
            description="Test capability",
            handler=lambda ctx: CapabilityResult(success=True, data={"result": "success"}),
            patterns=[r"test\s+route"],
            intent_types=["system_status"],
        )
        self.test_router.register(cap)
        result = self.test_router.route("test route", intent_type="system_status")
        assert result.success is True
        assert result.capability_name == "test_cap"

    def test_router_no_capability_error(self):
        """Test NoCapabilityError is raised when no capability matches."""
        with pytest.raises(NoCapabilityError):
            self.test_router.route("nonexistent query")

    def test_router_can_handle(self):
        """Test can_handle method."""
        cap = Capability(
            name="test_cap",
            description="Test capability",
            handler=lambda ctx: CapabilityResult(success=True),
            patterns=[r"test\s+handle"],
            intent_types=["system_status"],
        )
        self.test_router.register(cap)
        assert self.test_router.can_handle("test handle", intent_type="system_status") is True
        assert self.test_router.can_handle("other query") is False


class TestHandlers:
    """Tests for capability handler functions."""

    def test_get_python_version(self):
        """Test get_python_version handler."""
        result = get_python_version()
        assert "version" in result
        assert "major" in result
        assert "minor" in result

    def test_get_os_info(self):
        """Test get_os_info handler."""
        result = get_os_info()
        assert "name" in result
        assert "version" in result

    def test_get_working_directory(self):
        """Test get_working_directory handler."""
        result = get_working_directory()
        assert "path" in result
        assert "exists" in result

    def test_get_current_model(self):
        """Test get_current_model handler."""
        result = get_current_model()
        assert "provider" in result
        assert "model" in result

    def test_get_ollama_status(self):
        """Test get_ollama_status handler."""
        result = get_ollama_status()
        assert "connected" in result
        assert "healthy" in result
        assert "provider" in result

    def test_get_git_status(self):
        """Test get_git_status handler."""
        result = get_git_status()
        assert "is_git_repo" in result


class TestFormatter:
    """Tests for the ResponseFormatter class."""

    def test_format_success(self):
        """Test formatting a successful result."""
        result = CapabilityResult(
            success=True,
            data={"version": "3.11.0"},
            capability_name="python_version",
        )
        formatted = format_capability_result(result)
        assert "3.11.0" in formatted

    def test_format_failure(self):
        """Test formatting a failure result."""
        result = CapabilityResult(
            success=False,
            message="Error occurred",
            capability_name="test_cap",
        )
        formatted = format_capability_result(result)
        # Errors should be hidden in non-debug mode
        assert "Error" not in formatted

    def test_format_ollama_status_connected(self):
        """Test formatting Ollama status when connected."""
        result = CapabilityResult(
            success=True,
            data={
                "connected": True,
                "healthy": True,
                "model": "qwen3:8b",
                "provider": "ollama",
            },
            capability_name="ollama_status",
        )
        formatted = format_capability_result(result)
        assert "Ollama" in formatted or "ollama" in formatted

    def test_format_git_status(self):
        """Test formatting Git status."""
        result = CapabilityResult(
            success=True,
            data={
                "is_git_repo": True,
                "branch": "main",
                "is_clean": True,
                "changes_count": 0,
            },
            capability_name="git_status",
        )
        formatted = format_capability_result(result)
        assert "Git" in formatted or "git" in formatted


class TestGlobalRouter:
    """Tests for the global router instance and route_query function."""

    def test_route_query_python_version(self):
        """Test routing a Python version query."""
        result = route_query("what is the python version", intent_type="system_status")
        assert result is not None
        assert result.success is True
        assert result.capability_name == "python_version"

    def test_route_query_current_model(self):
        """Test routing a current model query."""
        result = route_query("what model are you using", intent_type="system_status")
        assert result is not None
        assert result.success is True
        assert result.capability_name == "current_model"

    def test_route_query_ollama_status(self):
        """Test routing an Ollama status query."""
        result = route_query("are you connected to ollama", intent_type="system_status")
        assert result is not None
        assert result.success is True
        assert result.capability_name == "ollama_status"

    def test_route_query_os_info(self):
        """Test routing an OS info query."""
        result = route_query("what os am I using", intent_type="system_status")
        assert result is not None
        assert result.success is True
        assert result.capability_name == "os_info"

    def test_route_query_git_status(self):
        """Test routing a Git status query."""
        result = route_query("git status", intent_type="system_status")
        assert result is not None
        assert result.success is True
        assert result.capability_name == "git_status"

    def test_route_query_current_time(self):
        """Test routing a current time query."""
        result = route_query("what time is it", intent_type="system_status")
        assert result is not None
        assert result.success is True
        assert result.capability_name == "current_time"

    def test_route_query_no_match(self):
        """Test routing a query with no matching capability."""
        result = route_query("random query that does not match", intent_type="system_status")
        assert result is None


class TestIntentClassification:
    """Tests for intent classification with capability routing."""

    def test_system_status_intent(self):
        """Test that system status queries are classified correctly.

        Note: Only queries that match SYSTEM_STATUS patterns are actually
        classified as SYSTEM_STATUS. Other queries like "what is the python version"
        are classified as QUESTION, and "git status" as GIT_OPERATION.
        """
        # Queries that should be SYSTEM_STATUS
        system_status_queries = [
            "what model are you using",
            "are you connected to ollama",
        ]
        for query in system_status_queries:
            result = classify_intent(query)
            assert result.intent == IntentType.SYSTEM_STATUS, \
                f"Query '{query}' should be SYSTEM_STATUS, got {result.intent.value}"

        # Queries that are NOT SYSTEM_STATUS but still should not plan
        # "what is the python version" is a QUESTION (not SYSTEM_STATUS)
        # "what time is it" is CHAT (not SYSTEM_STATUS)
        # "git status" is GIT_OPERATION (requires planning)
        result_python = classify_intent("what is the python version")
        assert result_python.intent == IntentType.QUESTION
        assert result_python.should_plan is False  # Questions don't require planning

        result_time = classify_intent("what time is it")
        assert result_time.should_plan is False  # Chat doesn't require planning

        result_git = classify_intent("git status")
        assert result_git.intent == IntentType.GIT_OPERATION
        assert result_git.should_plan is True  # Git operations require planning


class TestConversationalControlCapabilities:
    """Tests for the ConversationalControlHandler registered in app.capabilities.handlers.

    These capabilities short-circuit routing per NATURAL_CONVERSATION.md
    "Conversational Control".
    """

    def test_control_capabilities_registered(self):
        from app.capabilities.router import router
        names = set(router.get_capabilities())
        assert "control_stop" in names
        assert "control_cancel" in names
        assert "control_undo" in names
        assert "control_redo" in names
        assert "control_status" in names

    @pytest.mark.parametrize("phrase,expected_capability", [
        ("stop", "control_stop"),
        ("halt", "control_stop"),
        ("wait", "control_stop"),
        ("cancel", "control_cancel"),
        ("nevermind", "control_cancel"),
        ("abort", "control_cancel"),
        ("undo", "control_undo"),
        ("revert", "control_undo"),
        ("redo", "control_redo"),
        ("status", "control_status"),
        ("what are you doing?", "control_status"),
        ("current plan", "control_status"),
        ("current step", "control_status"),
    ])
    def test_control_capability_routing(self, phrase, expected_capability):
        from app.capabilities.router import route_query
        result = route_query(phrase, intent_type="conversational_control")
        assert result is not None
        assert result.success is True
        assert result.capability_name == expected_capability
        assert result.data is not None
        assert "control_command" in result.data

    def test_stop_message_short_circuits(self):
        """A 'stop' command returns its acknowledgement; no error."""
        from app.capabilities.router import route_query
        from app.capabilities.formatter import format_capability_result
        result = route_query("stop", intent_type="conversational_control")
        formatted = format_capability_result(result)
        assert "stop" in formatted.lower() or "Stopped" in formatted

    def test_undo_message_does_not_error_when_no_mutations(self):
        """'undo' is a no-op when nothing has been mutated and must not error."""
        from app.capabilities.router import route_query
        result = route_query("undo", intent_type="conversational_control")
        assert result is not None
        assert result.success is True
