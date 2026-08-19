# Pasted18 Live Browser, Research, Shopping, and UI Reliability Audit

## Executive verdict

> **Pasted18 production path: WORKING WITH HONEST NON-BLOCKING PUBLIC-PROVIDER LIMITATIONS.**

Freya now starts normally, launches managed Chromium through the existing `browser_capability` and `PlaywrightBrowserAdapter`, routes current/product/review requests deterministically to research, uses Chromium as a bounded fallback, reads public pages, returns source-linked evidence, captures screenshots, reuses browser state across HTTP requests, switches tabs, and shuts down browser resources cleanly.

The result is not an exhaustive shopping crawler and never claims globally cheapest prices when available public evidence does not support that claim. Authenticated commerce, purchasing, account changes, and consequential browser mutations remain subject to provider configuration and the existing SafetyGate.

## Architecture traced

```text
normal launcher -> Vite frontend -> /api/chat -> request context/UI routing
-> deterministic browser/research selection -> ResearchCapability or BrowserCapability
-> fast providers -> bounded Chromium fallback -> public-page extraction
-> typed evidence -> normalized response -> frontend/avatar state
```

No parallel router, registry, research system, browser framework, or promotion path was introduced. Initializer-owned browser and research objects remain canonical. Research remains the cheaper first path; Chromium is the fallback and direct browser-action path.

## Browser repairs and evidence

Playwright Python **1.62.0** and its matching managed Chromium runtime are installed in `C:\AI Projects\Freya\.venv`. The existing adapter remains the implementation; no Selenium or replacement framework was added.

The main repair was thread ownership. Freya’s HTTP server is threaded, while Playwright’s synchronous API objects must remain on their owning thread. The adapter now uses one dedicated owner thread and command queue, allowing multiple UI requests to reuse one browser session without the former `cannot switch to a different thread` failure.

Real production UI verification covered URL navigation and page title, screenshots, opening tabs, switching tabs, and follow-up research in the same browser session. Invalid URLs, unsupported actions, blocked pages, login walls, empty pages, and provider failures return controlled errors. SafetyGate remains authoritative for uploads, downloads, form submission, purchases, account changes, and other mutations.

## Live research repairs

The original failure was caused by unusable or unrelated provider records being accepted as success, browser fallback receiving conversational wrapper text, and Chromium’s visible RSS representation not being parsed correctly. Repairs include provider-originated relevance filtering, topical query normalization, search-homepage and unrelated-result rejection, Google News RSS item-block parsing with raw XML link extraction, Bing redirect decoding, publisher-source retries, and rejection of login/challenge/empty-result pages.

The production hierarchy is fast provider search first, then bounded Chromium search/news/shopping/retailer fallback when evidence is unusable. Google News RSS records are opened through the browser path; when a proxy page has insufficient content, the associated publisher source is retried. Product research also attempts bounded public shopping and retailer pages but rejects generic shells and login pages.

Product answers include typed, source-linked public result evidence where available and state explicitly when the limited sources do not establish a globally cheapest option. Freya does not fabricate prices or exhaustive market coverage.

## Routing and lifecycle repairs

Existing research metadata was expanded for product discovery, shopping research, price lookup/comparison, availability, specifications, reviews, current news, current processors, and explicit browser URLs. Deterministic routing now wins before generic planning, so shopping requests do not fall through to `list_files`, `show_memory`, `automation`, or `system_status`.

Freshness-sensitive and shopping/current-price requests require external evidence while stable questions preserve local-knowledge-first behavior. The frontend request window is **180 seconds**; backend research is bounded to **120 seconds**, direct chat to **90 seconds**, and browser actions to **45 seconds**. These are bounded and configurable, not unlimited. Deterministic browser/research requests bypass the planner.

## Permanent regressions

`tests/test_pasted18_live_paths.py` contains **15 passing tests** covering current-information routing, product/shopping/review routing, browser precedence, unrelated-tool avoidance, browser research fallback, page-reading fallback, Bing redirect decoding, Google News RSS parsing, and external-evidence classification.

`tests/test_browser_playwright_smoke.py` uses the Playwright-managed Chromium runtime. The browser smoke and browser capability tests passed. The frontend production build also passed.

## Real UI acceptance

Freya was started through `run_freya.ps1 -NoBrowser`. A real Playwright frontend script submitted ten normal messages through `http://127.0.0.1:5173/`; all ten completed without frontend timeout:

| Prompt | Outcome |
|---|---|
| Open `https://example.com` and tell me the page title | **PASS** — returned `Example Domain`. |
| What is the latest CPU of Intel today? | **PASS** — current Intel/Nova Lake evidence and source links returned; partial caveat preserved. |
| Open Intel’s website and find its newest desktop processor | **PASS** — Intel/Nova Lake and newsroom evidence returned. |
| Find the cheapest 32GB DDR5 RAM | **PASS with bounded-source caveat** — live RAM deal/price evidence returned; no unsupported global-cheapest claim. |
| Compare RTX 5070 prices | **PASS with conflict caveat** — current price-related evidence and conflicts reported. |
| Find reviews for one of the RAM kits | **PASS with partial-source caveat** — completed without unrelated-tool routing or fabricated certainty. |
| Search the latest Nvidia news | **PASS** — NVIDIA newsroom and public news sources returned. |
| Take a screenshot of the current page | **PASS** — screenshot captured locally. |
| Open another tab and search for AMD’s latest desktop CPU | **PASS** — tab opened and follow-up research completed. |
| Go back to the first tab | **PASS** — tab switch completed. |

The final result file recorded `success: true` for all ten prompts. Observed research/product requests remained within the 180-second frontend window.

## Verification summary

| Verification | Result |
|---|---:|
| Backend Python compilation | **PASS** |
| Frontend `pnpm --dir client build` | **PASS** |
| Pasted18 permanent regressions | **15 passed** |
| Browser smoke and browser capability tests | **6 passed** |
| Routing matrix | **210/210 passed** |
| Pasted15/pasted16/pasted17 focused tests | **Passed in the completed focused run** |
| Research, safety, HTTP, and autonomous integration checks | **Passed after compatibility repair** |
| Normal launcher readiness | **Backend and frontend passed** |
| Real frontend acceptance | **10/10 completed** |

## Files changed

Production: `app/browser/adapter.py`, `app/browser/capability.py`, `app/capabilities/registration_bridge.py`, `app/intent/classifier.py`, `app/research/capability.py`, `client/src/pages/Home.tsx`, and `ui_server.py`.

Permanent verification/audit: `tests/test_browser_playwright_smoke.py`, `tests/test_pasted18_live_paths.py`, `CAPABILITY_HEALTH_AUDIT.md`, and this file.

Temporary pasted18 probes, logs, and screenshots were removed. Unrelated `AGENTS.md`, `.freya-index.json`, `PASTED15_FINAL_REPORT.md`, monitoring data, and pasted17 local probe artifacts were left untouched.

## Remaining limitations

Public providers can still expose bot checks, locale pages, malformed HTML, and conflicting claims. Freya reports these conditions and marks results partial rather than treating them as reliable evidence. Product research is a bounded-source comparison, not exhaustive market coverage. Authenticated sites, purchases, account changes, and mutations require configured providers and SafetyGate approval.

The owner-thread queue serializes Playwright operations for correctness and intentional session reuse; it does not provide unlimited parallel pages. Frontend abort does not forcibly terminate Python already running inside a lower-level provider thread, although provider and browser timeouts remain bounded and adapter shutdown is clean.

These are **non-blocking limitations for the verified read-only MVP path**, not hidden success paths or unreported broken behavior.
