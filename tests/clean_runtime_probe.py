"""Standalone canonical-runtime probe invoked by the clean-process integration test."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.protocols import SystemConfig
from app.planner.plan_manager import Plan, PlanConfig
from app.planner.task import Task
from app.verification.runner import VerificationResult
from main import FreyaApp


def _deterministic_llm(prompt: str, *args, **kwargs) -> str:
    """Replace the optional local-model boundary without changing the runtime graph."""
    if "Plan a SHORT execution" in prompt:
        return '{"steps": ["Read README.md"]}'
    if "Summarize for the user" in prompt:
        return "The requested read completed and verification passed."
    return "The clean-process marker is available from local memory."


def _verified_result() -> VerificationResult:
    return VerificationResult(
        success=True,
        command=["verify", "tests+lint"],
        stdout="verification passed",
        stderr="",
        return_code=0,
    )


def main(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("Clean process fixture.\n", encoding="utf-8")
    config = SystemConfig(
        workspace=workspace,
        enable_autonomy=True,
        enable_orchestrator=True,
        enable_diagnostics=True,
        enable_self_improvement=True,
        enable_file_watcher=False,
        enable_config_hot_reload=False,
        enable_observability=True,
    )
    app = FreyaApp(workspace, config)
    app.start()
    system = app.system
    marker = "freya-clean-process-known-memory-marker"

    try:
        assert system.execution._safety_gate is system.orchestrator.safety_gate
        assert system.self_improvement._workflow_orchestrator is system.orchestrator
        assert system.infra.job_service is system.autonomy._job_service
        # Bind this test-only external boundary before every question so the
        # clean process never waits on or downloads an optional local model.
        system.priority_llm._llm.ask = _deterministic_llm

        system.memory.record_conversation({"role": "assistant", "content": marker})
        known_memory_answer = app.chat(f"What do you know about {marker}?")
        assert known_memory_answer
        retrieved = system.memory.unified_retrieval.retrieve(marker)
        assert any(marker in result.content for result in retrieved)

        capability = system.facade._router.execute_capability("show_capabilities", "show capabilities")
        assert capability.success

        unsupported_answer = app.chat("What is the weather on Neptune today?")
        assert "reliable" in unsupported_answer.lower() or "enough" in unsupported_answer.lower()

        system.execution._planner.create_plan = lambda task, context, allow_mutations: Plan(
            config=PlanConfig(name="Clean process read-only plan"),
            tasks=[Task(title="Read README.md")],
        )
        system.execution._executor._agent_executor.execute_step = lambda title, tools: {
            "success": True,
            "output": "README.md read through the approved capability path.",
        }
        system.execution._execution_verifier._verification_runner.dry_run_verify = _verified_result
        execution_answer = app.execute_task("Read README.md", allow_mutations=False)
        assert execution_answer == "The requested read completed and verification passed."
    finally:
        app.shutdown()

    assert app._running is False
    assert system.infra.job_service._shutdown is True
    assert system.infra.event_bus._running is False
    assert not system.priority_llm._worker_thread.is_alive()
    assert not system.orchestrator._main_thread.is_alive()
    print(json.dumps({"success": True, "known_memory": marker}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
