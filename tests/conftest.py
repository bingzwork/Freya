import gc
import time

import pytest

from app.orchestrator.capability_registry import reset_capability_registry
from app.orchestrator.workflow_orchestrator import reset_workflow_orchestrator


@pytest.fixture(autouse=True)
def isolate_global_runtime():
    """Release process-global runtime state after every test."""
    yield
    reset_workflow_orchestrator()
    reset_capability_registry()
    gc.collect()
    time.sleep(0.05)
