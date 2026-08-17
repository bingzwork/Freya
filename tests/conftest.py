import asyncio
import inspect
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

# Explicit classification keeps the fast suite deterministic while leaving
# model/integration/environment tests available to the complete-suite command.
_LLM_MODULES = {"test_llm.py", "test_llm_stack.py", "test_providers.py", "test_provider_resilience.py"}
_INTEGRATION_MODULES = {"test_browser_playwright_smoke.py", "test_external_service_registry.py", "test_http_tools.py", "test_production_health_readiness.py", "test_production_retrieval_integration.py", "test_websearch_osint.py"}
_ENVIRONMENT_MODULES = {"test_clean_process_runtime.py", "test_durable_memory_process_restart.py", "test_gpu_monitor.py"}
_SLOW_MODULES = {"test_agent_conversation.py", "test_project_memory.py", "test_vector_db.py", "test_learning_pipeline.py", "test_knowledge_retrieval.py", "test_capability_audit.py"}


def pytest_pyfunc_call(pyfuncitem):
    """Run async tests without adding a dependency when pytest-asyncio is absent."""
    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None
    if pyfuncitem.config.pluginmanager.hasplugin("asyncio"):
        return None
    testargs = {
        arg: pyfuncitem.funcargs[arg]
        for arg in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(testfunction(**testargs))
    return True

def pytest_collection_modifyitems(config, items):
    for item in items:
        module_name = item.fspath.basename
        if module_name in _LLM_MODULES:
            item.add_marker(pytest.mark.llm)
        elif module_name in _INTEGRATION_MODULES:
            item.add_marker(pytest.mark.integration)
        elif module_name in _ENVIRONMENT_MODULES:
            item.add_marker(pytest.mark.environment)
        else:
            item.add_marker(pytest.mark.core)
            if module_name in _SLOW_MODULES:
                item.add_marker(pytest.mark.slow)
