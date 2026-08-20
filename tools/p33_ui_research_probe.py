import json
import time
from pathlib import Path
import requests

CASES = [
    ("factual", "What is the latest stable version of Python?"),
    ("comparison", "Compare Playwright and Selenium for browser automation."),
    ("news", "What are the latest developments affecting grocery prices?"),
]
rows = []
for name, prompt in CASES:
    started = time.monotonic()
    try:
        response = requests.post("http://127.0.0.1:8787/api/chat", json={"message": prompt}, timeout=240)
        payload = response.json()
        rows.append({"name": name, "prompt": prompt, "status": response.status_code, "elapsed_seconds": round(time.monotonic() - started, 2), "answer": payload.get("answer", ""), "response_type": payload.get("response_type", ""), "research_queries": payload.get("research_queries", []), "semantic": payload.get("multimodal_semantic", {})})
    except Exception as error:
        rows.append({"name": name, "prompt": prompt, "status": 599, "elapsed_seconds": round(time.monotonic() - started, 2), "error": str(error)})
Path("outputs/p33_ui_research_probe.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
for row in rows:
    print(json.dumps({"name": row["name"], "status": row["status"], "elapsed_seconds": row["elapsed_seconds"], "response_type": row.get("response_type"), "answer": row.get("answer", "")[:1200]}, ensure_ascii=False))
