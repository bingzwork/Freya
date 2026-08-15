from __future__ import annotations

from pathlib import Path

from app.core.protocols import SystemConfig
from app.orchestrator.capability_registry import CapabilityRegistry
from main import FreyaApp


def _start_app(tmp_path: Path) -> FreyaApp:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("authoritative capability fixture\n")
    app = FreyaApp(
        workspace,
        SystemConfig(
            workspace=workspace,
            enable_autonomy=False,
            enable_file_watcher=False,
            enable_config_hot_reload=False,
        ),
    )
    app.start()
    return app


def test_authoritative_capability_collaborators_are_initializer_owned(tmp_path: Path):
    app = _start_app(tmp_path)
    try:
        system = app.system
        capabilities = CapabilityRegistry().get_all()

        memory = capabilities["memory_management"]
        assert memory._memory is system.memory

        learning = capabilities["learning_pipeline"]
        assert learning._pipeline is system.learning_pipeline
        assert learning._memory is system.memory

        knowledge = capabilities["knowledge_base"]
        assert knowledge._memory is system.memory
        assert knowledge._retrieval is system.memory.unified_retrieval

        reasoning = capabilities["reasoning_engine"]
        assert reasoning._intelligence is app.initializer._intelligence
    finally:
        app.shutdown()


def test_memory_learning_knowledge_and_reasoning_actions_use_current_paths(tmp_path: Path):
    app = _start_app(tmp_path)
    try:
        capabilities = CapabilityRegistry().get_all()

        memory = capabilities["memory_management"]
        stored = memory.execute(
            "store",
            {
                "type": "semantic",
                "content": "Freya keeps local knowledge authoritative before fallback.",
                "metadata": {"title": "Knowledge-first routing", "category": "architecture"},
            },
        )
        assert stored["success"] is True
        assert "Memory not initialized" not in str(stored)

        retrieved = memory.execute(
            "retrieve", {"type": "unified", "query": "knowledge authoritative", "limit": 5}
        )
        assert retrieved["success"] is True
        assert "MemoryCoordinator unavailable" not in str(retrieved)

        learning = capabilities["learning_pipeline"]
        learned = learning.execute(
            "reflect",
            {
                "task": "The local retrieval path was verified.",
                "outcome": "success",
                "context": {"verified": True},
                "tags": ["architecture"],
            },
        )
        assert learned["success"] is True
        assert "LearningPipeline unavailable" not in str(learned)

        knowledge = capabilities["knowledge_base"]
        knowledge_stored = knowledge.execute(
            "store_knowledge",
            {
                "title": "Unified retrieval",
                "content": "UnifiedRetrieval aggregates the coordinator-owned memory modules.",
                "category": "architecture",
            },
        )
        assert knowledge_stored["success"] is True
        searched = knowledge.execute(
            "search", {"query": "UnifiedRetrieval coordinator memory", "limit": 5}
        )
        assert searched["success"] is True
        assert "UnifiedRetrieval unavailable" not in str(searched)

        reasoning = capabilities["reasoning_engine"]
        analyzed = reasoning.execute(
            "analyze", {"problem": "How should local knowledge be used?", "context": {}}
        )
        assert analyzed["success"] is True
        assert analyzed["analysis"]["next_action"]["answer_source"] in {
            "internal_knowledge", "capability_system", "llm_fallback"
        }
        synthesized = reasoning.execute(
            "synthesize",
            {"task": "Summarize the local knowledge route", "sources": searched["results"]},
        )
        assert synthesized["success"] is True
        assert "LLM not available" not in str(synthesized)
    finally:
        app.shutdown()


def test_reasoning_capability_does_not_directly_call_an_agent_llm():
    import inspect
    from app.orchestrator.capabilities import ReasoningEngineCapability

    source = inspect.getsource(ReasoningEngineCapability)
    assert "self._agent" not in source
    assert "self._agent.llm" not in source
    assert "set_intelligence" in source
