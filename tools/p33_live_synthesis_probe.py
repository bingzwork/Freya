import json
from pathlib import Path
from app.research.intelligence import RequestSemanticAnalyzer, SynthesisEngine

FACTS = [{
    "claim": "The documented feature is available in the current release.",
    "evidence": "The documented feature is available in the current release, according to the readable source text.",
    "source_title": "Official documentation",
    "source_url": "https://example.com/official-docs",
    "source_role": "OFFICIAL_DOCUMENTATION",
    "confidence": 0.9,
}]
CITATIONS = [{"title": "Official documentation", "url": "https://example.com/official-docs"}]
CASES = [
    ("factual", "What is the documented feature?"),
    ("comparison", "Compare Playwright and Selenium for browser automation."),
    ("news", "What are the latest developments affecting grocery prices?"),
    ("review", "What do reviews say about the documented feature?"),
    ("specification", "What are the specifications of the documented feature?"),
]
rows = []
for name, query in CASES:
    semantic = RequestSemanticAnalyzer.analyze(query)
    template = SynthesisEngine._template_answer(semantic, FACTS)
    result = SynthesisEngine.synthesize(semantic, FACTS, [{"url": FACTS[0]["source_url"]}], [], CITATIONS)
    answer = SynthesisEngine.attach_inline_citations(result["answer"], FACTS, CITATIONS)
    rows.append({"name": name, "query": query, "intent": semantic.intent, "template": template, "answer": answer, "used_template_shape": result["answer"] == template})
Path("outputs/p33_live_synthesis_probe.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
for row in rows:
    print(json.dumps({"name": row["name"], "intent": row["intent"], "used_template_shape": row["used_template_shape"], "answer": row["answer"][:700]}, ensure_ascii=False))
