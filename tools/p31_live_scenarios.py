import json
import time
from pathlib import Path
import requests

BASE = "http://127.0.0.1:8787/api/chat"
SCENARIOS = [
    ("normal", "Hello Freya, what can you help me with?"),
    ("factual", "Who makes the RTX 5090?"),
    ("current", "What's the latest stable version of Python?"),
    ("web", "Search the web for the official NVIDIA RTX 5060 specifications."),
    ("research", "Research the public work of a named author from reliable sources."),
    ("comparison", "ryzen 7 5700x vs i5 14400"),
    ("recommendation", "Which local model should I use for Freya and why?"),
    ("shopping", "Find me the cheapest matching 32 GB DDR5 RAM in the Philippines."),
    ("troubleshooting", "Why does Freya's browser search return no readable pages?"),
    ("software", "How does the FastAPI library handle middleware? Check the repository."),
    ("counted", "Give me 5 reliable alternatives to Ollama."),
    ("image", "find me 10 photos of River Lynn"),
    ("followup", "show me 5 more"),
    ("correction", "That's wrong; use the official source and correct the version."),
    ("ambiguous", "Find the best one."),
    ("no_result", "Find reliable public images of a nonexistent entity with no public record."),
    ("conflict", "Which source is correct when two official pages list different release dates?"),
]

out = Path("outputs/p31_live_scenarios.jsonl")
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", encoding="utf-8") as handle:
    for name, prompt in SCENARIOS:
        started = time.monotonic()
        record = {"name": name, "prompt": prompt}
        try:
            response = requests.post(BASE, json={"message": prompt, "attachments": []}, timeout=240)
            record["status"] = response.status_code
            record["elapsed_seconds"] = round(time.monotonic() - started, 2)
            try:
                payload = response.json()
                record["answer"] = payload.get("answer", "")
                record["response_type"] = payload.get("response_type", "")
                record["requested_count"] = payload.get("requested_count")
                record["semantic"] = payload.get("multimodal_semantic", {})
                record["comparison"] = payload.get("comparison")
                record["image_count"] = len(payload.get("image_results") or [])
                record["image_metrics"] = payload.get("image_search_metrics")
            except Exception as exc:
                record["parse_error"] = repr(exc)
                record["raw"] = response.text[:12000]
        except Exception as exc:
            record["status"] = 0
            record["elapsed_seconds"] = round(time.monotonic() - started, 2)
            record["error"] = repr(exc)
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        print(json.dumps({"name": name, "status": record.get("status"), "elapsed": record.get("elapsed_seconds"), "response_type": record.get("response_type"), "image_count": record.get("image_count")}, ensure_ascii=False))
