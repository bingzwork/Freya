import json
from pathlib import Path
import requests

prompts = [
    "My laptop fan is making a loud noise. What should I do?",
    "Why does my phone battery drain so fast?",
    "My Wi-Fi keeps disconnecting every few minutes. How can I troubleshoot it?",
]
results = []
for prompt in prompts:
    response = requests.post("http://127.0.0.1:8787/api/chat", json={"message": prompt}, timeout=240)
    payload = response.json()
    results.append({
        "prompt": prompt,
        "status": response.status_code,
        "response_type": payload.get("response_type"),
        "answer": payload.get("answer", ""),
        "semantic": payload.get("multimodal_semantic", {}),
    })
Path("outputs/p34_everyday_troubleshooting_probe.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
for result in results:
    print(json.dumps(result, ensure_ascii=False))
