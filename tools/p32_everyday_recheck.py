import json
import time
from pathlib import Path
import requests

BASE = "http://127.0.0.1:8787/api/chat"
CASES = [
    ("bill", "Can you explain why my electricity bill might have gone up this month?"),
    ("email", "Help me write a polite email to my landlord about a leaking faucet."),
    ("trip", "Plan a relaxed three-day family trip to Cebu with a moderate budget."),
    ("wifi", "Why is my home Wi-Fi slow even when the signal looks strong?"),
    ("appliance", "Which is better for a small apartment: an air purifier or a dehumidifier?"),
    ("news", "What are the latest developments affecting grocery prices?"),
    ("browser", "What is the best browser automation approach for Freya and why?"),
]
results = []
for name, prompt in CASES:
    started = time.monotonic()
    try:
        response = requests.post(BASE, json={"message": prompt}, timeout=180)
        payload = response.json()
        results.append({"name": name, "prompt": prompt, "status": response.status_code, "elapsed_seconds": round(time.monotonic() - started, 2), "answer": payload.get("answer", ""), "response_type": payload.get("response_type", ""), "research_queries": payload.get("research_queries", []), "semantic": payload.get("multimodal_semantic", {})})
    except Exception as exc:
        results.append({"name": name, "prompt": prompt, "status": 599, "elapsed_seconds": round(time.monotonic() - started, 2), "error": str(exc)})
Path("outputs/p32_everyday_recheck.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
for item in results:
    print(json.dumps({"name": item.get("name"), "status": item.get("status"), "elapsed_seconds": item.get("elapsed_seconds"), "answer": item.get("answer", "")[:900], "response_type": item.get("response_type"), "research_queries": item.get("research_queries", [])}, ensure_ascii=False))
