import json
from pathlib import Path
import requests

cases = [
    ("greeting", "Hello Freya, what can you help me with?"),
    ("factual", "Who makes the RTX 5090?"),
    ("current", "What's the latest stable version of Python?"),
    ("official", "Search the web for the official NVIDIA RTX 5060 specifications."),
    ("missing_subject", "Research the public work of a named author from reliable sources."),
    ("comparison", "ryzen 7 5700x vs i5 14400"),
]
records=[]
for name, prompt in cases:
    try:
        response=requests.post("http://127.0.0.1:8787/api/chat", json={"message":prompt,"attachments":[]}, timeout=240)
        payload=response.json()
        records.append({"name":name,"prompt":prompt,"status":response.status_code,"answer":payload.get("answer",""),"response_type":payload.get("response_type"),"semantic":payload.get("multimodal_semantic",{}),"comparison":payload.get("comparison"),"research_queries":payload.get("research_queries",[])})
    except Exception as exc:
        records.append({"name":name,"prompt":prompt,"status":0,"error":repr(exc)})
Path("outputs/p31_recheck.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
for record in records:
    print(json.dumps({"name":record["name"],"status":record.get("status"),"response_type":record.get("response_type"),"answer":record.get("answer","")[:350]},ensure_ascii=False))
