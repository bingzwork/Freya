# Pasted31 Adversarial Findings

The first live pass was run against the real local Freya backend on ports 8787/5173. The baseline benchmark and existing focused suite were green, but real user scenarios exposed response-quality defects.

| Scenario | Observed defect | Generalized repair direction |
|---|---|---|
| `Hello Freya, what can you help me with?` | Returned “I can use the registered capability memory_management.” This is internal capability language, not a natural greeting. | Add social/small-talk classification and a user-facing conversational response path. |
| `Who makes the RTX 5090?` | Returned a generic evidence failure instead of researching the factual question. | Route external factual lookups through the research path and compose a grounded direct answer. |
| `What's the latest stable version of Python?` | Fallback searched the wrapper words and returned WhatsApp/definition sources. | Normalize question wrappers before search and reject low-topic-relevance fallback results. |
| Official RTX 5060 specifications | Returned a raw source list with duplicated/concatenated titles instead of synthesized facts. | Replace source-dump fallback with structured source-backed answer composition. |
| Named-author research | Returned generic author-evaluation links even though no author was named. | Ask for the missing subject instead of researching a placeholder. |
| Ryzen 7 5700X vs i5-14400 | Manufacturer resolution is fixed and structured comparison renders, but evidence extraction still produces an invalid performance value such as `5700X`, source titles are concatenated, and Intel evidence can be absent. | Tighten numeric extraction, improve CPU query variants/source acceptance, and render clean evidence/source records. |
| Counted image/search follow-up | Existing Pasted30 image path returns image assets and metrics, but this pass still needs additional wording, failure, and malformed-result adversarial cases. | Continue the live repair loop after general research fixes. |

This file records the starting defects for Pasted31; none of these findings should be accepted as a limitation at completion.

## Final repair loop additions

The remaining live failures were also repaired rather than accepted. Explicit specification requests now use a dedicated `SPECIFICATION_LOOKUP` intent and the same measurable-evidence filter as factual synthesis, so marketing-only text is rejected. A bounded snippet-evidence path now supports grounded factual and specification answers when linked pages are unreadable. Primary release-index retrieval preserves complete patch versions such as Python 3.14.7.

Comparison collection now allocates a fair per-query evidence share, preventing the first entity from consuming the entire source budget. CPU aliases and punctuation are normalized consistently, and model names cannot be extracted as performance values. Image-provider timeouts and constructor failures are contained at the UI boundary, with safe 200 responses and no raw DDGS/provider diagnostics. Explicit nonexistent or unverified image subjects never receive unrelated assets. Subject-less correction, anaphoric, and conflict requests clarify instead of launching unrelated searches. Source titles are normalized and duplicate concatenated result titles are truncated before display.

## Final acceptance evidence

The final focused live recheck returned HTTP 200 for greeting, factual manufacturer lookup, current Python version, official RTX 5060 specifications, missing-subject clarification, and comparison. The focused edge recheck returned HTTP 200 for valid image requests, provider-timeout-safe image responses, clarification cases, and comparison; the explicit no-result image harness returned HTTP 200 with zero images and a truthful no-substitution response. The UI smoke check returned HTTP 200 for the Vite surface and a real conversational chat request.

The expanded Pasted31 regression file contains 14 passing tests, including permanent coverage for provider timeout safety, subject-less conflict clarification, specification intent routing, full patch-version extraction, source fallback formatting, and fair comparison planning. The combined focused regression suite passed in full. The production frontend build passed. The Pasted30 benchmark passed all 25 of 25 cases after its specification case was updated to the stronger dedicated specification intent contract.
