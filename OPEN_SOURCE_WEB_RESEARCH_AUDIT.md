# Open-Source Web and Research Architecture Audit

## 1. Current Freya web architecture

Freya’s production path is initializer-owned and capability-routed. User conversation reaches `UnifiedRouter` and `KnowledgeFirstResolver`; stable local questions use `UnifiedRetrieval`, while fresh, explicit, shopping, verification, and public-web requests reach the canonical `ResearchCapability`. `ResearchCapability` currently owns structured search results, page records, source-quality scoring, fact extraction, cross-reference, citations, product listing normalization, marketplace constraints, and image-result payloads. `BrowserCapability` owns the public browser action interface and delegates mechanics to the existing `PlaywrightBrowserAdapter`, which already has a dedicated owner thread, session reuse, tab handling, clean shutdown, and the full public action surface. Consequential browser actions are checked by the existing `SafetyGate` before adapter execution.

The UI server adds a thin production transport layer for `/api/chat`, avatar/SSE operational events, attachment processing, browser conversational commands, shopping session state, and `image_results`. The frontend already renders image cards from the structured media contract. These healthy Freya-specific surfaces must remain canonical.

## 2. Brittle components and inventory

| Current area | Classification | Reason |
|---|---|---|
| `ResearchCapability` result/evidence/product contracts | **KEEP** | They are Freya’s canonical downstream contracts and preserve source provenance, shopping, and image behavior. |
| `BrowserCapability` public actions and SafetyGate check | **KEEP** | This is the authoritative safety and browser boundary. |
| `PlaywrightBrowserAdapter` owner-thread lifecycle and session reuse | **KEEP** | It has already repaired cross-thread Playwright behavior and must not be replaced casually. |
| `KnowledgeFirstResolver` and `CapabilityRouter` | **KEEP BUT EXTEND** | Add explicit research-mode selection at the existing research action seam; do not add another router. |
| `InternetResearchImporter.search()` DuckDuckGo/Bing HTML parsing | **REPLACE WITH ADAPTER** | Provider-specific selectors, redirect decoding, and a dead second parser block create maintenance debt. |
| `ExternalKnowledgeImporter` generic selector-based page extraction | **WRAP / REPLACE WITH ADAPTER** | Generic CSS heuristics are weaker than a maintained main-content extractor for arbitrary public pages. |
| `WebSearchTool` fallback orchestration | **WRAP / REPAIR** | Preserve bounded fallback semantics, but move provider selection and normalization behind replaceable provider interfaces. |
| `WebPageReader` | **WRAP / REPAIR** | Keep URL safety and `WebPage`; allow a maintained extractor to supply readable text and metadata, then fall back honestly. |
| `SourceEvaluator`, `FactExtractor`, `CrossReference`, `CitationManager` | **KEEP** | These are Freya-owned evidence and synthesis inputs, not web mechanics. |
| `FreeImageResearchChain` output contract | **KEEP BUT EXTEND** | Preserve `image_results`, source metadata, and exact-product safeguards while adding a provider seam and entity matching. |
| UI server research/image branching | **KEEP BUT CONSOLIDATE** | Preserve existing conversation/shopping state, but call canonical research actions with explicit modes instead of duplicating decisions. |

The largest brittle surface is not Freya’s evidence model; it is the low-level retrieval machinery: hand-maintained DuckDuckGo/Bing/Google HTML parsing, redirect handling, generic HTML selectors, and scattered fallback calls. The migration will reduce this code by moving it behind provider adapters and retiring only covered legacy parsing after verification.

## 3. Browser Use findings

