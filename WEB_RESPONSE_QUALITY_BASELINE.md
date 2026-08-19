# Freya Web Response Quality Baseline

## Baseline identity

The baseline was run against Freya commit `7a822ef`, before Pasted30 production changes. It uses the permanent 25-case benchmark in `WEB_RESPONSE_QUALITY_BENCHMARK.json` and the current `RequestSemanticAnalyzer` contract.

| Metric | Baseline |
|---|---:|
| Benchmark cases | 25 |
| Semantic/mode cases passing | 10 |
| Cases with failures | 15 |
| Intent mismatches | 10 |
| Research-mode mismatches | 4 |
| Requested-count support failures | 4 |
| Prompt-specific hardcoding | 0 |
| Fabricated output introduced by benchmark | 0 |

## Primary failure modes

The largest baseline weakness is that the semantic contract does not yet preserve enough of the user’s requested result shape. `requested_count` is absent from the canonical model, so image, alternative, and follow-up count requests cannot reliably reach the backend or UI as a binding target. The baseline failed count recognition for ten photos, five similar images, five alternatives, and five more.

Freshness words are detected, but the current classifier sometimes over-promotes a current question to `NEWS_RESEARCH`. For example, “latest stable version of Python” and “what changed in the latest Freya web-search behavior” were classified as news rather than current factual lookup. The freshness signal exists, but the response mode is not yet sufficiently differentiated.

The current analyzer also routes some source requests, troubleshooting questions, repository questions, and conflict questions to generic factual/web paths instead of distinct result contracts. This does not necessarily mean the backend cannot answer them; it means the user’s requested operation and expected response type are not explicit enough for coverage and quality enforcement.

Reverse-image and similar-image requests have image-search intent but can retain `FAST_SEARCH` execution mode. That makes it easier for downstream code to select a generic search path instead of a first-class image-discovery path.

## Image-search implementation failures found by inspection

The current image-search backend delegates text discovery using the caller’s `limit` and does not intentionally over-fetch candidates. Public HTML and vision-assisted fallback paths therefore commonly stop near the requested display count before broken assets, mismatches, and duplicates are removed. A request for ten photos can consequently produce four usable assets without a bounded coverage-gap follow-up.

The current image candidate contract preserves basic titles, image URLs, source URLs/domains, snippets, match type, and relevance, but does not consistently carry entity match confidence, date type, freshness, dimensions, asset type, or complete provenance. The UI normalizer also limits the visible result shape and has no requested-count, verified-count, rejection, or candidate metrics.

The current `/api/chat` image-search branch emits a generic success sentence instead of deriving the sentence from the actual verified result count. The response payload does not yet expose candidate, rejected, duplicate, broken-asset, or coverage-gap telemetry for the activity panel.

## Current strengths

The baseline confirms that ordinary factual lookup, technical comparison, recommendation classification, news classification for explicit news queries, public-person research, location research, correction handling, and attachment-as-reference comparison already have useful foundations. Pasted23–Pasted29 also provide semantic research, comparison, multimodal routing, local-baseline reconciliation, vertical plans, source profiles, answer-quality verification, and validated learning boundaries.

## Pasted30 acceptance target

The first implementation target is not a stronger local model. It is a more explicit response contract: understand requested operation and count, choose the right research/image mode, over-fetch within bounded budgets, validate and deduplicate actual assets, evaluate coverage, continue when a gap remains, synthesize a direct answer, and report the truthful result type and count. The benchmark will be rerun after each bounded implementation stage.

## Baseline artifacts

The generated machine-readable baseline is `outputs/p30_baseline.json`. The benchmark runner is `tools/p30_baseline.py`. These artifacts record the before state without changing production behavior.
