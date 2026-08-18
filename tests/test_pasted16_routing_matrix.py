from pathlib import Path

import pytest
from main import FreyaApp

ROUTING_VARIANTS = {
    "api_connector": [
        "Call the local API endpoint and return its JSON.",
        "Make a GET request to this approved web API.",
        "Fetch the JSON response from the configured API.",
        "Send this request to the allowed HTTP endpoint.",
        "Read data from the configured API service.",
    ],
    "audio": [
        "Transcribe this local audio file.",
        "Convert this recording to text.",
        "Trim the beginning from this sound file.",
        "Normalize the volume in this audio.",
        "Split this recording into smaller clips.",
    ],
    "automation": [
        "Create a reminder for tomorrow.",
        "Remind me every Monday to review the report.",
        "Schedule this recurring task for me.",
        "Pause the reminder that I created.",
        "Show the status of my scheduled automations.",
    ],
    "browser_capability": [
        "Open this website.",
        "Navigate to the public web page.",
        "Read the contents of this URL.",
        "Reload the page and tell me its title.",
        "Find the login link on this web page.",
    ],
    "calendar": [
        "What appointments do I have?",
        "Show my calendar for tomorrow.",
        "Find my next meeting.",
        "Do I have availability this afternoon?",
        "Create a calendar event for the appointment.",
    ],
    "capability_introspection": [
        "What capabilities are available?",
        "Show me Freya's capability list.",
        "Which things can you do?",
        "Tell me what functions are supported.",
        "What can Freya help me with?",
    ],
    "code_execution": [
        "Run this Python code: print(1).",
        "Execute this safe local command.",
        "Run the script I provided.",
        "Test this code in the local environment.",
        "Apply this code patch and verify it.",
    ],
    "communication_hub": [
        "Send a message to the team.",
        "Publish this announcement to the shared channel.",
        "Show the communication history.",
        "Post this update for the group.",
        "Review the messages sent through the hub.",
    ],
    "computer": [
        "Open the calculator application.",
        "Take a screenshot of the desktop.",
        "Click the button on the open application.",
        "Type this text into the current window.",
        "Use a keyboard shortcut on the computer.",
    ],
    "contacts": [
        "Find John in my contacts.",
        "Search my address book for Alice.",
        "Read the contact details for this person.",
        "Create a new contact entry.",
        "Update the phone number in my contacts.",
    ],
    "data_analysis": [
        "Analyze this CSV file.",
        "Summarize the columns in this spreadsheet.",
        "Group these data rows by category.",
        "Calculate the correlation in this dataset.",
        "Create a chart from these data.",
    ],
    "database": [
        "List the tables in this database.",
        "Run a read-only SQL query.",
        "Show the database schema.",
        "Find these records in the SQLite database.",
        "Inspect the columns in this table.",
    ],
    "debugging": [
        "Help debug this traceback.",
        "Diagnose the error in this log.",
        "Inspect why this program failed.",
        "Run diagnostics on the broken task.",
        "Validate whether this fix resolves the error.",
    ],
    "decision_engine": [
        "Compare alpha and beta and recommend one.",
        "Help me choose between these two options.",
        "Evaluate the alternatives and decide which is better.",
        "Which choice should I make given these options?",
        "Compare the advantages of these alternatives.",
    ],
    "dependency_management": [
        "Check the installed packages.",
        "Verify whether this dependency is installed.",
        "Inspect the local Python environment.",
        "Validate the project dependencies.",
        "Check which required tools are available.",
    ],
    "document_editing": [
        "Edit this document.",
        "Rewrite this document with the corrected wording.",
        "Format the report and save the changes.",
        "Modify the contents of this file.",
        "Export the edited document.",
    ],
    "email": [
        "Send an email.",
        "Search my inbox for the latest message.",
        "Draft a reply to this email.",
        "Read the selected email.",
        "Archive this email message.",
    ],
    "file_input": [
        "Read this local file.",
        "Load the contents of the text file.",
        "Open this file for inspection.",
        "Import the file from this path.",
        "Read the document I attached.",
    ],
    "file_output": [
        "Save this to a file.",
        "Write the result to the requested path.",
        "Export this content as a file.",
        "Create a text file with this output.",
        "Store the report on disk.",
    ],
    "image": [
        "Analyze this image.",
        "Resize the picture to a smaller size.",
        "Crop the image around the subject.",
        "Convert this image to PNG.",
        "Remove the background from this picture.",
    ],
    "iot": [
        "Check my smart home devices.",
        "List the connected IoT devices.",
        "Read the temperature sensor state.",
        "Show the current device status.",
        "Turn on the living room smart light.",
    ],
    "knowledge_base": [
        "Search the stored knowledge base.",
        "Find this fact in my knowledge.",
        "Look up the saved project information.",
        "Store this durable fact in the knowledge base.",
        "Retrieve the relevant stored knowledge.",
    ],
    "learning_pipeline": [
        "Record this lesson for learning.",
        "Learn this durable correction.",
        "Consolidate the validated lesson.",
        "Reflect on what happened and extract a lesson.",
        "Store this verified learning result.",
    ],
    "memory_management": [
        "Remember this fact.",
        "Save this preference to memory.",
        "Retrieve what I told you earlier.",
        "Consolidate the relevant memories.",
        "Store this information for later.",
    ],
    "orchestration_core": [
        "Run this workflow.",
        "Execute the existing workflow now.",
        "Check the status of the workflow.",
        "Start the composed sequence of steps.",
        "Orchestrate these tasks in order.",
    ],
    "planning_engine": [
        "Make a plan for this task.",
        "Create a project plan.",
        "Break this objective into steps.",
        "Replan the work after this change.",
        "Show me the current plan.",
    ],
    "reasoning_engine": [
        "Reason through this problem step by step.",
        "Explain why this result happened.",
        "Analyze the causes of this issue.",
        "Think through the tradeoffs carefully.",
        "Synthesize an answer from these facts.",
    ],
    "research_capability": [
        "Search the web for current information.",
        "Research this topic and compare sources.",
        "Verify this claim against public sources.",
        "Read the relevant pages and summarize them.",
        "Find current information about this subject.",
    ],
    "safety_guard": [
        "Check whether this action is safe.",
        "Run a safety check on this request.",
        "Is this operation allowed?",
        "Assess the risk of this action.",
        "Should Freya block this dangerous operation?",
    ],
    "show_capabilities": [
        "What can you do?",
        "List all registered capabilities.",
        "Show me the supported actions.",
        "What functions are enabled right now?",
        "Give me the capability summary.",
    ],
    "show_goals": [
        "Show me my goals.",
        "What objectives am I tracking?",
        "List my current goals.",
        "Which goals are still active?",
        "Display the goals I created.",
    ],
    "show_identity": [
        "Who are you?",
        "Tell me your identity.",
        "What is your name and role?",
        "Which assistant am I speaking with?",
        "Describe who you are.",
    ],
    "show_memory": [
        "What do you remember?",
        "Show the memories you have stored.",
        "What facts have you retained about me?",
        "Review our saved conversation memory.",
        "Tell me what is in memory.",
    ],
    "show_tasks": [
        "Show my active tasks.",
        "What tasks are currently running?",
        "List my pending work.",
        "Which jobs are active?",
        "Display the tasks in progress.",
    ],
    "simulation_capability": [
        "Simulate what happens if this service fails.",
        "Model the outcome of this scenario.",
        "Compare these possible scenarios.",
        "Run a failure simulation.",
        "Should we simulate this situation before acting?",
    ],
    "system_monitoring": [
        "Check system health and metrics.",
        "Monitor the performance of the computer.",
        "Show current CPU and memory metrics.",
        "Run a system health check.",
        "Is any component unhealthy right now?",
    ],
    "system_status": [
        "What is the current system status?",
        "Is Freya ready and healthy?",
        "Show the backend status.",
        "Is the service running normally?",
        "Give me a status report.",
    ],
    "tool_dispatch": [
        "Run the registered tool.",
        "Execute this tool action.",
        "Dispatch the request to the selected tool.",
        "Use the existing tool manager to perform this.",
        "Invoke the approved tool.",
    ],
    "tool_registry": [
        "List the available tools and their metadata.",
        "Show the registered tools.",
        "What tools are installed?",
        "Inspect the tool registry.",
        "Which tools can be dispatched?",
    ],
    "video": [
        "Analyze this local video.",
        "Inspect the video file.",
        "Trim the beginning of this video.",
        "Extract the audio from this movie.",
        "Resize the video and export it.",
    ],
    "vision": [
        "Inspect what is in this image.",
        "Read the text in this picture.",
        "Analyze the visual contents of the screenshot.",
        "Extract fields from this image.",
        "Describe what you see in the image.",
    ],
    "voice": [
        "Speak this response aloud.",
        "Read this text out loud.",
        "Convert this response to speech.",
        "Say this message aloud.",
        "Transcribe this voice recording.",
    ],
}


@pytest.fixture(scope="module")
def live_router():
    app = FreyaApp(Path.cwd())
    app.start()
    try:
        yield app.system.facade._control._router
    finally:
        app.shutdown()


@pytest.mark.parametrize(
    "capability,prompt",
    [(name, prompt) for name, prompts in ROUTING_VARIANTS.items() for prompt in prompts],
)
def test_natural_language_variants_select_capability(live_router, capability, prompt):
    route = live_router.route(prompt)
    assert route.capability_name == capability, {
        "prompt": prompt,
        "expected": capability,
        "actual": route.capability_name,
        "reason": route.reason,
    }
