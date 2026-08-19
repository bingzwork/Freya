# Open-Source Research Intelligence Audit

## Scope and baseline

Pasted23 addresses a research-intelligence problem, not a low-level browser problem. Pasted22 already supplies Freya-owned search, page-reading, image, bounded deep-research, shopping, browser, SafetyGate, and UI seams. The pre-change production UI reproduced three failures: latest NVIDIA GPU news selected an unrelated infrastructure article, `compare RTX 5060 vs RX 9060 XT` became a cheapest-product listing with benchmark sites represented as sellers, and a self-contained NVIDIA update request was blocked by stale shopping-winner state.

The common failure is that request semantics are too weak and retrieval evidence is allowed to redefine the user’s goal. Freya needs a small semantic/evidence/synthesis layer between the existing resolver/capability route and the existing web adapter, without creating a second router, planner, memory system, or agent framework.

## Mature systems inspected

| System | Useful proven pattern | Freya adaptation | Rejected import |
|---|---|---|---|
| [Browser Use][1] | Stateful browser session, structured observations, stable target/session state, explicit action outcomes and recovery boundaries. | Keep these ideas behind Freya’s existing `BrowserCapability` and `PlaywrightBrowserAdapter`; pass typed page observations to research when useful. | Full browser agent, event bus, CDP controller, and alternate lifecycle. |
| [Open Deep Research][2] | Explicit research brief, bounded supervisor/researcher iterations, model-role separation, compression before final writing, structured configuration. | Extend Freya’s existing bounded coordinator with a typed objective, subquestions, source roles, stopping metadata, and compact evidence context. | LangGraph graph, second planner, parallel multi-agent stack, and external synthesis owner. |
| [GPT Researcher][3] | Planner creates task-specific questions; execution workers gather and source-track evidence; publisher aggregates findings with citations; context is managed across branches. | Use deterministic/template question planning plus Freya’s local model only for bounded structured suggestions; preserve source roles and final citations in Freya’s `ResearchResult`. | Autonomous multi-agent runtime, crawler replacement, and report publisher. |
| [STORM][4] | Perspective-guided question asking, simulated expert/writer dialogue, research-before-outline, outline-before-writing, and separate polishing. | Add task-specific research strategies, comparison dimensions, news developments, and answer plans before synthesis. | Wikipedia/article-generation pipeline, multi-agent discourse engine, and large report workflow. |
| [LlamaIndex CitationQueryEngine][5] | Retrieves granular citation nodes, asks the synthesizer to answer only from numbered sources, and exposes source nodes for inspection. | Normalize typed evidence chunks, keep source-to-claim links, validate citations, and make final synthesis consume only selected evidence. | LlamaIndex index, vector store, and alternate response engine. |

## Freya’s current seams

`KnowledgeFirstResolver` and `CapabilityRouter` remain the canonical route owners. `ResearchCapability` already owns `ResearchResult`, `Fact`, `Citation`, `CrossReference`, source evaluation, shopping normalization, product extraction, and the Pasted22 `WebResearchAdapter`. `ConversationMemory` already stores typed turns, entities, and shopping state. `MemoryCoordinator` remains the safe conversation-context owner. These are extension points, not reasons to build parallel services.

The main weaknesses are visible in the production code. Product intent is inferred from a small keyword set, so comparison and review requests can enter shopping. `_extract_product_listing` parses a price from arbitrary readable content without a semantic evidence type or commerce-offer requirement. `CrossReference` compares loosely similar sentences and emits a generic conflict warning. Non-shopping research and deep research both concatenate the first facts into `Based on the retrieved sources:`. UI shopping-state guards run before a semantic reference check, allowing stale state to hijack a new named request.

## Target semantic representation

The implementation will add a compact Freya-owned `RequestSemanticModel` and related enums in the existing research layer. It will carry the user goal through routing, retrieval, evidence normalization, and synthesis.

```text
intent: FACTUAL_LOOKUP | CURRENT_LOOKUP | NEWS_RESEARCH | DEEP_RESEARCH |
        TECHNICAL_COMPARISON | PRODUCT_COMPARISON | SHOPPING_DISCOVERY |
        SHOPPING_PRICE_SEARCH | REVIEW_RESEARCH | SPECIFICATION_LOOKUP |
        CLAIM_VERIFICATION | IMAGE_SEARCH | PAGE_SUMMARY | GENERAL_WEB_RESEARCH
execution_mode: FAST_SEARCH | DEEP_RESEARCH | IMAGE_SEARCH
entities: normalized named entities
operation: answer | compare | summarize | verify | find | show | review
freshness: none | current_preferred | latest
comparison_dimensions: typed dimensions requested or suggested
shopping: bool
price_lookup: bool
news: bool
image: bool
requested_domain, output_goal, explicit_references, constraints
```

Strong deterministic cues will handle obvious commands. A bounded local-model classifier may enrich ambiguous requests only through validated structured output; it will never override hard safety, explicit URLs, hard marketplace constraints, or clear comparison/shopping distinctions.

## Evidence taxonomy and field restrictions

