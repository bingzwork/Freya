from app.research.intelligence import RequestSemanticAnalyzer, SynthesisEngine
from app.capabilities.formatter import ResponseFormatter


def test_boot_manager_incident_is_classified_as_troubleshooting():
    semantic = RequestSemanticAnalyzer.analyze("pc suddenly cant detect my Bootmanager, but SSD is detected")
    assert semantic.operation == "troubleshoot"
    assert semantic.response_type == "troubleshooting"
    assert semantic.output_goal == "troubleshooting"


def test_boot_manager_incident_enters_ui_troubleshooting_route():
    from ui_server import _is_troubleshooting_request
    assert _is_troubleshooting_request("pc suddenly cant detect my Bootmanager, but SSD is detected")


def test_troubleshooting_prompt_requires_safe_ordered_diagnosis():
    semantic = RequestSemanticAnalyzer.analyze("pc suddenly cant detect my Bootmanager, but SSD is detected")
    prompt = SynthesisEngine._synthesis_prompt(semantic, [{
        "claim": "The SSD is visible to firmware but no boot entry was readable.",
        "evidence": "The SSD is visible to firmware but no boot entry was readable.",
        "source_url": "https://example.com/boot",
        "source_title": "Boot documentation",
    }], [], [], [])
    assert "safe and reversible" in prompt
    assert "more invasive" in prompt
    assert "Do not infer" in prompt
    assert "destructive" in prompt


def test_weak_instruction_fragments_are_not_usable_troubleshooting_evidence():
    assert not SynthesisEngine._usable_segments({
        "claim": "Review your bill and compare it with the previous month.",
        "evidence": "Review your bill and compare it with the previous month.",
        "source_title": "Troubleshooting guide",
    })
    assert not SynthesisEngine._usable_segments({
        "claim": "Guide to the best air purifier covers exactly which models handle smoke.",
        "evidence": "Guide to the best air purifier covers exactly which models handle smoke.",
        "source_title": "Product guide",
    })


def test_challenge_and_captcha_urls_are_not_presented_as_sources():
    assert SynthesisEngine._is_redirect_url("https://forums.example.com/.stile/challenge?rung=nojs")
    assert SynthesisEngine._is_redirect_url("https://example.com/captcha?challenge=1")
    assert not SynthesisEngine._is_redirect_url("https://example.com/articles/boot-repair")
    assert ResponseFormatter._is_unusable_source_url("https://forums.example.com/.stile/challenge?rung=nojs")
    assert not ResponseFormatter._is_unusable_source_url("https://example.com/articles/boot-repair")


def test_empty_troubleshooting_evidence_returns_ordered_safe_checks(monkeypatch):
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: None))
    semantic = RequestSemanticAnalyzer.analyze("pc suddenly cant detect my Bootmanager, but SSD is detected")
    answer = SynthesisEngine.synthesize(semantic, [], [], [], [])['answer']
    assert "could not verify the exact cause" in answer
    assert "order of checks" in answer
    assert "before resetting" in answer
    assert "exact error text" in answer
    assert "what changed immediately before" in answer
    assert "based on the retrieved evidence" not in answer.lower()
    assert "Windows Boot Manager" not in answer
