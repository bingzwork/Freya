import json
import time
from pathlib import Path
import requests

cases = [
    ("image", "find me 10 photos of River Lynn"),
    ("image_followup", "show me 5 more"),
    ("correction_without_subject", "That's wrong; use the official source and correct the version."),
    ("ambiguous_without_subject", "Find the best one."),
    ("anaphoric_without_subject", "what about the other one"),
    ("comparison", "ryzen 7 5700x vs i5 14400"),
]
records = []
for name, prompt in cases:
    started = time.monotonic()
    record = {"name": name, "prompt": prompt}
    try:
        response = requests.post("http://127.0.0.1:8787/api/chat", json={"message": prompt, "attachments": []}, timeout=240)
        record["status"] = response.status_code
        record["elapsed_seconds"] = round(time.monotonic() - started, 2)
        payload = response.json()
        record["answer"] = payload.get("answer", "")
        record["response_type"] = payload.get("response_type", "")
        record["image_count"] = len(payload.get("image_results") or [])
        record["image_metrics"] = payload.get("image_search_metrics")
        record["comparison"] = payload.get("comparison")
    except Exception as exc:
        record["status"] = 0
        record["elapsed_seconds"] = round(time.monotonic() - started, 2)
        record["error"] = repr(exc)
    records.append(record)
    print(json.dumps({"name": name, "status": record.get("status"), "elapsed": record.get("elapsed_seconds"), "response_type": record.get("response_type"), "image_count": record.get("image_count"), "answer": str(record.get("answer", ""))[:260]}, ensure_ascii=False))
Path("outputs/p31_edge_recheck.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
