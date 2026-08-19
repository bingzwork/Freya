import json
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8787/api/chat"
CASES = [
    ("valid_image", "find me 3 photos of River Lynn"),
    ("no_result_image", "Find reliable public images of a nonexistent entity with no public record."),
]
results = []
for name, prompt in CASES:
    started = time.monotonic()
    try:
        response = requests.post(BASE, json={"message": prompt}, timeout=90)
        payload = response.json()
        results.append({
            "name": name,
            "prompt": prompt,
            "status": response.status_code,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "answer": payload.get("answer", ""),
            "response_type": payload.get("response_type", ""),
            "image_count": len(payload.get("image_results") or []),
            "metrics": payload.get("image_metrics") or {},
        })
    except Exception as exc:
        results.append({"name": name, "prompt": prompt, "status": 599, "elapsed_seconds": round(time.monotonic() - started, 2), "error": str(exc)})
out = Path("outputs/p31_image_final_recheck.json")
out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
for item in results:
    print(json.dumps(item, ensure_ascii=False))
if any(item.get("status") != 200 for item in results):
    raise SystemExit(1)
if any(item.get("name") == "no_result_image" and item.get("image_count") for item in results):
    raise SystemExit(2)
if any("Traceback" in str(item.get("answer", "")) or "DDGSException" in str(item.get("answer", "")) for item in results):
    raise SystemExit(3)
