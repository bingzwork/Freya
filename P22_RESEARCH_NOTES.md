# Pasted22 Research Notes (working document)

## Primary repositories inspected

| Project | URL | Evidence collected |
|---|---|---|
| Browser Use | https://github.com/browser-use/browser-use | Mature maintained browser automation project with a large active repository, a dedicated `browser_use` source tree, examples, tests, documentation, releases, and explicit browser-agent/session infrastructure. The repository’s current main branch shows release `0.13.8` dated Aug. 16, 2026 and a substantial contributor/dependent base. |
| LangChain Open Deep Research | https://github.com/langchain-ai/open_deep_research | Open-source deep research implementation with current `src`, examples, tests, LangGraph configuration, and a `src/legacy/` folder documenting earlier workflow and multi-agent approaches. The README presents a staged research flow separating user clarification/brief generation, research, and report writing. |

## Browser Use findings to validate in source files

Browser Use is relevant as a **web-mechanics reference and optional adapter target**, not as a replacement controller for Freya. The repository areas to inspect further are its browser/session lifecycle, state or DOM representation, action models, extraction/observation utilities, profiles, screenshots/downloads/uploads, and recovery/retry behavior. The key architectural lesson for Freya is to improve browser observations and mechanics behind `BrowserCapability` while keeping Freya’s `CapabilityRouter`, `SafetyGate`, `PlaywrightBrowserAdapter` lifecycle, and local model ownership authoritative.

## Open Deep Research findings to validate in source files

Open Deep Research is relevant as a **bounded research-loop reference**, not as a second Freya planner/router. The README indicates a staged separation between user clarification/brief generation, research, and report writing. Its current implementation should be inspected for query decomposition, iterative source discovery, stateful findings, source selection, and stopping rules. The legacy folder explicitly contrasts a plan-and-execute workflow and a supervisor/researcher multi-agent architecture; these should be treated as ideas to selectively adapt, not architectures to import wholesale.

## Freya production findings

Freya already has canonical owners and contracts:

1. `ResearchCapability` owns public-web search, page reading, source evaluation, fact extraction, cross-reference, citations, shopping normalization/listing extraction, and image-result payloads.
2. `BrowserCapability` owns browser actions and delegates mechanics to `PlaywrightBrowserAdapter`; consequential actions are checked by the existing `SafetyGate`.
3. `KnowledgeFirstResolver` is the precise seam for choosing a research action. It currently routes fresh/explicit external requests to `research_capability`, selecting only `research_topic` or `verify_claim`.
4. `FreeImageResearchChain` already provides browser-backed reverse-image providers plus public image search and page-image extraction. Its result contract uses `image_results` and preserves source-page URLs and provider metadata.
5. `InternetResearchImporter` still owns hand-maintained DuckDuckGo/Bing HTML parsing and generic BeautifulSoup page extraction. Its active `search()` path returns early before a second legacy DuckDuckGo parser block, confirming brittle and dead duplicate parsing code.

## Initial adapter direction

The safest likely implementation is a small Freya-owned adapter layer that:

- exposes explicit `FAST_SEARCH`, `DEEP_RESEARCH`, and `IMAGE_SEARCH` mode metadata;
- keeps `ResearchCapability` as the registry-facing owner;
- keeps `BrowserCapability` and `PlaywrightBrowserAdapter` as the browser boundary;
- replaces or wraps brittle provider-specific search/page extraction only behind the existing `WebSearchTool`/`WebPageReader` seams;
- adds a bounded, evidence-preserving deep-research loop that reuses current `action_search_web`, `action_read_page`, `SourceEvaluator`, `FactExtractor`, `CrossReference`, and `CitationManager` rather than adding a planner or agent;
- preserves shopping constraints, `image_results`, SafetyGate, local-first routing, and existing UI formatter contracts.

## Sources

[1]: https://github.com/browser-use/browser-use
[2]: https://github.com/langchain-ai/open_deep_research
[3]: https://docs.browser-use.com/open-source/customize/agent/all-parameters

## Implementation-level findings

### Browser Use

The current Browser Use source separates a stateful `BrowserSession` from higher-level agent behavior. The session owns browser configuration/profile, targets/tabs, lifecycle events, navigation, reconnection-oriented event handling, cookies/storage, and page/session state. Its DOM layer models enhanced DOM nodes and serialized DOM state, including an LLM representation and an evaluation representation; the serializer maintains stable element identity/indices and can include scroll information. Watchdogs cover DOM updates, crashes, CAPTCHA/challenge states, downloads, popups, permissions, storage state, screenshots, and security. These are useful patterns for Freya’s existing adapter, but importing the complete event bus, CDP layer, agent loop, or watchdog suite would violate the requirement to keep Freya’s browser lifecycle and controller canonical.

