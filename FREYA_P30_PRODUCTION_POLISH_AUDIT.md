# Freya Pasted30 Production Polish Audit

## Root cause found

The reported `ryzen 7 5700x vs i5 14400` failure was caused by contextual CPU-family inheritance. The comparison resolver saw `Ryzen` on the first side and inherited the AMD Ryzen family for the second side, producing the invalid canonical entity `AMD Ryzen I5 14400`. That contaminated every downstream search query and prevented reliable Intel evidence retrieval.

## Implemented corrections

The CPU resolver now recognizes Intel Core shorthand independently from the other comparison side. `i5 14400`, `i5-14400`, `Intel i5 14400`, and `Intel Core i5-14400` normalize to `Intel Core i5-14400`. Ryzen shorthand remains supported, including `Ryzen 7600`, `Ryzen 9600X`, and `Ryzen 7 5700X`. A validation guard rejects any CPU entity whose canonical manufacturer contradicts its raw text.

The comparison action now emits structured matrix state to `/api/chat`. The frontend renders that state as a real comparison panel with a heading, evidence status, readable table, explicit “Not verified” cells, evidence-gap callouts, bottom-line guidance, and clickable source cards. It no longer relies on raw Markdown embedded in the answer string.

The general assistant renderer now handles basic emphasis and links, while the central research formatter removes raw provider diagnostics from user-facing text. Provider failures are summarized as “Some public sources were unavailable or unreadable; the comparison uses the evidence that remained.” Internal exception names, DDGS errors, HTTP errors, tracebacks, and raw fetch failures are not shown in the main answer.

## Live acceptance

The final live request was:

> `ryzen 7 5700x vs i5 14400`

The backend returned HTTP 200 with `response_type: comparison`. The canonical entities were `AMD Ryzen 7 5700X` and `Intel Core i5-14400`. Planned queries included `Intel Core i5-14400 official specifications` and `AMD Ryzen 7 5700X vs Intel Core i5-14400 benchmark comparison`; no `AMD Ryzen i5` query was generated.

The returned comparison state was `PARTIAL_BUT_USEFUL`, with four source citations and explicit missing dimensions. The answer contained no raw Markdown table syntax, no bold Markdown markers, and no `HTTPError`, `DDGSException`, traceback, or raw provider-fetch diagnostic.

## Verification

The focused Pasted30 and comparison suite passed **17 tests** after the CPU and presentation fixes. The broader focused Pasted23, Pasted26, Pasted27, Pasted28, Pasted29, automatic-routing, and Pasted30 collection contains **79 tests**, and the focused run passed. The modified Python modules compiled successfully, and the React frontend production build completed successfully with Vite.

## Acceptance interpretation

This fixes the blocking entity-resolution defect and the presentation defect visible in the supplied screenshot. The comparison is now honest about partial evidence without exposing internal implementation failures, and the user receives a structured, readable result rather than a raw research trace.
