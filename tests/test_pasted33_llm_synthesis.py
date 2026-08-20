from app.research.intelligence import RequestSemanticAnalyzer, SynthesisEngine


FACT = {
    "claim": "The documented feature is available in the current release.",
    "evidence": "The documented feature is available in the current release, according to the readable source text.",
    "source_title": "Official documentation",
    "source_url": "https://example.com/official-docs",
    "source_role": "OFFICIAL_DOCUMENTATION",
    "confidence": 0.9,
}
CITATIONS = [{"title": "Official documentation", "url": "https://example.com/official-docs"}]


def _generated_answer(prompt):
    assert "Grounding rules" in prompt
    assert "request_semantics" in prompt
    return "The documented feature is available in the current release."


def _run_generated(monkeypatch, query):
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(_generated_answer))
    semantic = RequestSemanticAnalyzer.analyze(query)
    result = SynthesisEngine.synthesize(semantic, [FACT], [{"url": FACT["source_url"]}], [], CITATIONS)
    answer = SynthesisEngine.attach_inline_citations(result["answer"], [FACT], CITATIONS)
    assert result["answer"] == "The documented feature is available in the current release."
    assert result["answer_source"] == "llm"
    assert "[1]" in answer
    assert "https://example.com/official-docs" in answer
    assert "Sources:" in answer


def test_factual_shape_uses_local_llm_and_resolves_citations(monkeypatch):
    _run_generated(monkeypatch, "What is the documented feature?")


def test_comparison_shape_uses_local_llm_and_resolves_citations(monkeypatch):
    _run_generated(monkeypatch, "Compare Playwright and Selenium for browser automation.")


def test_news_shape_uses_local_llm_and_resolves_citations(monkeypatch):
    _run_generated(monkeypatch, "What are the latest developments affecting grocery prices?")


def test_review_shape_uses_local_llm_and_resolves_citations(monkeypatch):
    _run_generated(monkeypatch, "What do reviews say about the documented feature?")


def test_specification_shape_uses_local_llm_and_resolves_citations(monkeypatch):
    _run_generated(monkeypatch, "What are the specifications of the documented feature?")


def test_insufficient_evidence_does_not_call_llm_or_paper_over_gap(monkeypatch):
    called = []
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: called.append(prompt) or "invented answer"))
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    result = SynthesisEngine.synthesize(semantic, [], [], [], [])
    assert not called
    assert "could not verify enough" in result["answer"].lower()
    assert "invented answer" not in result["answer"]


def test_llm_timeout_falls_back_to_existing_template(monkeypatch):
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: None))
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    expected = SynthesisEngine._template_answer(semantic, [FACT])
    result = SynthesisEngine.synthesize(semantic, [FACT], [], [], CITATIONS)
    assert result["answer"] == expected
    assert result["answer"]


def test_prompt_contains_only_structured_research_inputs(monkeypatch):
    prompts = []
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: prompts.append(prompt) or "The documented feature is available in the current release."))
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    SynthesisEngine.synthesize(semantic, [FACT], [{"url": FACT["source_url"]}], [], CITATIONS)
    assert len(prompts) == 1
    assert "Official documentation" in prompts[0]
    assert "outside knowledge" in prompts[0]
    assert "internal field names" in prompts[0]


def test_priority_provider_timeout_uses_template_fallback(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class TimeoutProvider:
        def ask_outcome(self, prompt, system, priority, timeout):
            calls.append((prompt, priority, timeout))
            return SimpleNamespace(is_success=False, reason="Provider timeout")

    monkeypatch.setattr("app.core.priority_llm.get_priority_llm", lambda: TimeoutProvider())
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    expected = SynthesisEngine._template_answer(semantic, [FACT])
    result = SynthesisEngine.synthesize(semantic, [FACT], [], [], CITATIONS)
    assert result["answer"] == expected
    assert calls
    assert calls[0][2] == SynthesisEngine.LLM_SYNTHESIS_TIMEOUT_SECONDS


def test_unsupported_generated_prose_falls_back_to_template(monkeypatch):
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: "The moon is made of cheese and this unrelated claim is certain."))
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    expected = SynthesisEngine._template_answer(semantic, [FACT])
    result = SynthesisEngine.synthesize(semantic, [FACT], [], [], CITATIONS)
    assert result["answer"] == expected
    assert result["answer_source"] == "template"
