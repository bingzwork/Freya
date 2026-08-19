# Pasted29 Specialized Research Intelligence Audit

## Scope

Pasted29 extends the existing `ResearchCapability` and `WebResearchAdapter` with specialized vertical research strategies, operational source-quality profiles, visible claim-level citations, and typed user-feedback learning. These remain strategies behind Freya’s canonical research capability; no duplicate top-level capabilities were created.

## Vertical strategy selection

`ResearchStrategySelector.select_vertical()` and `vertical_plan()` select `GENERAL_WEB`, `NEWS`, `OFFICIAL_DOCUMENTATION`, `ACADEMIC_RESEARCH`, `PRODUCTS`, `MARKETPLACES`, `REVIEWS`, `SOFTWARE_REPOSITORIES`, or `IMAGE_SEARCH`. Each plan defines source priorities, freshness, query suffixes, extraction requirements, and verification rules. News prioritizes publication/event dates and independent reporting. Documentation prefers first-party sources and version checks. Academic research requires methodology and context. Products and marketplaces separate manufacturer facts from reviews and listings, and require variant/price/availability checks. Image search retains provenance and does not make unsupported identity claims.

## Source-quality profiles

`SourceQualityProfileStore` tracks domain identity, source type, authority score, extraction success/failure, recurring relevance, verification success, duplicate and conflict observations, rate-limit failures, and last evaluation time. Profile bonuses are bounded. A profile can influence ranking, but it cannot override the evidence classifier, page content, conflicts, or verification result.

Validated profile snapshots are written through the existing `MemoryCoordinator` as `source_profile` knowledge only after answer-quality verification succeeds. They are loaded from canonical semantic memory on startup. This keeps source-profile learning durable while preserving existing learning and promotion boundaries.

> A historically reliable source can still be wrong, and a historically weak source can still contain valid evidence. Evidence remains stronger than reputation.

## Visible citations

`SynthesisEngine.attach_inline_citations()` maps each answer sentence to the most similar supporting fact and adds a numbered citation only when that fact’s URL is present in the citation set. It also emits a visible `Sources` section with the exact title and URL. Claims without adequate support are not silently assigned an unrelated citation.

The answer-quality verifier runs before citation rendering. Unsupported or insufficiently grounded answers retain uncertainty metadata and do not become more authoritative merely because a source list exists.

## Feedback learning

`FeedbackClassifier` separates user preferences and answer style, factual corrections, source feedback, execution feedback, and answer confirmation. Preferences use the existing preference-learning owner. Factual corrections, source feedback, and execution feedback enter the existing `LearningPipeline` as unverified or appropriately typed candidates. A user statement is never promoted directly into universal fact memory.

## Synthesis-model boundary

The local model and canonical provider architecture were not replaced. Pasted29 instruments retrieval, source quality, evidence grounding, citation coverage, and feedback boundaries first. A stronger synthesis model should be evaluated only after a fixed response-quality benchmark demonstrates that evidence quality is no longer the primary bottleneck.

## Verification

`tests/test_pasted29_research_intelligence.py` covers vertical strategy selection, marketplace fields, source-profile history, bounded reputation influence, inline citation grounding, feedback classification, and unverified feedback learning. Final verification also passed the Pasted28, Pasted23, and Pasted26 compatibility regressions, and production syntax compilation passed for `intelligence.py`, `capability.py`, and `initializer.py`.

## Remaining limitations

Source profiles are operational evidence, not a complete global authority graph. Provider coverage, public-page accessibility, dynamic-page extraction, and browser access remain environment-dependent. Inline citations use the extracted fact/source contract; pages that cannot be read cannot yield passage-level citations. These limits are surfaced rather than hidden.
