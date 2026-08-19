# Comparison Intelligence Audit

## Root cause of the original failure

The RTX 3050 versus 5050 failure was not primarily a search-provider problem. Freya classified the request correctly as a technical comparison, but the generic research path treated retrieved pages as one undifferentiated evidence bag. It did not resolve the shorthand second entity before planning, did not keep evidence partitioned by entity, extracted arbitrary readable sentences as specifications or performance, and allowed synthesis to continue when one side had no verified evidence. The old comparison formatter also supplied `Item A` and `Item B` fallbacks, which made an unresolved retrieval result visible as if it were a real entity.

Pasted26 adds a gate between request semantics and ordinary synthesis. Comparison requests now follow:

```text
RequestSemanticModel
  -> entity resolution
  -> category-aware comparison plan
  -> balanced entity-A/entity-B/direct retrieval
  -> existing page/evidence classification
  -> typed claim extraction
  -> partitioned evidence matrix
  -> sufficiency and bounded gap research
  -> comparable-claim conflict analysis
  -> validated natural comparison
```

## Mature systems studied

| External system | Useful pattern | Freya adaptation |
|---|---|---|
| [Open Deep Research][1] | Separate search retrieval, content extraction, report generation, and bounded recursive follow-up. | Comparison plans produce explicit entity and direct-matchup queries; gap queries are bounded and remain inside the canonical ResearchCapability. |
| [GPT Researcher][2] | Separate planner, execution/search workers, source-tracked summaries, and publisher synthesis. | Each comparison entity receives independent queries and evidence buckets; final output consumes typed claims and a compact matrix rather than raw pages. |
| [STORM][3] | Separate research/knowledge curation from outline generation and final writing; use perspective-guided questions for breadth. | Category defaults create comparison dimensions and required evidence roles before retrieval. Freya does not install or duplicate the STORM framework. |

These patterns were selected because they address the actual failure layer: research decomposition, evidence balance, claim grounding, and synthesis gating. Pasted22 retrieval, Pasted23 semantics, Pasted24 learning, and Pasted25 browser monitoring remain canonical.

## Entity resolution

`ComparisonIntelligenceEngine` resolves both sides before query generation. It uses the full request, contextual inheritance, category rules, aliases, and confidence metadata. For example:

```text
rtx 3050 vs 5050
  -> NVIDIA GeForce RTX 3050
  -> NVIDIA GeForce RTX 5050
```

The second side inherits the RTX family only when the first side establishes that context. The same mechanism handles iPhone, Galaxy, Ryzen, PlayStation, database, browser-automation, and frontend-framework comparisons. It does not emit `Item A`, `Item B`, `Entity 1`, or `unknown_product`, and it does not place unresolved placeholders into search queries or synthesis.

## Comparison planning and balanced research

A category-aware plan contains resolved entities, category, dimensions, evidence roles, and bounded query records. GPU plans request official specifications and independent benchmarks for each entity, plus direct benchmark and review/value comparisons. CPU, smartphone, console, laptop, database, browser-framework, and frontend-framework categories have their own compact defaults, with a general fallback rather than a giant template system.

The collector labels each query with its intended entity and rejects a result when its title, snippet, and URL do not identify that planned entity. This prevents five results for entity A from silently becoming evidence for entity B. If a readable page is unavailable, a search snippet can enter only through the same typed-claim validation path, with a lower confidence and source provenance; arbitrary page text cannot enter a comparison cell.

## Claim extraction

Page-level evidence roles from Pasted23 are preserved. Comparison facts are converted into `TypedClaim` records only when they have an identifiable entity, semantic property, meaningful value, source URL, source role, confidence, and optional benchmark conditions. Properties include category-appropriate fields such as VRAM, memory, architecture, performance, ray tracing, power, cores/threads, clock, cache, display, camera, battery, storage, price/value, capabilities, and compatibility.

