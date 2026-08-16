import unittest
from unittest.mock import MagicMock, patch
import sys


class TestWorkflowOrchestrator(unittest.TestCase):
    def test_execute_workflow_approved(self):
        mock_event_bus = MagicMock()
        mock_job_service = MagicMock()
        mock_observability = MagicMock()
        mock_registry = MagicMock()
        
        mock_composed_workflow = MagicMock()
        mock_composed_workflow.spec = MagicMock()
        mock_composed_workflow.spec.workflow_id = 'test-workflow'
        mock_composed_workflow.spec.name = 'Test Workflow'
        mock_composed_workflow.steps = []
        mock_composed_workflow.task_graph = MagicMock()
        
        mock_composer = MagicMock()
        mock_composer.compose.return_value = mock_composed_workflow
        
        mock_executor = MagicMock()
        mock_executor.execute.return_value = 'exec-123'
        
        mock_observer = MagicMock()
        
        safety_gate_mock = MagicMock()
        safety_gate_mock.check_and_enforce.return_value = MagicMock(success=True, status='approved')
        
        # Patch at the SOURCE modules where they're defined
        with patch('app.core.events.get_event_bus', return_value=mock_event_bus),              patch('app.core.background_jobs.get_job_service', return_value=mock_job_service),              patch('app.core.observability.get_observability_hub', return_value=mock_observability),              patch('app.orchestrator.workflow_orchestrator.CapabilityRegistry', return_value=mock_registry),              patch('app.orchestrator.workflow_orchestrator.WorkflowComposer', return_value=mock_composer),              patch('app.orchestrator.workflow_orchestrator.TaskExecutor', return_value=mock_executor),              patch('app.orchestrator.workflow_orchestrator.SelfObserver', return_value=mock_observer):
            
            from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator
            
            orch = WorkflowOrchestrator(safety_gate=safety_gate_mock)
            orch.start()
            result = orch.execute_workflow(MagicMock())
            orch.stop()
            self.assertRegex(str(result), 'exec-123')

    def test_execute_workflow_rejected(self):
        mock_event_bus = MagicMock()
        mock_job_service = MagicMock()
        mock_observability = MagicMock()
        mock_registry = MagicMock()
        
        mock_composer = MagicMock()
        mock_executor = MagicMock()
        mock_observer = MagicMock()
        
        safety_gate_mock = MagicMock()
        safety_gate_mock.check_and_enforce.side_effect = Exception('Safety gate rejected')
        
        # Patch at the SOURCE modules where they're defined
        with patch('app.core.events.get_event_bus', return_value=mock_event_bus),              patch('app.core.background_jobs.get_job_service', return_value=mock_job_service),              patch('app.core.observability.get_observability_hub', return_value=mock_observability),              patch('app.orchestrator.workflow_orchestrator.CapabilityRegistry', return_value=mock_registry),              patch('app.orchestrator.workflow_orchestrator.WorkflowComposer', return_value=mock_composer),              patch('app.orchestrator.workflow_orchestrator.TaskExecutor', return_value=mock_executor),              patch('app.orchestrator.workflow_orchestrator.SelfObserver', return_value=mock_observer):
            
            from app.orchestrator.workflow_orchestrator import WorkflowOrchestrator
            
            orch = WorkflowOrchestrator(safety_gate=safety_gate_mock)
            orch.start()
            with self.assertRaises(Exception):
                orch.execute_workflow(MagicMock())
            orch.stop()


if __name__ == '__main__':
    unittest.main()
