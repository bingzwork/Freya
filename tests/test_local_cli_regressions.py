from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
from app.capabilities.handlers import handle_capability_introspection, handle_show_capabilities
from app.memory.project_memory import ProjectMemory
from app.verification.answer_verifier import AnswerVerifier

def _registry(*names):
    capabilities = {}
    for name in names:
        metadata = SimpleNamespace(name=name, description=f"{name} description", category=SimpleNamespace(value="tool"), tags=[name], supported_actions=["execute"])
        capabilities[name] = SimpleNamespace(metadata=metadata)
    return SimpleNamespace(get_all=lambda: capabilities)

def test_capability_list_uses_live_registry_details():
    result = handle_show_capabilities({"capability_registry": _registry("runtime_demo")})
    assert result.data["count"] == 1
    assert result.data["capabilities"][0]["name"] == "runtime_demo"
    assert "runtime_demo" in result.message

def test_capability_introspection_uses_live_registry():
    result = handle_capability_introspection({"query": "Can you use runtime demo?", "capability_registry": _registry("runtime_demo")})
    assert result.data["supported"] is True
    assert "runtime_demo" in result.message

def test_authoritative_internal_evidence_is_accepted():
    verifier = AnswerVerifier()
    check = verifier._check_claims_against_local_evidence("Freya was created by Don Alvin Jalop.", {"authoritative_internal": True, "authoritative_evidence": [{"source": "identity", "content": "Freya was created by Don Alvin Jalop."}]})
    assert check.is_grounded is True

def test_project_memory_concurrent_atomic_saves_are_serialized(tmp_path):
    memory = ProjectMemory.__new__(ProjectMemory)
    memory.path = tmp_path / "data" / "memory" / "freya_memory.json"
    memory.file_allowlist = SimpleNamespace(require_allowed=lambda *args: None)
    entries = [{"kind": "concurrent", "content": {"value": "ok"}}]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: memory._save(entries), range(16)))
    assert json.loads(memory.path.read_text(encoding="utf-8")) == entries
