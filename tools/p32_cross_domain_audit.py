import json
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8787/api/chat"
CASES = [
    ("greeting", "Hello Freya, what can you help me with?"),
    ("factual_maker", "Who makes the RTX 5090?"),
    ("causal_market", "Why are RAM prices so expensive now?"),
    ("current_version", "What is the latest stable version of Python?"),
    ("specifications", "Search the web for the official NVIDIA RTX 5060 specifications."),
    ("software_repository", "How does the FastAPI library handle middleware? Check the repository."),
    ("comparison", "Compare AMD Ryzen 7 5700X and Intel Core i5-14400 for gaming and productivity."),
    ("shopping", "Find the cheapest matching 32 GB DDR5 RAM in the Philippines."),
    ("news", "What are the latest developments affecting NVIDIA GPU prices?"),
    ("counted", "Give me 5 reliable alternatives to Ollama."),
    ("recommendation", "What is the best browser automation approach for Freya and why?"),
    ("claim_verification", "Find reliable sources supporting the claim that browser automation can be blocked by CAPTCHAs."),
    ("troubleshooting", "Why does Freya's browser search return no readable pages?"),
    ("ambiguous", "Find the best one."),
    ("correction", "That's wrong; use the official source and correct the version."),
]

results = []
for name, prompt in CASES:
    started = time.monotonic()
    try:
        response = requests.post(BASE, json={"message": prompt}, timeout=180)
        payload = response.json()
        results.append({
            "name": name,
            "prompt": prompt,
            "status": response.status_code,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "answer": payload.get("answer", ""),
            "response_type": payload.get("response_type", ""),
            "semantic": payload.get("multimodal_semantic", {}),
            "research_queries": payload.get("research_queries", []),
            "sources": payload.get("sources", []),
            "image_count": len(payload.get("image_results") or []),
        })
    except Exception as exc:
        results.append({"name": name, "prompt": prompt, "status": 599, "elapsed_seconds": round(time.monotonic() - started, 2), "error": str(exc)})
    print(json.dumps(results[-1], ensure_ascii=False))

out = Path("outputs/p32_cross_domain_audit.json")
out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
