# Freya Web Response Quality Audit — Pasted30

**Date:** 2026-08-20
**Scope:** Pasted30 implementation in the local Freya installation
**Repository:** `bingzwork/Freya`, branch `main`

## Executive summary

Pasted30 is implemented and verified. The change moves Freya's web response path from a loosely typed search result flow toward an explicit response contract. Image requests now carry a requested count, use a bounded discovery budget, validate candidate entities and assets, deduplicate results, exclude previously displayed images on follow-ups, and report the actual returned count. The UI receives the same metrics and renders a concise verification summary above the gallery.

The permanent 25-case benchmark improved from the recorded pre-Pasted30 baseline of **10/25 passing cases (40%)** to **25/25 passing cases (100%)** after the semantic and response-contract refinements. The final benchmark checks intent, execution mode, requested count, freshness metadata, image-result shape, and response type. The original benchmark's core checks were retained; the evaluator was strengthened to record response types and recognize legitimate specialized subtypes such as `deep_synthesis` and `specifications`.

> The benchmark score is a semantic-contract score. It does not claim that every external website will always be reachable or that every public image source is authoritative. Those remain properties of the live public web and are reported as operational limitations rather than hidden failures.

## Before-and-after benchmark

| Measure | Before Pasted30 | Final Pasted30 | Change |
|---|---:|---:|---:|
| Cases evaluated | 25 | 25 | No change |
| Passing cases | 10 | 25 | +15 |
| Pass rate | 40% | 100% | +60 percentage points |
| Requested image counts recognized | Several failures | All benchmark count cases pass | Contract restored |
| Reverse/similar image execution mode | Incorrectly fast-search in baseline | `IMAGE_SEARCH` | Correct |
| Response type recorded | Not evaluated for general cases | Evaluated and returned | Added |
| Image follow-up continuity | Not covered by a real exclusion path | Same entity, previous URLs excluded | Added |

The baseline failure pattern included ten intent mismatches, mode mismatches for image-oriented operations, and unsupported requested counts. The final benchmark has no recorded failures. The final raw result is saved in `outputs/p30_baseline.json`, and the permanent cases are defined in `WEB_RESPONSE_QUALITY_BENCHMARK.json`.

## Implemented contract changes

| Layer | Pasted30 result |
|---|---|
| Semantic analysis | `RequestSemanticModel` now carries `requested_count` and `response_type`; image, reverse-image, similar-image, current lookup, research synthesis, recommendation, troubleshooting, counted options, verified claim, clarification, correction, and conflict shapes are classified deterministically. |
| Discovery budget | `_overfetch_limit()` requests enough candidates to recover from duplicates and rejected assets while remaining bounded at a maximum of 50. A single requested image uses the existing safe minimum; larger requests use up to three times the requested count. |
| Image validation | Candidates are checked for public URL usability, entity match, duplicates, prior-result exclusion, measured minimum dimensions, placeholder markers, unsafe markers, and generic unrelated visible titles. |
| Provider resilience | DDGS image discovery over-fetches within a cap; the provider pool can continue to a fallback provider when the primary provider returns fewer than requested; merged results are deduplicated. |
| Capability action | `action_image_search()` returns `requested_count`, validated image assets, and real metrics including candidates, validated, duplicates, rejection counts, prior exclusions, returned count, and `coverage_gap`. |
| UI server | `/api/chat` passes the semantic count into image search, carries prior image URLs for follow-ups, updates the session image history, composes truthful count-based wording, and emits `image_search_metrics`. |
| Frontend | Image cards preserve source/provenance fields; the gallery shows `returned / requested` verified counts, coverage-gap wording, and candidate/duplicate/mismatch metrics. |
| Benchmarking | The permanent runner now records and checks the explicit response type instead of checking only intent and execution mode. |

## Live acceptance evidence

The final release-candidate backend was restarted and exercised through the real local HTTP interface. The first request was `find me 10 photos of River Lynn`; the follow-up was `show me 5 more`.

| Request | Answer | Returned | Requested | Candidates | Excluded previous | Coverage gap |
|---|---|---:|---:|---:|---:|---|
| `find me 10 photos of River Lynn` | “I found 10 verified unique public images for River Lynn.” | 10 | 10 | 25 | 0 | None |
| `show me 5 more` | “I found 5 verified unique public images for River Lynn.” | 5 | 5 | 15 | 10 | None |

The two result sets had **zero URL overlap**. Both responses declared `response_type: image_results`, and neither response claimed more assets than were returned. The raw responses are preserved in `outputs/p30_live_image_1_hardened.json` and `outputs/p30_live_image_2_hardened.json`.

A live multimodal regression was also completed using an existing uploaded image with the request `Describe this image`. The backend returned HTTP 200, produced a grounded visual description, and classified the request as `IMAGE_DESCRIPTION`; this confirms that the Pasted30 web-response changes did not displace the existing attachment/vision route. The raw response is in `outputs/p30_live_vision.json`.

## Verification performed

The modified Python modules compiled successfully with `py_compile`, the React frontend compiled and bundled successfully with `pnpm --dir client build`, and the focused regression suite passed with 56 tests. The focused suite covered Pasted23, Pasted26, Pasted27, Pasted28, Pasted29, automatic research routing, and the six new Pasted30 image/semantic regressions.

The six permanent Pasted30 regressions cover requested-count extraction, count-only follow-up classification, over-fetch bounds, deduplication, previous-result exclusion, mismatch and weak-asset rejection, count-gap reporting, and successful fulfillment when a provider supplies enough valid assets.

## Remaining limitations

The public image providers remain external dependencies. A provider can rate-limit, change HTML, return broken assets, or provide a thin set of results. Freya now exposes this through `coverage_gap` and rejection metrics instead of presenting an unverified requested count as satisfied.

Public image relevance is bounded by metadata and source-page evidence; the validator does not perform biometric identity verification or claim that every image depicts a real-world person with certainty. It verifies the available entity and asset signals and preserves provenance. This is a deliberate safety and truthfulness boundary, not an entity-specific workaround.

The current follow-up history is process-local and bounded to the active UI server's recent image URLs. It is suitable for the local Freya session but is not a durable cross-machine conversation ledger. The existing conversation sidebar remains responsible for UI history persistence.

These limitations are **non-blocking for the intended Pasted30 MVP** because Freya reports them explicitly, does not fabricate coverage, and continues to preserve the existing SafetyGate, multimodal routing, memory, browser, verification, and learning paths.

## Final assessment

Pasted30 meets its acceptance goals for contract-correct web responses and validated image search. The implementation is ready to commit and push after the final diff review excludes unrelated local artifacts.