The safe reusable subset is therefore: a structured browser observation model; stable page/tab/session metadata; bounded DOM snapshots with interactive element metadata and scroll context; explicit navigation/readiness/recovery outcomes; and optional per-operation retry classification. These can be implemented as adapter-local helpers behind `BrowserCapability` without changing `BrowserCapability.execute()` or bypassing its SafetyGate check.

### Open Deep Research

The current Open Deep Research implementation builds a graph with clear phases: optional clarification, structured research-brief generation, supervisor research, and final report generation. The supervisor increments a research-iteration counter, delegates bounded research units, caps concurrent units, gathers results, and ends when a completion signal, no-tool-call result, or maximum iteration bound is reached. Each researcher loops through tool calls with a bounded tool-call iteration count, executes tool calls in parallel, then compresses research findings. The final writer retries token-limit failures with progressively reduced findings.

The reusable ideas for Freya are not the LangGraph graph, supervisor agent, or second planner. They are explicit bounded research state and stopping conditions: research brief/questions, query/source/page/depth/step/time limits, iterative follow-up only when evidence gaps remain, deduplication, source notes retained separately from the final answer, and a final synthesis boundary. Freya already owns source evaluation, facts, cross-reference, citations, shopping constraints, and final formatting, so the adapter should feed those existing owners rather than introduce another synthesis architecture.

### Design consequence

Pasted22 should begin with a focused, Freya-owned `WebResearchAdapter` or equivalent service that abstracts search/page retrieval and a bounded deep-research coordinator that invokes existing `ResearchCapability` stages. It should not copy Browser Use or Open Deep Research wholesale, add LangChain/LangGraph dependencies, or create a second router/planner/memory/autonomy system.

## Additional maintained retrieval component

Trafilatura is a focused, actively maintained Python extraction library rather than an agent framework. Its project documentation describes main-text extraction, metadata, headings/lists/quotes/code, links, images, tables, RSS/Atom/JSON feeds, URL filtering/deduplication, and multiple output formats. The repository is actively maintained and supports modern Python versions. It is a strong candidate for a thin page-reader adapter because it directly replaces Freya’s generic BeautifulSoup main-content heuristics without owning routing or synthesis.

The `ddgs` package is a maintained Python metasearch library. Its current PyPI release is `9.15.0`, requires Python >=3.10, and exposes text search across multiple engines plus a dedicated `images()` method for Bing/DuckDuckGo image search and `extract()` support. It is a plausible optional search/image provider behind a provider pool, but its live engine availability and Windows behavior must be verified before making it canonical. The adapter must retain Freya’s public URL validation, domain constraints, evidence normalization, and fallback behavior.

## Dependency decision at audit stage

Do not add Browser Use or LangChain/Open Deep Research as runtime dependencies: both would introduce large alternate agent/controller stacks and are not required to preserve Freya’s local model and canonical routing. Prefer adapting the bounded research patterns only. A small, pinned extraction/search dependency may be justified if installed and tested on Freya’s Python/Windows environment; otherwise the adapter must degrade to the existing providers without faking success.

Potential candidates to verify before implementation:

| Component | Candidate role | Current decision |
|---|---|---|
| Trafilatura | Main-page extraction and metadata | Strong candidate for optional canonical page-reader backend |
| DDGS | Text/news/image provider pool | Candidate; verify install, runtime, and real results before enabling |
| Browser Use | DOM/session/action reference | Study patterns only; do not add as controller |
| Open Deep Research | Bounded research-loop patterns | Adapt concepts only; do not add LangGraph or second agent |


## Final implementation observations

The selected design was implemented without importing either external agent framework. `app/research/web_adapter.py` now provides Freya-owned normalized provider contracts, bounded limits, explicit `ResearchMode` values, DDGS text/image adapters, Trafilatura page extraction, deterministic query planning, evidence-gap follow-ups, deduplication, and stopping metadata. `ResearchCapability` remains the canonical registry-facing owner and retains its existing importer/browser fallback paths.

The live Windows environment verified `ddgs==9.15.0` and `trafilatura==2.0.0`; the repository venv passed editable installation and `pip check`. Real acceptance returned current text sources, multi-source deep research, GALAX RTX 5060 image cards, browser actions, shopping comparisons, hard Shopee constraints, and safe no-winner refusals. Provider variability remains visible as honest partial/unavailable outcomes.

The final Pasted22 regression file contains 11 tests. The combined focused routing, live-path, shopping, research, and Pasted22 suite passed 51 tests in the final run. The production Windows Playwright acceptance recorded no browser console errors.
