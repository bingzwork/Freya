import json
from pathlib import Path
import requests

prompt = "pc suddenly cant detect my Bootmanager, but SSD is detected"
response = requests.post("http://127.0.0.1:8787/api/chat", json={"message": prompt}, timeout=240)
payload = response.json()
result = {
    "status": response.status_code,
    "answer": payload.get("answer", ""),
    "response_type": payload.get("response_type", ""),
    "research_queries": payload.get("research_queries", []),
    "semantic": payload.get("multimodal_semantic", {}),
}
Path("outputs/p34_bootmanager_probe.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
