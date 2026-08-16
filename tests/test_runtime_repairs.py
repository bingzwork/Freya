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

def test_self_analysis_ignores_unknown_resource_percentages():
    from app.self_observation.self_analysis import CentralizedSelfAnalysis
    resources = SimpleNamespace(cpu_percent=None, memory_percent=None, disk_percent=None)
    service = object.__new__(CentralizedSelfAnalysis)
    service._world_model = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(resources=resources))
    service._orchestrator = None
    service._decision_manager = None
    service._autonomous_learning = None
    result = service._analyze_limitations()
    assert result is not None

def test_question_selection_skips_vision_without_image_reference():
    from app.orchestrator.workflow_composer import IntentBasedSelector, WorkflowSpec
    vision = SimpleNamespace(metadata=SimpleNamespace(name='vision'))
    class Registry:
        def get_capabilities_by_category(self, category):
            return [vision]
    spec = WorkflowSpec(description='Answer a question', context={}, intent=IntentType.QUESTION)
    assert IntentBasedSelector().select(spec, Registry()) == []
