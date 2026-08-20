import json
import time
from pathlib import Path
import requests

cases = [
    ("bill", "Can you explain why my electricity bill might have gone up this month?"),
    ("news", "What are the latest developments affecting grocery prices?"),
    ("appliance", "Which is better for a small apartment: an air purifier or a dehumidifier?"),
    ("browser", "What is the best browser automation approach for Freya and why?"),
]
rows = []
for name, prompt in cases:
    start = time.monotonic()
    try:
        r = requests.post("http://127.0.0.1:8787/api/chat", json={"message": prompt}, timeout=180)
        p = r.json()
        rows.append({"name": name, "status": r.status_code, "elapsed_seconds": round(time.monotonic()-start, 2), "answer": p.get("answer", ""), "response_type": p.get("response_type", ""), "research_queries": p.get("research_queries", []), "semantic": p.get("multimodal_semantic", {})})
    except Exception as e:
        rows.append({"name": name, "status": 599, "elapsed_seconds": round(time.monotonic()-start, 2), "error": str(e)})
Path("outputs/p32_quality_smoke.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
for row in rows:
    print(json.dumps({"name": row["name"], "status": row["status"], "elapsed_seconds": row["elapsed_seconds"], "response_type": row.get("response_type"), "answer": row.get("answer", "")[:1000]}, ensure_ascii=False))
