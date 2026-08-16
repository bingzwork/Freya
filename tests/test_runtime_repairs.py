import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.orchestrator.workflow_composer import *
from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator

def test_search_query_mapping():
    composer = object.__new__(WorkflowComposer)
    spec = WorkflowSpec(description='Find status', context={'user_query': 'Find status'})
    step = WorkflowStep(capability_name='knowledge_base', action='search_web')
    task = composer._build_task_graph(spec, [step]).get_task(step.step_id)
    assert task.metadata['inputs'] == {'query': 'Find status'}

def test_housekeeping_iso_time():
    orchestrator = object.__new__(WorkflowOrchestrator)
    orchestrator._workflow_lock = threading.RLock()
    orchestrator._active_workflows = {'wf': SimpleNamespace(status=WorkflowStatus.COMPLETED, completed_at=(datetime.now(timezone.utc)-timedelta(seconds=301)).isoformat())}
    orchestrator._run_housekeeping()
    assert orchestrator._active_workflows == {}
