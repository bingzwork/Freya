"""Permanent regression coverage for pasted_content_15 autonomy reliability boundaries."""

from unittest.mock import MagicMock

from app.autonomy.models import AutonomyConfig, GoalContext
from app.autonomy.self_initiated import SelfInitiatedWorkManager
from app.orchestrator.workflow_orchestrator import WorkflowStatus


def _goal(goal_id="goal-1", name="Ship MVP", description="Advance the Freya MVP"):
    return GoalContext(
        goal_id=goal_id,
        name=name,
        description=description,
        status="in_progress",
        priority="high",
        progress=0.25,
        is_blocked=False,
        blocking_reasons=[],
        dependencies=[],
        duration_estimate=None,
        metadata={},
        created_at="2026-08-18T00:00:00+00:00",
        updated_at="2026-08-18T00:00:00+00:00",
    )


def _goal_mapping(goal_id="goal-1", name="Ship MVP", description="Advance the Freya MVP"):
    return {
        "goal_id": goal_id,
        "name": name,
        "description": description,
        "status": "in_progress",
        "priority": "high",
        "progress": 0.25,
        "is_blocked": False,
        "blocking_reasons": [],
        "dependencies": [],
        "duration_estimate": None,
        "metadata": {},
        "created_at": "2026-08-18T00:00:00+00:00",
        "updated_at": "2026-08-18T00:00:00+00:00",
    }


def _manager(orchestrator=None, **config_overrides):
    goal_storage = MagicMock()
    goal_storage.get_next_eligible_goals.return_value = []
    orchestrator = orchestrator or MagicMock()
    values = {
        "self_initiated_enabled": True,
        "use_background_job_service": False,
        "max_actions_per_cycle": 1,
        "max_retries_per_task": 1,
        "failure_backoff_seconds": 0.0,
        "repeated_failure_cooldown_seconds": 0.0,
    }
    values.update(config_overrides)
    manager = SelfInitiatedWorkManager(
        config=AutonomyConfig(**values),
        goal_storage=goal_storage,
        workflow_orchestrator=orchestrator,
    )
    return manager, goal_storage, orchestrator


def test_invalid_autonomous_candidate_without_goal_is_rejected():
    manager, _, _ = _manager()

    assert manager._create_work_from_goal(_goal(goal_id="", name="Valid name")) is None
    assert manager._create_work_from_goal(_goal(name="", description="Valid description")) is None


def test_duplicate_equivalent_goal_is_suppressed_with_stable_key():
    manager, goal_storage, orchestrator = _manager()
    orchestrator.execute_workflow.return_value = "exec-1"
    goal_storage.get_next_eligible_goals.return_value = [_goal_mapping()]
    manager.start()

    manager._check_and_generate_work()
    manager._check_and_generate_work()

    assert orchestrator.execute_workflow.call_count == 1
    active = manager.get_active_work()
    assert len(active) == 1
    assert active[0].metadata["deduplication_key"].startswith("autonomy:")
    assert active[0].metadata["source_id"] == "goal-1"
    manager.stop()


def test_safety_gate_denial_fails_autonomous_work_without_propagating():
    orchestrator = MagicMock()
    orchestrator.execute_workflow.side_effect = RuntimeError("safety gate denied")
    manager, goal_storage, _ = _manager(orchestrator)
    goal_storage.get_next_eligible_goals.return_value = [_goal_mapping()]
    manager.start()

    manager._check_and_generate_work()

    assert len(manager.get_active_work()) == 0
    history = manager.get_work_history()
    assert history[-1].status == "failed"
    assert "safety gate denied" in history[-1].metadata["error"]
    manager.stop()


def test_repeated_autonomous_failure_is_bounded_by_max_retries():
    orchestrator = MagicMock()
    orchestrator.execute_workflow.side_effect = RuntimeError("transient failure")
    manager, goal_storage, _ = _manager(orchestrator, max_retries_per_task=1)
    goal_storage.get_next_eligible_goals.return_value = [_goal_mapping()]
    manager.start()

    manager._check_and_generate_work()
    manager._check_and_generate_work()
    manager._check_and_generate_work()

    assert orchestrator.execute_workflow.call_count == 2
    assert len(manager.get_work_history()) == 2
    assert manager.get_work_history()[-1].metadata["retry_state"]["attempt"] == 2
    manager.stop()


def test_autonomous_completion_requires_verified_outcome():
    orchestrator = MagicMock()
    orchestrator.execute_workflow.return_value = "exec-verified"
    orchestrator.get_workflow_verification.return_value = {"status": "verified", "success": True}
    manager, _, _ = _manager(orchestrator)
    manager.start()
    item = manager._create_work_from_goal(_goal())
    manager._active_work[item.id] = item
    item.status = "running"
    item.workflow_execution_id = "exec-verified"

    orchestrator.get_workflow_status.return_value = WorkflowStatus.COMPLETED
    manager._monitor_work(item)

    assert manager.get_work_history()[-1].status == "completed"
    assert manager.get_work_history()[-1].metadata["completion_details"]["verification"]["status"] == "verified"
    manager.stop()


def test_autonomous_shutdown_cancels_pending_work_cleanly():
    orchestrator = MagicMock()
    orchestrator.execute_workflow.return_value = "exec-pending"
    orchestrator.get_workflow_status.return_value = WorkflowStatus.EXECUTING
    manager, goal_storage, _ = _manager(orchestrator)
    goal_storage.get_next_eligible_goals.return_value = [_goal_mapping()]
    manager.start()

    manager._check_and_generate_work()
    assert len(manager.get_active_work()) == 1
    manager.stop()

    assert not manager.is_running()
    assert manager.get_active_work() == []
    assert manager.get_work_history()[-1].metadata["completion_details"]["final_status"] == "shutdown"
    orchestrator.cancel_workflow.assert_called_once_with("exec-pending")
