# Freya Native Web Search Implementation Report

## Verdict

**PASS WITH SPECIFIC LIMITATIONS.** Freya now contains a Jan-style native `web_search` plus `web_fetch` path. Exa keyless mode was verified live against `https://mcp.exa.ai/mcp`, the project adapter normalized three ranked results for a current GPU query, and the bounded page reader successfully returned readable content from a public HTML page. The real browser/UI model loop was not fully exercised because this verification environment did not provide a running tool-capable Ollama model session; the loop is covered with deterministic fake-model tests.

## Audit result

The old normal web path was the UI server's `_research_text_request()` branch. It classified freshness-sensitive requests before the local model, invoked `research_capability` directly, used the older DDGS/importer/Bing/HTML adapter chain, filtered and ranked results with research-specific heuristics, fetched pages through the legacy `WebPageReader`, and finally synthesized or formatted the result through `SynthesisEngine` and `ResponseFormatter`. The model did not receive native tool schemas and could not decide which result to fetch or whether to search again.

This explains the poor behavior for requests such as “what is the best GPU right now?”: snippets and provider-specific records were routed through a large deterministic research pipeline before a tool-capable local model could inspect sources. The new UI path bypasses that old answer-producing branch for ordinary external textual questions and invokes the model-controlled native tool loop instead. Specialized image and shopping paths remain on their existing capability routes.

## Files changed

| Area | Files | Change |
|---|---|---|
| Native web tools | `app/research/native_web_tools.py` | Added `SearchResult`, `FetchResult`, Exa, SearXNG, Bing HTML fallback, SSRF-aware bounded readable fetch, normalized errors, schemas, and ToolManager registration. |
| Model loop | `app/core/tool_loop.py` | Added bounded model → tool → result → model iteration with maximum consecutive/search/fetch call limits. |
| LLM transport | `app/core/llm.py`, `app/core/priority_llm.py`, `app/providers/resilient.py`, `app/providers/ollama.py` | Added structured tool-capable requests, raw provider response preservation, dict-based message support, and model capability detection. |
| Canonical wiring | `app/agent/facade_impl.py`, `app/research/capability.py` | Exposed the native loop through the canonical facade and registered exact `web_search`/`web_fetch` tool names in the existing ToolManager. |
| UI/settings | `ui_server.py`, `client/src/pages/Home.tsx`, `client/src/index.css`, `.env.example` | Added settings GET/POST endpoints, a Web Search settings panel, Exa/SearXNG/Bing selection, enable/disable state, and documented environment variables. |
| Tests | `tests/test_native_web_tools.py` | Added focused contract, fallback, extraction, schema, iterative-loop, and non-tool-model tests. |

## Contracts and behavior

### `web_search`

The native schema is a single required `query` string plus optional integer `count`. Count defaults to 5 and is clamped to a maximum of 20. Successful output contains only normalized records with `title`, `url`, `snippet`, and nullable `published_at`. Duplicate URLs, tracking-only variants, empty titles, and malformed records are removed before the model sees results.

### `web_fetch`

The native schema accepts one required `url`. Only public `http://` and `https://` URLs are accepted; embedded credentials, localhost, private IPs, loopback, link-local, reserved, and invalid targets are rejected. Redirect destinations are revalidated. HTML, XHTML, plain text, and JSON are accepted; unsupported content types, HTTP errors, TLS failures, timeouts, empty extraction, and oversized responses become structured tool errors rather than conversation crashes.

Readable extraction removes scripts, styles, navigation, footer, header, aside, forms, templates, and SVG elements, then normalizes whitespace. The default model-facing bound is 40,000 characters, configurable through `FREYA_WEB_FETCH_MAX_CHARS`; truncation prefers a sentence boundary when one is available. Title, publication date, and author metadata are preserved only when reliably discoverable.

### Provider order and errors