[Browser Use](https://github.com/browser-use/browser-use) is a mature, actively maintained browser-automation project with separate browser-session, profile, DOM, agent, controller, tool, and watchdog areas. Its `BrowserSession` separates stateful browser lifecycle and targets/tabs from higher-level agent behavior. Its DOM service builds enhanced DOM/accessibility trees, filters visibility, handles iframes, and serializes compact LLM/evaluation representations. Its source tree also contains watchdogs for crashes, CAPTCHA/challenges, DOM changes, downloads, popups, permissions, screenshots, storage state, and security.[1]

The reusable ideas are **structured observations, stable page/tab/session metadata, compact visible/interactive representations, explicit readiness/recovery outcomes, and bounded retry classification**. Browser Use’s full CDP/event-bus/session/agent stack is not suitable as a Freya replacement because it would create a second browser controller and potentially duplicate lifecycle ownership. Freya will retain `BrowserCapability` and `PlaywrightBrowserAdapter`; any selected improvements will be small adapter-local helpers that preserve the current synchronous action contract and owner thread.

## 4. Open Deep Research findings

[LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research) separates clarification, structured research-brief generation, bounded supervisor research, researcher tool iterations, compression, and final report generation. Its current graph caps concurrent research units, increments supervisor iterations, caps researcher tool-call iterations, executes independent tool calls in parallel, retains raw notes separately from compressed findings, and exits on completion signals, missing tool calls, or configured limits. Its state models explicit research briefs, notes, raw notes, iterations, and final reports.[2]

These are useful **bounded-loop and evidence-state patterns**, not a reason to add LangGraph or a second planning/agent architecture. Freya already owns intent, routing, source quality, fact extraction, cross-checking, citations, answer formatting, memory, and SafetyGate. The implementation will adapt the following concepts in a small synchronous coordinator: research questions, query/source/page/depth/step/time budgets, gap-driven follow-up queries, source diversity, deduplication, confidence/stopping checks, and a final normalized evidence package returned to Freya synthesis.

## 5. Image-search findings

Neither Browser Use nor Open Deep Research is a complete image-search provider. Freya already has a stronger starting seam in `FreeImageResearchChain`: browser-backed reverse-image providers, public page-image extraction, public image search, optional local vision clues, deduplication, and structured `image_results`. The migration will preserve that contract and add provider-neutral normalization, entity/query matching, source-quality weighting, dimensions when available, and bounded multi-image selection. Real-world image requests remain retrieval requests; they must not invoke image generation. Exact product requests will be accepted only when brand/model/product-page/context signals meet a conservative threshold; otherwise Freya returns an honest inability to verify.

## 6. Dependency implications

Browser Use and Open Deep Research will **not** be added as runtime dependencies. They are large alternate agent/controller stacks and are not required to implement the selected mechanics. Freya’s local model, Python 3.12 Windows environment, Playwright/Chromium, and existing router remain the compatibility baseline.

[Trafilatura](https://github.com/adbar/trafilatura) is a focused extraction library with maintained releases, main-text extraction, metadata, structure, links, images, tables, feed support, filtering, and deduplication. It is a strong optional page-reader backend because it directly addresses Freya’s generic HTML extraction debt without becoming an agent.[3] The `ddgs` package currently exposes text, news, and image metasearch APIs and supports Python 3.10+.[4] It is a candidate provider, but it will be enabled only if its exact pinned version installs and produces structured results on Freya’s Windows runtime. If it is not dependable in this environment, the provider pool will fall back to the existing browser/direct-domain paths without faking success.

No dependency is added during the audit. Any implementation dependency must be pinned, Windows/Python-compatible, compatible with local-model operation, and covered by a fallback path. If the candidate libraries are not already installed, the safer initial implementation is an optional import seam with existing providers retained until the dependency is verified.

## 7. Local-model and Windows compatibility

The design does not require a cloud model, LangChain, LangGraph, an MCP server, or a second agent loop. Fast search and bounded deep research use Freya’s existing synchronous capability boundary and local evidence processors. Browser operations continue through the existing Playwright owner thread. Optional extraction/search libraries are imported lazily so normal startup remains functional if they are absent. Browser Use’s patterns will not be copied in a way that introduces direct cross-thread Playwright calls.

## 8. Resource impact

Fast search remains a small bounded path. Deep research uses explicit limits for query count, source count, page count, traversal depth, browser steps, and wall-clock duration; it is not selected for every current/fresh request. Image retrieval is bounded to a small candidate set, normally 1–4 final images. No autonomous background research worker is introduced. Foreground calls remain cancellable through existing bounded request wrappers and publish safe operational events only.

The implementation will record mode, query count, source/page counts, duplicate counts, provider attempts, and elapsed time in safe result metadata/events. It will not expose chain-of-thought or raw private model prompts.

## 9. Components to reuse

The implementation reuses `CapabilityRouter`, `UnifiedRouter`, `KnowledgeFirstResolver`, `ResearchCapability`, `BrowserCapability`, `PlaywrightBrowserAdapter`, `SafetyGate`, `MemoryCoordinator` conversation context, existing shopping session state, `SourceEvaluator`, `FactExtractor`, `CrossReference`, `CitationManager`, `FreeImageResearchChain`, `image_results`, existing `/api/chat`, and Agent Console event/SSE transport.

## 10. Components not to reuse as runtime architecture

The implementation will not install or embed Browser Use’s agent/controller/event-bus stack, Open Deep Research’s LangGraph graph, a second planner/router, a second conversation or memory system, a second autonomy manager, an uncontrolled third-party browser agent, or provider-specific logic scattered across `ui_server.py` and unrelated capabilities.

## 11. Adapter design

The target is a small Freya-owned adapter boundary:

```text
KnowledgeFirstResolver
          │ explicit mode metadata
          ▼
CapabilityRouter → ResearchCapability
                         │
                         ▼
                 WebResearchAdapter
        ┌────────────┼──────────────┐
        │            │              │
   SearchPool   PageReader   ImageProvider
        │            │              │
        └────── normalized evidence ─┘
                         │
                  Freya synthesis
```

`SearchProvider` returns normalized public result records. `PageReader` returns a `WebPage` with readable content, metadata, links, images, and a provider/error record. `ImageSearchProvider` returns normalized image candidates with source page, domain, title, entity, dimensions when known, relevance, and match confidence. `DeepResearchCoordinator` invokes these adapters through `ResearchCapability` and returns bounded evidence plus transparent uncertainty. Provider failures are data in the result, not reasons to rewrite `ResearchCapability`.

## 12. Deep-research design

`DEEP_RESEARCH` begins with a bounded brief derived from the user request and existing conversation/shopping context. It generates a small set of targeted queries using deterministic templates and, where already available, Freya’s local model only for structured query suggestions. It searches, deduplicates, ranks, opens selected public sources, extracts facts, follows a limited number of important links when they materially address an evidence gap, and cross-checks important claims across independent domains. It stops when the core question is covered, source diversity is sufficient, additional results are duplicates, confidence stops improving, or a budget is reached. The final result retains query/source/page/fact/citation/uncertainty metadata for Freya’s existing formatter.

No dark-web, login, paywall, CAPTCHA bypass, private-system, or unrestricted crawler behavior is introduced. All page access continues through public URL validation and existing browser safety boundaries.

## 13. Image-search design

`IMAGE_SEARCH` is selected for standalone image requests and follow-ups. The UI/server preserves the recent entity and shopping winner through existing conversation/shopping state. The research action receives a resolved entity query rather than the raw phrase “show me that one.” Product image retrieval first uses the verified winner’s exact product page when available; standalone requests use normalized public image providers and source-page traversal. Candidates are deduplicated, ranked by entity/title/source context, and returned through `image_results` so the existing frontend renders actual cards. If exact identity cannot be verified, Freya returns no misleading candidate and explains the limitation.

## 14. Migration plan

First, add the adapter contracts, explicit modes, normalized provider outcomes, and permanent unit tests with fake providers. Second, route existing fast/image/research actions through the adapter while retaining old paths as fallback. Third, verify real Windows installation and live UI behavior, including shopping and browser continuity. Fourth, make the new path canonical. Fifth, delete the covered dead DuckDuckGo/Bing/Google parser branches and scattered page-extraction fallback code. The old path is not deleted before the replacement is proven.

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Search providers throttle or change behavior | Pluggable provider pool, bounded fallbacks, honest partial results, no provider-specific logic in the router. |
| Optional dependency fails on Windows | Lazy import, pinned version, startup-safe absence behavior, existing browser/direct-domain fallback. |
| Deep research becomes slow or expensive | Explicit mode selection and query/source/page/time/browser-step budgets. |
| Research loop becomes a second agent | Deterministic Freya-owned coordinator, no external planner/router, no hidden autonomous loop. |
| Wrong product image returned | Exact entity/product-page/context matching threshold and honest failure. |
| Conversation follow-up loses entity | Reuse `MemoryCoordinator` conversation context and existing shopping session state. |
| Browser cross-thread regression | Preserve `PlaywrightBrowserAdapter` owner thread; no direct third-party Playwright calls. |
| Safety bypass | All consequential browser actions remain in `BrowserCapability._safety_check()` and canonical SafetyGate. |
| UI contract breaks | Preserve `CapabilityResult`, `image_results`, citations, shopping fields, and existing frontend rendering. |

## 16. Acceptance criteria

The focused acceptance set will prove fast search, explicit deep multi-source research, follow-up queries, source-page reading, cross-checking, bounded stopping, domain constraints, shopping winner continuity, standalone/product/person/place image search, follow-up image retrieval, exact-image failure honesty, provider failure resilience, browser fallback/recovery, timeout/cancellation, SafetyGate preservation, existing browser actions, chat/UI rendering, Agent Console safe events, frontend build, and clean shutdown.

## 17. Final recommendation

Adopt **existing Playwright with selected Browser Use-inspired observation improvements** for the browser backend, **deep-research patterns only** for the research backend, **Trafilatura as an optional thin page-reader adapter if installation/verification succeeds**, and a **provider-neutral image-search seam reusing the existing FreeImageResearchChain contract**. Do not install Browser Use or Open Deep Research as runtime frameworks. This is the smallest architecture that addresses brittle retrieval while keeping Freya the assistant and preserves the already verified local-first, routing, memory, shopping, safety, autonomy, browser, and UI behavior.

## References

[1]: https://github.com/browser-use/browser-use "Browser Use repository"
[2]: https://github.com/langchain-ai/open_deep_research "LangChain Open Deep Research repository"
[3]: https://github.com/adbar/trafilatura "Trafilatura repository"
[4]: https://pypi.org/project/ddgs/ "DDGS package on PyPI"


## 18. Implemented result

The selected adapter design is now implemented in `app/research/web_adapter.py` and integrated behind the existing `ResearchCapability` seams. `DDGSProvider` supplies normalized text and image outcomes, `TrafilaturaPageReader` supplies structured readable page content and metadata, and `WebResearchAdapter` preserves provider attempts, errors, source URLs, domains, rankings, and bounded limits. Existing importer and browser fallbacks remain available, and explicit injected importers remain deterministic for tests and compatibility.

`ResearchCapability` now supports explicit `FAST_SEARCH`, `DEEP_RESEARCH`, and `IMAGE_SEARCH` mode metadata without adding a second router. The bounded deep coordinator generates a small query set, performs limited source/page traversal, deduplicates URLs, asks for evidence-gap follow-ups, reuses Freya’s existing fact/cross-reference/citation stages, and returns query/source/page/elapsed/limit/stopping metadata. It does not expose private prompts or chain-of-thought and does not create a background research worker.

`KnowledgeFirstResolver` passes mode metadata through the existing `research_capability` invocation seam. The UI server keeps the existing `/api/chat`, browser action, shopping state, memory context, avatar event, and `image_results` contracts. Image follow-ups resolve the recent image entity through existing conversation context; shopping image follow-ups use the verified winner when present and return a safe refusal when a constrained search has no verified winner. Product/shopping phrases such as “photo printer” are not treated as image-search requests.

## 19. Dependency and runtime verification

The only new direct runtime dependencies are pinned `ddgs==9.15.0` and `trafilatura==2.0.0`; Freya’s existing compatible `lxml` range was widened to accommodate the verified Windows installation. Browser Use and Open Deep Research were not installed. The repository venv completed editable installation and `pip check` reported no broken requirements. The maintained DDGS text/image APIs and Trafilatura extraction API were both exercised with deterministic probes and live public-web calls.

## 20. Verification record

| Acceptance area | Result | Evidence |
|---|---|---|
| Existing research and fallback compatibility | Passed | `tests/test_research_capability.py`, `tests/test_web_search_fallback.py`: 14 passed after adapter integration. |
| Pasted22 adapter and mode regressions | Passed | `tests/test_pasted22_web_adapters.py`: 11 passed, including provider normalization, bounded query planning, deep multi-source flow, explicit modes, image matching, importer compatibility, shopping classification, and safe no-winner refusal. |
| Existing routing, live paths, and shopping regressions | Passed | Focused combined suite covering automatic research routing, Pasted18 live paths, Pasted19 shopping intelligence, and Pasted22: 51 passed in the final run. |
| Fast research in production UI | Passed | Clean Windows Playwright acceptance returned real current Intel sources, citations, and conflict caveats. |
| Deep research in production UI | Passed | Clean Windows Playwright acceptance returned multi-source Nova Lake evidence and source links; the bounded coordinator returned explicit deep mode and evidence metadata in direct tests. |
| Standalone and follow-up image search | Passed | Real UI acceptance returned four GALAX RTX 5060 image cards; “show me another photo” reused GALAX RTX 5060 rather than the literal follow-up phrase. |
| Shopping and hard marketplace constraint | Passed | Real UI acceptance returned verified product listings and a cheapest-price comparison; “only on Shopee” returned no-substitution failure when Shopee exposed no usable product pages. |
| Shopping image safety | Passed | Real UI acceptance refused “show me a photo of the cheapest one” after the constrained Shopee search had no verified winner. |
| Browser continuity | Passed | Existing production UI acceptance completed open-source reading, summarize, screenshot, open-tab, and back actions through the canonical browser capability. |
| Agent Console and avatar/UI behavior | Passed | Existing console panels remained visible; Tasks, Memory, System Status, Autonomy, image cards, and avatar operational events remained functional with no browser console errors. |
| Frontend build | Passed | Existing production frontend build completed after the final source changes. |

## 21. Honest limitations

Public-web search and image providers remain subject to provider throttling, changing result quality, robots restrictions, and pages that expose insufficient readable content. Freya reports provider errors and partial evidence instead of fabricating success. Some marketplace pages, including Shopee in the live environment, did not expose usable product links; the hard domain constraint correctly returned no marketplace substitution. GPU availability remains environment-dependent and is reported honestly by the existing System Status implementation. Browser login-required, CAPTCHA, paywalled, or consequential actions remain bounded by the existing browser and SafetyGate policies; no bypass was introduced.

These limitations are **non-blocking for the Pasted22 MVP** because they are explicit provider/environment outcomes, not hidden placeholders or architecture gaps. The core fast, deep, image, shopping, browser, safety, local-first routing, and UI contracts are implemented and verified through real production paths.

## 22. Final architecture decision

Freya remains the assistant and authoritative owner. The implementation keeps one router, one `ResearchCapability`, one browser controller, one SafetyGate, one memory context, one shopping state owner, one UI transport, and one Agent Console event surface. Browser Use and Open Deep Research contributed bounded mechanics and evidence-state patterns only; they are not runtime frameworks in Freya.
