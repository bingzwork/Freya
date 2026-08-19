import json
import re
import subprocess
from pathlib import Path

from app.research.intelligence import RequestSemanticAnalyzer


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "WEB_RESPONSE_QUALITY_BENCHMARK.json"
OUTPUT = ROOT / "outputs" / "p30_baseline.json"


def requested_count(prompt: str):
    match = re.search(r"\b(?:give|find|show|send|return|list|top)\s+(\d+)\b|\b(\d+)\s+(?:photos?|images?|options?|alternatives?|results?)\b", prompt, re.I)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))


def main():
    records = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    results = []
    for record in records:
        model = RequestSemanticAnalyzer.analyze(record["prompt"], context={})
        actual_count = getattr(model, "requested_count", None)
        expected_count = record.get("requested_count")
        failures = []
        if model.intent != record["expected_intent"]:
            failures.append("INTENT_MISMATCH")
        if model.execution_mode != record["expected_mode"]:
            failures.append("MODE_MISMATCH")
        if expected_count is not None and actual_count != expected_count:
            failures.append("REQUESTED_COUNT_UNSUPPORTED")
        if record["freshness"] in {"latest", "current"} and not getattr(model, "freshness", ""):
            failures.append("FRESHNESS_METADATA_MISSING")
        expected_type = str(record.get("expected_result_type") or "")
        actual_type = str(getattr(model, "response_type", "") or getattr(model, "output_goal", ""))
        exempt_types = {"no_result", "correction_or_verified_answer", "conflict_explanation"}
        compatible_types = {"research_synthesis": {"research_synthesis", "deep_synthesis"}, "direct_answer": {"direct_answer", "specifications"}}
        allowed_types = compatible_types.get(expected_type, {expected_type})
        if expected_type not in exempt_types and actual_type not in allowed_types:
            failures.append("RESPONSE_TYPE_MISMATCH")
        if expected_type == "image_results" and model.output_goal != "image_results":
            failures.append("IMAGE_RESULT_CONTRACT_MISMATCH")
        results.append({
            "id": record["id"],
            "prompt": record["prompt"],
            "expected": {"intent": record["expected_intent"], "mode": record["expected_mode"], "count": expected_count, "result_type": record["expected_result_type"]},
            "actual": {"intent": model.intent, "mode": model.execution_mode, "operation": model.operation, "output_goal": model.output_goal, "response_type": actual_type, "count": actual_count, "freshness": getattr(model, "freshness", ""), "entities": list(model.entities), "requested_domain": model.requested_domain},
            "failures": failures,
        })
    try:
        implementation_commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        implementation_commit = "working-tree"
    summary = {
        "benchmark": str(BENCHMARK.name),
        "implementation_commit": implementation_commit or "working-tree",
        "case_count": len(results),
        "passed_cases": sum(1 for item in results if not item["failures"]),
        "failed_cases": sum(1 for item in results if item["failures"]),
        "failure_counts": {name: sum(name in item["failures"] for item in results) for name in sorted({failure for item in results for failure in item["failures"]})},
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("case_count", "passed_cases", "failed_cases", "failure_counts")}, indent=2))


if __name__ == "__main__":
    main()