A benchmark or review claim may populate performance-related properties, but it cannot become a seller or current listing price. Commerce fields remain governed by Pasted23’s retail/marketplace evidence invariant. Navigation fragments such as “Skip to main content,” generic comparison page descriptions, cookie/login text, and untyped marketing prose are discarded.

## Evidence matrix and sufficiency

`ComparisonEvidenceMatrix` stores cells by entity and dimension. Each cell retains typed claims, support count, support status, comparability, and conflict state. Shared direct-comparison claims are kept separately from entity-specific claims. Important dimensions are checked for both entities before synthesis.

The gate has three states:

| Status | Behavior |
|---|---|
| `SUFFICIENT` | Both entities have evidence across the important dimensions; comparison synthesis is allowed. |
| `PARTIAL_BUT_USEFUL` | At least one side has validated evidence, but coverage is incomplete; Freya returns a clearly marked partial comparison and names missing cells. |
| `INSUFFICIENT` | Neither side has usable validated claims or two entities cannot be resolved; Freya refuses to invent a comparison. |

Missing cells create targeted gap queries instead of repeating one broad comparison search. Conflict analysis runs only after claims and coverage are built.

## Conflict rules and benchmark comparability

A comparison conflict requires the same resolved entity, same typed property, comparable conditions, materially different values, at least two credible source URLs, and adequate confidence. Different games, resolutions, quality presets, test platforms, drivers, or methodologies are not automatically conflicts. Different retailer prices are not conflicts. A benchmark source remains benchmark evidence and never becomes a seller without independent commerce signals.

## Synthesis validation

The final comparison is built from resolved names, category, matrix cells, typed claims, citations, missing evidence, and validated conflicts. It cannot use a raw page as a table cell, cannot use placeholders, cannot populate commerce fields from benchmarks, and cannot claim a complete comparison when the evidence gate is insufficient. Partial output explicitly identifies missing coverage. Complete output uses a natural recommendation sentence and a compact comparison table, rather than the former generic `Technical comparison: ... Item B` template.

## Files changed

The Pasted26 implementation adds `app/research/comparison_intelligence.py`, extends `app/research/capability.py` to route comparisons through the new pipeline, and adds `tests/test_pasted26_comparison_intelligence.py`. The dashboard correction immediately preceding Pasted26 is committed separately in `690733b`; it uses the canonical BrowserCapability status and removes the Research status row.

## Verification and UI acceptance

The permanent Pasted26 suite covers contextual completion, cross-category entity resolution, balanced plan queries, claim filtering, matrix partitioning, partial evidence and gap queries, true versus false conflicts, and a deterministic ResearchCapability integration. The combined Pasted23/Pasted24/Pasted25/Pasted26 focused regression command passed all collected tests. Python syntax checks passed.

A direct production `/api/chat` probe for `rtx 3050 vs 5050` completed in approximately 38 seconds with canonical entities, no `Item B`, no shopping seller fields, and an honest partial comparison when the current public providers returned only one-sided readable evidence. The previous 3-prompt UI acceptance attempt reached the real backend but exhausted its 240-second browser wait before a report was emitted. A final bounded UI rerun is required after the current provider availability check. This limitation is provider availability/coverage, not a fallback-to-placeholder defect: Freya now stops honestly instead of manufacturing the missing side.

## Remaining limitations

Public provider availability remains intermittent, and benchmark/specification page readability varies. When the provider cannot produce balanced readable evidence within the bounded budget, Freya returns a partial/insufficient result rather than a complete recommendation. Entity verification is currently deterministic and evidence-aware at the plan boundary; a future enhancement could add a bounded structured local-model disambiguation pass for genuinely ambiguous shorthand. The comparison engine intentionally does not implement a separate agent framework, persistent comparison database, or unrestricted recursive research loop.

## References

[1]: https://github.com/btahir/open-deep-research "Open Deep Research repository"
[2]: https://github.com/assafelovic/gpt-researcher "GPT Researcher repository"
[3]: https://github.com/stanford-oval/storm "STORM repository"
