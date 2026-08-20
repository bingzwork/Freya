import json

from app.research.intelligence import GroundedAnswer, RequestSemanticAnalyzer, SynthesisEngine


FACT = {
    "claim": "The service supports the requested feature in the current release.",
    "evidence": "The service supports the requested feature in the current release according to the readable official documentation.",
    "source_title": "Official documentation",
    "source_url": "https://example.com/docs",
    "source_role": "OFFICIAL_DOCUMENTATION",
    "confidence": 0.95,
}


def test_structured_local_writer_becomes_canonical_grounded_answer(monkeypatch):
    def generated(prompt):
        return json.dumps({
            "answer_paragraphs": ["The service supports the requested feature in the current release."],
            "steps": [],
            "claims": [{"text": "The service supports the requested feature in the current release.", "evidence_ids": ["fact-1"]}],
            "uncertainties": [],
            "follow_up_questions": [],
        })

    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(generated))
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    result = SynthesisEngine.synthesize(semantic, [FACT], [{"url": FACT["source_url"]}], [], [{"title": FACT["source_title"], "url": FACT["source_url"]}])
    grounded = GroundedAnswer(**result["grounded_answer"])
    assert grounded.answer == "The service supports the requested feature in the current release."
    assert grounded.evidence_state == "VERIFIED"
    assert grounded.answer_source == "llm"
    assert grounded.claims
    assert grounded.claims[0]["evidence_ids"] == ["fact-1"]


def test_search_snippets_are_not_promoted_to_final_facts(monkeypatch):
    calls = []
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: calls.append(prompt) or "invented"))
    semantic = RequestSemanticAnalyzer.analyze("What is the documented feature?")
    snippet = dict(FACT, snippet_only=True)
    result = SynthesisEngine.synthesize(semantic, [snippet], [{"url": FACT["source_url"]}], [], [])
    assert not calls
    assert result["evidence_state"] == "INSUFFICIENT"
    assert "could not verify" in result["answer"].lower()
    assert "invented" not in result["answer"]


def test_claim_binding_marks_unsupported_sentences():
    bindings = SynthesisEngine._bind_claims("The service supports the requested feature. Unrelated claim with no evidence.", [FACT])
    assert bindings
    assert any(item["supported"] for item in bindings)
    assert any(not item["supported"] for item in bindings)


def test_malformed_structured_writer_output_falls_back_cleanly(monkeypatch):
    monkeypatch.setattr(SynthesisEngine, "_invoke_llm", staticmethod(lambda prompt: '{ "answer_paragraphs": This is malformed'))
    semantic = RequestSemanticAnalyzer.analyze("Why does my phone battery drain so fast?")
    result = SynthesisEngine.synthesize(semantic, [], [], [], [])
    assert "answer_paragraphs" not in result["answer"]
    assert "could not verify" in result["answer"].lower()


def test_challenge_title_is_not_rendered_as_a_citation():
    answer = SynthesisEngine.attach_inline_citations(
        "The source-backed claim is supported.",
        [{"claim": "The source-backed claim is supported.", "source_url": "https://example.com/article"}],
        [{"title": "Attention Required! | Cloudflare", "url": "https://example.com/article"}],
    )
    assert "Cloudflare" not in answer
    assert "Sources:" not in answer