Every page/result used for synthesis will receive an evidence role based on domain, URL path, metadata, schema signals, title, content structure, and context. The minimum taxonomy is `OFFICIAL_PRODUCT`, `OFFICIAL_ANNOUNCEMENT`, `OFFICIAL_DOCUMENTATION`, `NEWS_ARTICLE`, `RETAIL_LISTING`, `MARKETPLACE_LISTING`, `REVIEW`, `BENCHMARK`, `TECHNICAL_COMPARISON`, `RESEARCH_PAPER`, `FORUM_DISCUSSION`, `SOCIAL_POST`, `GENERAL_WEB`, and `IMAGE`.

Evidence roles control which fields are valid. Only `RETAIL_LISTING` or `MARKETPLACE_LISTING` evidence with commerce signals may populate seller, marketplace, availability, and current listing price. A benchmark or comparison page may contribute FPS, performance scores, methodology, power, and relative performance, but its MSRP/reference price is never a current seller offer. News evidence may contribute publication/event dates, announcements, quotes, and context, but does not become a product listing merely because it mentions a product.

Price records will preserve `CURRENT_LISTING_PRICE`, `MSRP`, `LAUNCH_PRICE`, `REFERENCE_PRICE`, `HISTORICAL_PRICE`, `SALE_PRICE`, `ESTIMATED_PRICE`, or `UNKNOWN_PRICE`. This prevents a `$299` benchmark/MSRP mention from becoming a live listing.

## Research strategies

`NEWS_RESEARCH` generates topical queries, filters results against the requested subject, extracts publication/event/updated dates, ranks by relevance and recency, groups distinct developments, opens the strongest sources, cross-checks important claims, and produces a development-oriented summary with specific caveats.

`TECHNICAL_COMPARISON` extracts entities and category-aware dimensions, gathers official specifications plus independent performance evidence, keeps price context separate from shopping, and synthesizes a comparison table and tradeoff conclusion. `SHOPPING_PRICE_SEARCH` alone may convert verified commerce evidence into `ProductListing` records. `REVIEW_RESEARCH` prioritizes review/benchmark evidence and retains methodology caveats. Factual, page-summary, verification, image, and deep-research strategies use the existing modes and contracts with task-specific answer plans.

## Context boundaries

A new message first receives an explicit-reference check. Named entities plus a complete operation, such as `find latest update of NVIDIA`, override stale implicit state. Prior context is used for typed references such as `that one`, `the cheapest one`, `it`, `compare it with AMD`, `show me another photo`, and `what about the second one`, only when a credible antecedent exists.

Typed context remains separate: recent entities, comparison, news topic, image entity, research topic, sources, and shopping winner. A shopping winner cannot block a self-contained news request. The original semantic model is carried alongside results so prices in comparison evidence cannot change the original intent into shopping.

## Conflict and uncertainty rules

A material conflict requires the same entity, the same property or claim, materially incompatible values, and credible evidence on both sides. Different retailer prices, different benchmark conditions, provider failure, missing information, and source absence are not conflicts. True conflicts retain the claim, source A/value A, source B/value B, incompatibility reason, and confidence. User-facing caveats will name the specific uncertainty rather than emit generic boilerplate.

## Synthesis validation

Before final output, a lightweight validation pass checks that comparison answers are not shopping listings, news answers are supported by topic-relevant news evidence, seller fields are restricted to commerce evidence, citations point to the claims they support, and raw retrieval garbage or broken Markdown is removed. Task-specific synthesis will prefer direct answers, concise evidence, useful citations, comparison tables where appropriate, meaningful dates for news, and specific uncertainty.

## Patterns deliberately rejected

Freya will not install Browser Use, Open Deep Research, GPT Researcher, STORM, LlamaIndex, LangGraph, or another autonomous agent framework. No second router, research manager, memory system, autonomy manager, browser controller, or event bus will be created. The local model remains a bounded semantic/synthesis helper, not an unvalidated authority over safety or routing.

## Invariants

1. `TECHNICAL_COMPARISON` cannot silently become `SHOPPING_PRICE_SEARCH`.
2. Benchmark, review, news, and comparison evidence cannot become retail listings without independent commerce signals.
3. `NEWS_RESEARCH` enforces topic relevance and actual date semantics.
4. An explicit self-contained request overrides stale shopping state.
5. Image follow-ups may reuse only a credible recent image entity or winner.
6. Hard marketplace constraints remain hard.
7. Existing `FAST_SEARCH`, `DEEP_RESEARCH`, `IMAGE_SEARCH`, browser, shopping, image cards, Agent Console, autonomy, memory, `/api/chat`, frontend build, and SafetyGate contracts remain intact.

## References

[1]: https://github.com/browser-use/browser-use "Browser Use repository"
[2]: https://github.com/langchain-ai/open_deep_research "Open Deep Research repository"
[3]: https://github.com/assafelovic/gpt-researcher "GPT Researcher repository"
[4]: https://github.com/stanford-oval/storm "Stanford STORM repository"
[5]: https://developers.llamaindex.ai/python/examples/query_engine/citation_query_engine/ "LlamaIndex CitationQueryEngine documentation"
