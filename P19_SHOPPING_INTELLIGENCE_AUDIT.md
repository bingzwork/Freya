# Pasted19 Shopping Intelligence Audit

## Scope

Pasted19 repaired Freya’s conversational shopping and product-research path without introducing a second router, browser framework, research system, or memory system. The work remains inside the existing research capability, canonical memory coordinator, UI server, formatter, and frontend image-result contract.

## Implemented behavior

The research layer now normalizes shopping requests into structured intent fields including product topic, use case, ranking basis, marketplace, allowed domain, and regional domain selection. A Shopee request in a Philippines context resolves to `shopee.ph`; explicit marketplace constraints are passed separately from the topical query and are enforced by the existing browser fallback. A constrained search failure is explicit and does not fall through to Amazon or another marketplace.

Product pages are represented as typed listings with product name, price, currency, seller, marketplace, canonical source URL, product URL, image URL, availability, rating, review count, confidence, and evidence. Numeric prices are parsed and listings are ordered from lowest to highest when a comparable price is available. Search/category pages and login/search boilerplate are treated as discovery or rejected, rather than being presented as final product evidence.

Evidence URLs are canonicalized by removing fragments and common tracking parameters. Cross-reference logic no longer treats different sellers’ prices as contradictory claims when the evidence is clearly listing-specific. User-facing research output is conversational, includes a structured comparison table when listings are present, and only surfaces specific caveats supported by the retrieval outcome.

Shopping context is persisted through the existing conversation-memory write path and a session-keyed UI state containing the active topic, marketplace constraint, candidates, winner, image references, and comparison basis. Follow-ups such as “the cheapest one” and “show me a photo” reuse the current winner. Exact product images are retrieved from the known product page and returned through the existing `image_results` response field; Freya does not fabricate or substitute generic images when an exact image is unavailable.

## Verification

The following checks passed during implementation:

| Check | Result |
|---|---|
| Modified-module syntax validation | Passed |
| `tests/test_pasted19_shopping_intelligence.py` | Passed, 8 tests |
| `tests/test_research_capability.py` | Passed |
| `tests/test_pasted18_live_paths.py` | Passed |
| Combined focused closure suite covering pasted19, pasted18, research, routing, browser, and SafetyGate | Passed to 100% with no test failures |
| Live backend readiness on port 8787 | Ready |
| Live frontend readiness on port 5173 | Ready |
| Exact three-turn printer/Shopee/photo UI flow | Passed fail-closed behavior: no Amazon substitution and no generic image when Shopee produced no verified winner |
| Additional unscripted UI conversations | Exercised laptop/SSD reviews, Amazon headphones image follow-up, and Shopee monitor follow-up |

The live public-web environment still has a known provider limitation: the primary importer and some public fallback pages may return no usable result, or marketplace pages may block automated retrieval. This is reported as a retrieval limitation and is not hidden as a fabricated result. Normal fallback logging is DEBUG-level; WARNING is reserved for genuinely degraded outcomes.

## Repository state

The implementation was committed and pushed to `origin/main` as:

`080bae4 feat: conversational shopping intelligence and multi-turn continuity`

Temporary pasted19 probes and captured runtime outputs were removed before commit. Pre-existing unrelated working-tree files were not staged.
