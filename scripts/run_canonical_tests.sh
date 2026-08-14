#!/usr/bin/env bash
# Install Freya as a package, then execute the focused canonical-runtime suite.
# This command intentionally does not set PYTHONPATH.
set -euo pipefail

python3 -m pip install --disable-pip-version-check ".[dev]"
python3 -m pytest \
  tests/test_clean_process_runtime.py \
  tests/test_target_architecture_contracts.py \
  tests/test_target_architecture_behavior.py \
  tests/test_workflow_capability_safety.py \
  tests/test_shared_event_improvement_flow.py \
  tests/test_safe_self_improvement_workflow.py \
  tests/test_task5_execution_learning.py \
  tests/test_capability_routing.py \
  tests/test_execution_safety_state_machine.py \
  tests/test_learning_repair_policy.py \
  tests/test_priority_llm_outcomes.py
