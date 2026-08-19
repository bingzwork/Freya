# Pasted28 Knowledge Improvement Audit

## Scope

Pasted28 changes Freya’s local-first behavior from **local answer closure** to **local baseline plus bounded improvement assessment**. Local retrieval remains the first step. Research is triggered when freshness, incompleteness, recommendation value, technical change, conflict detection, or useful enrichment justifies external evidence.

## Canonical owners preserved

The implementation extends the existing `KnowledgeFirstResolver`, `RequestSemanticAnalyzer`, `ResearchCapability`, `WebResearchAdapter`, `AnswerVerifier`-compatible evidence model, `LearningPipeline`, and `MemoryCoordinator` path. No second memory owner, research capability, orchestration engine, or learning pipeline was introduced.

## Implemented flow

```text
User request
  -> KnowledgeFirstResolver
  -> UnifiedRetrieval local baseline
  -> LocalKnowledgeSnapshot
  -> KnowledgeImprovementAssessor
  -> local answer OR ResearchCapability
  -> bounded provider/page retrieval
  -> evidence extraction and source typing
  -> KnowledgeReconciler
  -> ResearchAnswerQualityVerifier
  -> answer with structured trace metadata
  -> existing LearningPipeline only when verified
  -> MemoryCoordinator canonical write
```

## Local baseline and improvement states

`LocalKnowledgeSnapshot` preserves claims, confidence, provenance, learned/verified timestamps where available, freshness class, domain, source types, and retrieval count. `KnowledgeImprovementAssessor` emits explicit states: `LOCAL_SUFFICIENT_AND_CURRENT`, `LOCAL_VALID_BUT_ENRICHABLE`, `LOCAL_STALE`, `LOCAL_CONFLICTED`, `LOCAL_INCOMPLETE`, `LOCAL_UNKNOWN`, and `OFFLINE_LOCAL_ONLY`.

Freshness classes are `STATIC`, `LOW_CHANGE`, `MEDIUM_CHANGE`, `HIGH_CHANGE`, and `REALTIME`. The decision is not “newer always wins.” A freshness-sensitive request is researched, but the reconciliation stage still compares source confidence, source role, claim overlap, and material conflicts.

## Reconciliation

`KnowledgeReconciler` classifies local/external relationships as `LOCAL_ONLY`, `WEB_ONLY`, `AGREE`, `PARTIAL_AGREEMENT`, or `CONFLICT`. Numeric disagreements are retained as explicit conflicts. The chosen interpretation records the reason and provenance; external evidence does not automatically overwrite stronger local evidence.

## Research resilience

The existing `SearchProviderPool` now supports bounded multi-provider aggregation. DDGS remains the primary provider. A public Bing HTML fallback is attempted when multi-provider mode is requested or the primary provider fails. Duplicate URLs are removed and provider attempts are returned as structured metadata.

`EvidenceCache` provides bounded in-process TTL caching for search candidates and readable pages. Search evidence uses a short TTL; readable pages use a longer bounded TTL. Expired cache entries are not returned as silently current evidence.

## Verification and learning

`ResearchAnswerQualityVerifier` checks selected answer claims against extracted evidence and reports `VERIFIED`, `PARTIALLY_VERIFIED`, `CONFLICTED`, or `INSUFFICIENT_EVIDENCE`. Unsupported claims produce uncertainty metadata rather than confident success.

Verified research results can produce a structured learning candidate through the existing `LearningPipeline`. The candidate retains topic, answer, citations, evidence IDs, freshness class, learned/verified timestamps, conflicts, reconciliation state, and provenance. Unverified results are not promoted. `MemoryCoordinator` remains the durable write owner.

## Tests

`tests/test_pasted28_knowledge_improvement.py` covers:

1. Enrichable local knowledge for recommendations and model questions.
2. Stable local explanations remaining local.
3. Freshness-sensitive research decisions.
4. Local/external conflict preservation.
5. Web-only enrichment.
6. Unsupported-answer detection.
7. Evidence-grounded answers.
8. Multi-provider aggregation and deduplication.
9. Structured verified-research learning candidates.
10. Local-only request boundaries.

The dedicated Pasted28 regression file passes. Production syntax compilation passes for the modified research and resolver modules.

## Remaining bounded limitations

The secondary provider is best-effort public HTML retrieval and is not an API-backed replacement for a commercial search index. Source authority scoring and semantic reranking remain rule-based in this stage. Browser fallback and dynamic-page extraction remain dependent on page accessibility. These limitations are explicitly surfaced through provider attempts, errors, partial state, uncertainty, and answer-quality metadata.
