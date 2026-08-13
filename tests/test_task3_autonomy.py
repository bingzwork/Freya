from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.autonomy.manager import AutonomyManager as CanonicalAutonomyManager
from app.autonomy.manager import AutonomyStartupError
from app.autonomy.models import AutonomyConfig
from app.long_term_autonomy.manager import AutonomyManager as LongTermAutonomyManager


def test_canonical_autonomy_start_requires_explicit_dependencies():
    manager = CanonicalAutonomyManager(
        config=AutonomyConfig(
            use_background_job_service=False,
            watchdog_enabled=True,
            self_initiated_enabled=True,
            maintenance_enabled=True,
        ),
        event_bus=MagicMock(),
        observability=MagicMock(),
    )

    with pytest.raises(AutonomyStartupError, match="learning_pipeline"):
        manager.start()

    assert manager.is_running() is False


def make_long_term_manager(tmp_path):
    pipeline = MagicMock(return_value=SimpleNamespace(errors=[]))
    manager = LongTermAutonomyManager(
        workspace=str(tmp_path),
        event_bus=MagicMock(),
        job_service=MagicMock(),
        observability=MagicMock(),
        planner=MagicMock(),
        executor=MagicMock(),
        verifier=MagicMock(),
    )
    manager.learning_pipeline = pipeline
    manager.job_service.get_job.return_value = None
    return manager, pipeline


def test_long_term_jobs_use_real_callback_interfaces(tmp_path):
    manager, _ = make_long_term_manager(tmp_path)

    manager._register_background_jobs()

    callbacks = {
        call.kwargs["job_id"]: call.kwargs["func"]
        for call in manager.job_service.schedule.call_args_list
    }
    assert callbacks
    assert callbacks["autonomy_learning_pipeline"] == manager._run_learning_pipeline_job
    assert callbacks["autonomy_watchdog_checkpoint"] == manager._autonomy_watchdog_checkpoint
    assert callbacks["autonomy_self_initiated_work"] == manager._autonomy_self_initiated_work_job
    assert all(call.kwargs["trigger"].interval_seconds > 0 for call in manager.job_service.schedule.call_args_list)


def test_long_term_learning_job_reaches_pipeline(tmp_path):
    manager, pipeline = make_long_term_manager(tmp_path)

    result = manager._run_learning_pipeline_job()

    pipeline.assert_called_once_with()
    assert result.errors == []


def test_long_term_checkpoint_and_work_discovery_use_implemented_interfaces(tmp_path):
    manager, _ = make_long_term_manager(tmp_path)
    manager.continuous_operation = MagicMock()
    manager.continuous_operation.force_checkpoint.return_value = True
    manager.self_initiated_work = MagicMock()
    opportunity = SimpleNamespace(id="opp-1")
    manager.self_initiated_work.get_pending_opportunities.return_value = [opportunity]
    manager.self_initiated_work.schedule_opportunity.return_value = "task-1"
    manager._execute_specific_task = MagicMock(return_value={"verified": True})

    manager._autonomy_watchdog_checkpoint()
    scheduled = manager._autonomy_self_initiated_work_job()

    manager.continuous_operation.force_checkpoint.assert_called_once_with()
    manager.self_initiated_work._scan_and_generate.assert_called_once_with()
    manager.self_initiated_work.schedule_opportunity.assert_called_once_with("opp-1")
    manager.self_initiated_work.mark_opportunity_completed.assert_called_once_with("opp-1")
    assert scheduled == ["task-1"]


def test_long_term_task_completion_requires_verification(tmp_path):
    manager, _ = make_long_term_manager(tmp_path)
    task = manager.create_autonomous_task("Run a verified task", source="self_initiated")
    manager.planner.create_plan.return_value = SimpleNamespace(tasks=[object()])
    manager.executor.execute_plan.return_value = [{"result": {"value": "executed"}}]
    manager.verifier.dry_run_verify.return_value = SimpleNamespace(
        success=False,
        stderr="verification failed",
    )

    result = manager._execute_specific_task({"task_id": task.id})
    stored = manager.storage.get_task(task.id)

    assert result.get("verified") is not True
    assert result["verification_failed"] is True
    assert stored.status == "verification_failed"


def test_long_term_task_completes_only_after_verified_execution(tmp_path):
    manager, _ = make_long_term_manager(tmp_path)
    task = manager.create_autonomous_task("Run a verified task", source="self_initiated")
    manager.planner.create_plan.return_value = SimpleNamespace(tasks=[object()])
    manager.executor.execute_plan.return_value = [{"result": {"value": "executed"}}]
    manager.verifier.dry_run_verify.return_value = SimpleNamespace(
        success=True,
        stdout="verified",
        stderr="",
    )

    result = manager._execute_specific_task({"task_id": task.id})
    stored = manager.storage.get_task(task.id)

    assert result["verified"] is True
    assert stored.status == "completed"
    assert stored.result["verification"]["success"] is True


def test_long_term_missing_execution_dependencies_fail_without_completion(tmp_path):
    manager, _ = make_long_term_manager(tmp_path)
    manager.planner = None
    task = manager.create_autonomous_task("Cannot execute without planner")

    result = manager._execute_specific_task({"task_id": task.id})
    stored = manager.storage.get_task(task.id)

    assert result["action_taken"] is False
    assert stored.status == "failed"
    assert stored.status != "completed"
