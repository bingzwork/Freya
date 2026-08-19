# Mature AI Response Pattern Audit for Pasted30

## Scope

This audit studies publicly inspectable implementation patterns rather than private prompts or hidden proprietary systems. The selected systems are GPT Researcher, LangChain Open Deep Research, LangChain Local Deep Researcher, and Haystack’s ranking pipeline guidance.

## Systems studied

| System | Relevant observable pattern | Freya-compatible lesson |
|---|---|---|
| GPT Researcher | Separates planning, execution/crawling, source tracking, and report publication; supports multiple sources, smart image scraping/filtering, JavaScript-enabled scraping, memory/context, and real-time progress. [1] | Keep Freya’s canonical capability, but make planning, candidate discovery, validation, synthesis, and safe progress observable as structured stages. |
| LangChain Open Deep Research | Uses configurable research, summarization, compression, and final-report stages; supports multiple search tools and MCP; exposes evaluation through a fixed benchmark and structured configuration. [2] | Add explicit bounded stages and a permanent benchmark without replacing Freya’s local model or creating a second orchestrator. |
| LangChain Local Deep Researcher | Generates a query, retrieves sources, summarizes, reflects on knowledge gaps, generates a follow-up query, and repeats for a bounded number of cycles; saves sources and a final cited summary. [3] | Add coverage-gap detection and targeted query expansion instead of stopping after the first weak pass. |
| Haystack | Separates retrieval, ranking, and answer generation. Rankers use semantic, metadata, freshness, diversity, or heuristic signals after retrieval and before answer generation. [4] | Treat provider results as candidates, then validate/rank/deduplicate before response composition. Keep ranking transparent and bounded. |

## Patterns adopted

Freya adopts the common sequence `understand → plan → retrieve → evaluate coverage → follow up → validate → compose`. It also adopts result-type separation: image requests return image assets, shopping requests return product evidence, comparison requests return a comparison, and research requests return synthesized claims with provenance.

Freya adopts explicit operational metrics such as requested count, candidate count, validated count, duplicates, rejected mismatches, broken assets, source count, provider attempts, and stopping reason. These are safe activity metrics, not hidden reasoning.

Freya adopts fixed response-quality evaluation across intent satisfaction, evidence, freshness, coverage, relevance, count compliance, uncertainty, readability, and follow-up continuity. This supports measurable before/after improvement.

## Patterns deliberately rejected

Freya does not clone or install any external system. It does not create a second research capability, second router, second memory owner, or second workflow orchestrator. It does not copy private hosted-assistant prompts or claim parity with proprietary systems.

Freya does not treat a source count as proof of correctness, does not let historical source reputation override current evidence, does not use unbounded crawling, and does not use raw provider results as the final answer.

## Implementation boundary

The Pasted30 implementation extends Freya’s existing `RequestSemanticModel`, `ResearchCapability`, `WebResearchAdapter`, `FreeImageResearchChain`, `image_results` contract, Activity events, and frontend response rendering. Existing SafetyGate, BrowserCapability, LearningPipeline, MemoryCoordinator, and multimodal attachment-role boundaries remain canonical.

## References

[1]: https://github.com/assafelovic/gpt-researcher "GPT Researcher official repository"
[2]: https://github.com/langchain-ai/open_deep_research "LangChain Open Deep Research official repository"
[3]: https://github.com/langchain-ai/local-deep-researcher "LangChain Local Deep Researcher official repository"
[4]: https://docs.haystack.deepset.ai/docs/choosing-the-right-ranker "Haystack Choosing the Right Ranker"