Exa is the default provider. With no API key, the adapter uses Jan's keyless hosted MCP-compatible endpoint and parses its native `web_search_exa` response. With `EXA_API_KEY`, it uses Exa's structured REST search endpoint. A configured SearXNG URL is available as a fallback, and Bing HTML is retained as a final free fallback. Provider failure is distinct from a successful provider returning no results: failures return structured codes such as `EXA_NETWORK_FAILURE`, `EXA_TIMEOUT`, `SEARXNG_NETWORK_FAILURE`, or `search_failed`, while no results return an empty list.

The implementation does not require an Exa MCP configuration for normal Freya operation. The Exa hosted endpoint is called directly by the native provider adapter, not through Freya's external MCP registry.

## Tool registration and model capability detection

Exact names `web_search` and `web_fetch` are registered in the canonical initializer-owned ToolManager through `ResearchCapability.set_tool_manager()`. The model loop advertises only those two schemas, and only after the configured local-model path reports tool support. Ollama capability detection queries `/api/show` and checks the reported `tools` capability. Models that do not advertise tools receive a bounded `tools_unsupported` result and are not given unusable definitions.

Ollama assistant messages with structured `tool_calls` are preserved as assistant messages, tool outputs are returned as `role=tool` messages, and subsequent model turns receive the full bounded context. The loop permits repeated search/fetch decisions and stops at eight consecutive web calls, four searches, or six fetches. At the limit, it asks the model to answer from accumulated evidence rather than hanging.

## Settings

The UI now exposes Enable Web Search, Search Provider, and SearXNG URL. Exa API keys are intentionally not echoed back to the browser; the settings response reports only whether a key is configured. Environment defaults are:

| Setting | Default |
|---|---|
| `FREYA_WEB_SEARCH_ENABLED` | `true` |
| `FREYA_WEB_SEARCH_PROVIDER` | `exa` |
| `EXA_API_KEY` | unset; keyless mode remains active |
| `FREYA_SEARXNG_URL` | unset |
| `FREYA_WEB_FETCH_MAX_CHARS` | `40000` |

## Verification

The focused native tests passed: **26 tests passed** across `test_native_web_tools.py`, `test_web_search_fallback.py`, and `test_automatic_research_routing.py`. The frontend TypeScript/Vite build passed with `pnpm run build`. A live Exa keyless probe returned three ranked GPU results with real URLs, snippets, and publication dates. A live project fetch probe returned readable content from `https://example.com` within the configured bound.

The related architecture/tool/http test group produced **32 passed and 1 failure**. The failure is in the pre-existing `test_target_resolver_preserves_retrieved_evidence_for_verifier`: its `SimpleNamespace` test double provides `find_matching()` but not the resolver's already-required `execute_named()` method. The failure is outside the modified native web-tool path, and no resolver code was changed for this task.

The six requested query patterns are supported by the new architecture as follows: current GPU and NVIDIA questions invoke model-controlled search; comparison requests can search and fetch multiple sources; direct article summaries can invoke `web_fetch`; insufficient first results permit another search or fetch; and provider failures return bounded structured errors so the model can try another source or answer safely. Full UI acceptance of those exact prompts remains pending a running tool-capable local Ollama model.

## Before/after path

| Before | After |
|---|---|
| User query → freshness classifier → `research_capability` → DDGS/importer/Bing search → deterministic filtering and legacy page reader → synthesis/formatter. | User query → tool-capable local model → native `web_search` → model selects source → native `web_fetch` → bounded readable page → model may search/fetch again → final natural answer. |

The new path preserves the existing canonical registry, safety boundaries, memory, and optional MCP integrations. It does not add a research planner, evidence graph, new router, or second capability registry.

## References

[1]: https://www.jan.ai/changelog/2026-07-21-jan-v0.8.4 "Jan v0.8.4: Native Web Search, Per-Model Chat Templates & a Backend Settings Store"
[2]: https://github.com/janhq/jan/blob/main/src-tauri/plugins/tauri-plugin-websearch/src/provider.rs "Jan native web-search provider implementation"
[3]: https://github.com/janhq/jan/blob/main/web-app/src/lib/webSearchTool.ts "Jan native web-search tool schemas and execution"
