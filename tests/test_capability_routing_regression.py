from pathlib import Path
import pytest
from main import FreyaApp

PROMPTS = {
    "api_connector": "Call the local API endpoint and return its JSON.",
    "audio": "Transcribe this local audio file.",
    "automation": "Create a reminder for tomorrow.",
    "browser_capability": "Open this website.",
    "calendar": "What appointments do I have?",
    "capability_introspection": "What capabilities are available?",
    "code_execution": "Run this Python code: print(1).",
    "communication_hub": "Send a message to the team.",
    "computer": "Open the calculator application.",
    "contacts": "Find John in my contacts.",
    "data_analysis": "Analyze this CSV file.",
    "database": "List the tables in this database.",
    "debugging": "Help debug this traceback.",
    "decision_engine": "Compare alpha and beta and recommend one.",
    "dependency_management": "Check the installed packages.",
    "document_editing": "Edit this document.",
    "email": "Send an email.",
    "file_input": "Read this local file.",
    "file_output": "Save this to a file.",
    "image": "Analyze this image.",
    "iot": "Check my smart home devices.",
    "knowledge_base": "Search the stored knowledge base.",
    "learning_pipeline": "Record this lesson for learning.",
    "memory_management": "Remember this fact.",
    "orchestration_core": "Run this workflow.",
    "planning_engine": "Make a plan for this task.",
    "reasoning_engine": "Reason through this problem step by step.",
    "research_capability": "Search the web for current information.",
    "safety_guard": "Check whether this action is safe.",
    "show_capabilities": "What can you do?",
    "show_goals": "Show me my goals.",
    "show_identity": "Who are you?",
    "show_memory": "What do you remember?",
    "show_tasks": "Show my active tasks.",
    "simulation_capability": "Simulate what happens if this service fails.",
    "system_monitoring": "Check system health and metrics.",
    "system_status": "What is the current system status?",
    "tool_dispatch": "Run the registered tool.",
    "tool_registry": "List the available tools and their metadata.",
    "video": "Analyze this local video.",
    "vision": "Inspect what is in this image.",
    "voice": "Speak this response aloud.",
}

@pytest.fixture(scope="module")
def live_router():
    app = FreyaApp(Path.cwd())
    app.start()
    try:
        yield app.system.facade._control._router
    finally:
        app.shutdown()

@pytest.mark.parametrize("capability,prompt", PROMPTS.items())
def test_realistic_prompt_selects_capability(live_router, capability, prompt):
    route = live_router.route(prompt)
    assert route.capability_name == capability, {
        "prompt": prompt,
        "expected": capability,
        "actual": route.capability_name,
        "reason": route.reason,
    }
