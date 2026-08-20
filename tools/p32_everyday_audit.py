import json
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8787/api/chat"
CASES = [
    ("bill_explanation", "Can you explain why my electricity bill might have gone up this month?"),
    ("polite_email", "Help me write a polite email to my landlord about a leaking faucet."),
    ("trip_planning", "Plan a relaxed three-day family trip to Cebu with a moderate budget."),
    ("current_costs", "What are the latest developments affecting grocery prices?"),
    ("gift_recommendation", "What is a thoughtful birthday gift for a ten-year-old who likes drawing?"),
    ("wifi_troubleshooting", "Why is my home Wi-Fi slow even when the signal looks strong?"),
    ("dinner_count", "Give me 5 easy weeknight dinner ideas."),
    ("appliance_choice", "Which is better for a small apartment: an air purifier or a dehumidifier?"),
    ("browser_recommendation", "What is the best browser automation approach for Freya and why?"),
    ("followup_without_context", "What about the cheaper option?"),
]

results = []
for name, prompt in CASES:
    started = time.monotonic()
    try:
        response = requests.post(BASE, json={"message": prompt}, timeout=180)
        payload = response.json()
        item = {
            "name": name,
            "prompt": prompt,
            "status": response.status_code,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "answer": payload.get("answer", ""),
            "response_type": payload.get("response_type", ""),
            "semantic": payload.get("multimodal_semantic", {}),
            "research_queries": payload.get("research_queries", []),
            "image_count": len(payload.get("image_results") or []),
        }
    except Exception as exc:
        item = {"name": name, "prompt": prompt, "status": 599, "elapsed_seconds": round(time.monotonic() - started, 2), "error": str(exc)}
    results.append(item)
    print(json.dumps(item, ensure_ascii=False))

Path("outputs/p32_everyday_audit.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
