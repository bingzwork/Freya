from pathlib import Path
from types import SimpleNamespace

from app.capabilities.registration_bridge import CapabilityRegistrationBridge
from app.capabilities.router import CapabilityResult, CapabilityRouter
from app.conversational_control import ConversationControlHandler
from app.core.tool_manager import ToolManager
from app.execution.engine import ExecutionSafeFailure, UnifiedPlanner
from app.orchestrator.capability_registry import CapabilityRegistry, reset_capability_registry


class RecordingEventBus:
    def __init__(self):
        self.events = []

    def emit(self, name, data, source=None):
        self.events.append((name, data, source))


class RecordingChatActivity:
    def __init__(self):
        self.started = 0
        self.ended = 0

    def chat_started(self):
        self.started += 1

    def chat_ended(self):
        self.ended += 1


def test_current_architecture_documents_initializer_owned_v2_runtime():
    root = Path(__file__).resolve().parents[1]
    current = (root / "CURRENT_ARCHITECTURE.md").read_text(encoding="utf-8")

    required_fragments = (
        "# Freya Current Architecture",
        "**Status:** Current implemented architecture",
        "## 3. Initialization lifecycle",
        "SystemInitializer",
        "CapabilityRegistrationBridge",
        "PromotionRequest",
        "## 18. Evidence appendix",
    )
    assert all(fragment in current for fragment in required_fragments)
    assert "subgraph BOOT[\"1. BOOTSTRAP\"]" not in current
    assert "M2 --> H1 --> H2 --> F" not in current


def test_registry_router_handler_and_tool_manager_form_one_registration_chain(tmp_path):
    reset_capability_registry()
    try:
        registry = CapabilityRegistry()
        registry.start()
        tool_manager = ToolManager(tmp_path)
        router = CapabilityRouter()
        bridge = CapabilityRegistrationBridge(
            registry=registry,
            router=router,
            tool_manager=tool_manager,
        )
        calls = []

        bridge.register_query_capability(
            name="inspect_runtime",
            description="Inspect runtime state",
            keywords=["inspect runtime"],
            intent_types=["question"],
            handler=lambda context: calls.append(context) or CapabilityResult(
                success=True,
                message="runtime inspected",
            ),
        )

        result = router.route("please inspect runtime", intent_type="question")

        assert registry.get_capability("inspect_runtime") is not None
        assert "inspect_runtime" in router.get_capabilities()
        assert "capability::inspect_runtime" in tool_manager.tools
        assert result.success is True
        assert result.message == "runtime inspected"
        assert calls and calls[0]["capability_name"] == "inspect_runtime"
    finally:
        reset_capability_registry()


def test_conversation_control_is_question_ingress_and_memory_write_boundary():
    events = RecordingEventBus()
    writes = []
    memory = SimpleNamespace(
        get_conversation_context=lambda limit: [{"role": "user", "content": "earlier"}],
        get_active_goal=lambda: {"id": "goal-1"},
        record_conversation=lambda turn: writes.append(turn),
    )
    routed_context = {}
    router = SimpleNamespace(
        route=lambda question, context: routed_context.update({"question": question, "context": context})
        or SimpleNamespace(reason="knowledge-first"),
    )
    activity = RecordingChatActivity()
    control = ConversationControlHandler.__new__(ConversationControlHandler)
    control._router = router
    control._memory_coordinator = memory
    control._intelligence = object()
    control._chat_activity = activity
    control.event_bus = events

    route_result = control.route_question("What is Freya?")
    control.record_question_exchange("What is Freya?", "Freya is a local agent.")
    control.finish_question()

    assert route_result.reason == "knowledge-first"
    assert routed_context["context"]["ingress"] == "ConversationControl"
    assert routed_context["context"]["active_goal"]["id"] == "goal-1"
    assert writes == [
        {"role": "user", "content": "What is Freya?"},
        {"role": "assistant", "content": "Freya is a local agent."},
    ]
    assert activity.started == activity.ended == 1
    assert [event[0] for event in events.events] == [
        "conversation.question.received",
        "conversation.question.routed",
        "conversation.question.completed",
    ]


def test_unified_planner_uses_router_context_before_existing_planner():
    router = SimpleNamespace(
        get_planning_context=lambda task: {
            "knowledge": "Relevant project memory",
            "capabilities": [("tool_dispatch", 0.9)],
        }
    )
    planner = UnifiedPlanner.__new__(UnifiedPlanner)
    planner._router = router
    captured = {}
    planner._agent_planner = SimpleNamespace(
        create_plan=lambda task, external_context: captured.update(
            {"task": task, "external_context": external_context}
        )
        or "plan"
    )

    assert planner.create_plan("Run tests", "Existing context", True) == "plan"
    assert captured["task"] == "Run tests"
    assert "Relevant project memory" in captured["external_context"]
    assert "tool_dispatch" in captured["external_context"]


def test_execution_safe_failure_requests_compensation_reports_control_and_records_diagnostics():
    safety_calls = []
    reports = []
    patterns = []
    safe_failure = ExecutionSafeFailure(
        SimpleNamespace(
            check_and_enforce=lambda operation, operation_type, context: safety_calls.append(
                (operation, operation_type, context)
            )
        )
    )
    safe_failure.set_conversation_control(
        SimpleNamespace(report_partial_failure=lambda task, error, details: reports.append((task, error, details)))
    )
    safe_failure.set_diagnostics(
        SimpleNamespace(record_failure_pattern=lambda pattern: patterns.append(pattern))
    )

    safe_failure.handle(
        task="Apply patch",
        error="verification failed",
        state=SimpleNamespace(value="failed"),
    )

    assert safety_calls[0][1] == "execution_compensation"
    assert reports[0][0:2] == ("Apply patch", "verification failed")
    assert reports[0][2]["compensation"] == "authorized"
    assert patterns[0]["state"] == "failed"
