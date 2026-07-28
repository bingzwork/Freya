# Natural Conversation

> **Pillar Status:** 🟢 MOSTLY COMPLETE · **Completion:** 90% · **Last Updated:** 2026-07-28 (Implemented User Communication Principles in the runtime: `_format_generic` prefers the hand-written response message so internal field names do not leak to users; conversational control replies are plain English. Same principles are now also documented and enforced for the LLM-bound clarifying and low-confidence prompts in `FreyaAgent.run`.)

---

## Overview

Freya's natural conversation pipeline is mature.

The system distinguishes between general conversation, knowledge questions, system status requests, meta-commands, and software engineering tasks. The routing architecture is implemented and operational.

This document is the design specification for the natural conversation pillar. It defines:

- The capabilities that compose the conversation surface.
- The intent classification and routing layers.
- Conversational control semantics.
- The behavioral acceptance tests that validate correct routing.
- Open improvements and the single source of truth for unfinished work.

Future work focuses on natural-language nuance (ambiguity, summarization, entity resolution), not on the core request flow described here.

---

## User Communication Principles

This section governs how Freya speaks to users across the entire project. It applies to every reply Freya produces — greetings, status replies, control acknowledgements, clarifying questions, planning progress, tool-call explanations, and error messages. The runtime enforces these principles today; see `app/capabilities/formatter.py` and `app/agent/core_agent.py` for the implementation.

### Core Principles

Freya's communication with users follows these principles:

- **Natural, conversational tone.** Freya sounds like a helpful AI assistant, not a debugger, log file, or software engineer.
- **Plain English.** Prefer simple, everyday words. Avoid jargon, internal terms, and unnecessary vocabulary.
- **Hide implementation details.** Never expose internal architecture, routing, prompts, classifiers, confidence scores, pipelines, handlers, planners, or other internal systems unless the user explicitly asks.
- **User-goal framing.** Describe actions in terms of what the user is trying to accomplish, not how the system works.
- **Concise and friendly.** Keep replies short, easy to understand, and human. One or two sentences is usually enough.
- **Short clarifying questions.** When Freya is unsure, ask one paraphrased question. Multi-choice menus feel mechanical and are forbidden.
- **Brief acknowledgements.** Confirm in a line or two — never a paragraph.

### When Technical Language Is Allowed

Freya MAY use technical terminology only when one of the following is true:

- The user explicitly requests technical detail (e.g., "show me the routing decision").
- The user is performing software engineering work (e.g., debugging, code review, system administration).
- Technical accuracy requires it (e.g., quoting a stack trace or explaining a config value).

Otherwise, plain English wins.

### Examples

- **Don't say:** "The request was routed to the engineering planner."
  **Say:** "I'm working on your request."

- **Don't say:** "Intent classification confidence is low."
  **Say:** "I'm not completely sure what you mean. Could you clarify?"

- **Don't say:** "The runtime selected a different handler."
  **Say:** "I found a better way to help with your request."

- **Don't say:** `control_command: stop`.
  **Say:** "Stopped. What's next?"

These principles apply project-wide. Implementation details belong in architecture and developer-facing sections, never in user-facing responses.

---

## Architecture at a Glance

```
User Input ─▶ Normalization ─▶ Intent Classification ─▶ Routing ─▶ Handler
                                                                │
                                                                ├─▶ Direct Answer
                                                                ├─▶ Conversational Control
                                                                ├─▶ Engineering Planner
                                                                └─▶ General Conversation
```

Each intent classification produces exactly one of the eight intents listed in the Capability Summary, with a confidence score. Routing applies the rules in [Routing Semantics](#routing-semantics) to select a handler.

---

## Capability Summary

| # | Capability                      | Status          | Completion |
|---|---------------------------------|-----------------|-----------:|
| 1 | Intent Classification           | ✅ COMPLETE     | 100%       |
| 2 | Capability Routing              | ✅ COMPLETE     | 100%       |
| 3 | Runtime Context                 | ✅ COMPLETE     | 100%       |
| 4 | Conversation History            | ✅ COMPLETE     | 100%       |
| 5 | Direct Answer Routing           | ✅ COMPLETE     | 100%       |
| 6 | Conversational Control          | 🟡 PARTIAL     | 90%        |
| 7 | Greeting Handling               | ✅ COMPLETE     | 100%       |
| 8 | Knowledge Question Handling     | ✅ COMPLETE     | 100%       |
| 9 | System Status Detection         | ✅ COMPLETE     | 100%       |
| 10| Engineering Task Detection      | ✅ COMPLETE     | 100%       |

`🟡 PARTIAL` on Conversational Control reflects that the unified stop / cancel / undo surface is now centralized in `ConversationalControlHandler` and `FreyaAgent.run` short-circuits to it via `classification.is_control`, but the underlying effect on a hypothetical in-flight planner is not yet hooked up. Today's runtime invokes these handlers synchronously from `run()`, so the handlers emit an acknowledgement signal via `result.data["control_command"]`.

---

## Intent Classification

**Status:** ✅ COMPLETE
**Completion:** 100%
**Current State:** Implemented and integrated into the runtime.

Implemented Features

- Keyword-based intent classification
- Pattern matching
- Confidence scoring
- Intent routing
- Engineering request detection
- General conversation detection
- Knowledge question detection
- System status detection

Missing

None

Known Bugs

None

Technical Debt

Current implementation is rule-based.

Needs Improvement

- Statistical intent classification
- Improved ambiguity handling (see [When Ambiguous](#when-ambiguous))

---

## Capability Routing

**Status:** ✅ COMPLETE
**Completion:** 100%
**Current State:** Implemented and integrated.

Implemented Features

- Direct answer routing
- Conversation routing
- Engineering routing

Routing rules — including priority, conflict resolution, and low-confidence fallback — are specified in [Routing Semantics](#routing-semantics).

Missing

None

Known Bugs

None

Technical Debt

None

Needs Improvement

- Dynamic capability discovery

---

## Runtime Context

**Status:** ✅ COMPLETE
**Completion:** 100%
**Current State:** Implemented and integrated.

Implemented Features

- Runtime context selection
- Intent-aware context injection

Missing

None

Known Bugs

None

Technical Debt

None

Needs Improvement

- Smarter context compression

---

## Conversation History

**Status:** ✅ COMPLETE
**Completion:** 100%
**Current State:** Implemented and integrated.

Implemented Features

- Multi-turn history (in-memory)
- Conversation persistence (disk save/load)
- Prompt context injection (turns assembled into the LLM prompt)

Missing

None

Known Bugs

Previously missing conversation history injection has been resolved.

Technical Debt

None

Needs Improvement

- Long-term conversation summarization

---

## Direct Answer Routing

**Status:** ✅ COMPLETE
**Completion:** 100%
**Current State:** Implemented and integrated.

Implemented Features

- Greeting responses
- General knowledge responses
- System status responses
- General conversation mode

Missing

None

Known Bugs

Previous issue where simple questions incorrectly entered the engineering planner has been resolved.

Technical Debt

None

Needs Improvement

- Better routing confidence thresholds

---

## Conversational Control

**Status:** 🟡 PARTIAL
**Completion:** 90%
**Current State:** Implementation centralized in `app/capabilities/handlers.py:ConversationalControlHandler`. Patterns and keywords register five capabilities (`control_stop`, `control_cancel`, `control_undo`, `control_redo`, `control_status`) all bound to the new `IntentType.CONVERSATIONAL_CONTROL`. `FreyaAgent.run` short-circuits when `classification.is_control` is true, routing via `route_query` and `format_capability_result` without invoking the LLM.

### Purpose

Conversational control covers short, imperative meta-commands that interrupt or steer the current flow rather than contribute to it. These commands must short-circuit routing regardless of any other signal in the input.

### Supported Commands

| Command | Trigger phrases                          | Behavior                                                                                           |
|---------|------------------------------------------|----------------------------------------------------------------------------------------------------|
| `stop`  | `stop`, `halt`, `wait`                    | Interrupt the in-flight planner or LLM call. Returns control to the user with a brief acknowledgement. |
| `cancel`| `cancel`, `nevermind`, `abort`           | Cancel any pending action before execution. No-op when nothing is pending.                         |
| `undo`  | `undo`, `revert`                         | Revert the most recent mutation. Only meaningful when at least one mutation has been applied.       |
| `redo`  | `redo`                                   | Re-apply the most recently undone mutation. No-op when nothing has been undone.                    |
| `status`| `status`, `what are you doing?`          | Return a brief, user-friendly summary of what Freya is currently doing. Internal identifiers (plan ID, step number) are shown only when the user explicitly asks.      |

### Routing Rule

Conversational control is the highest-priority intent. When classification produces a control intent, the dispatcher MUST bypass all other routing decisions and return the control response without invoking the engineering planner or the general conversation flow.

### Behavioral Rules

- `stop` and `cancel` MUST be safe to issue at any point, including during a mutating confirmation prompt. The approval flow integrates via `HUMAN_OVERSIGHT.md`.
- `undo` MUST scope to mutations performed in the current session. It MUST NOT undo operations from a previous session.
- If `undo` is requested and no mutations have been performed in this session, respond conversationally with a one-line acknowledgement rather than an error.

Missing

- Cross-session undo.
- Hooks between control commands and any future in-flight planner cancellation.

Known Bugs

None

Technical Debt

None

Needs Improvement

- Centralize the control flow into one handler.
- Extend `undo` to support multi-step revert.

---

## Routing Semantics

### Priority Order

`IntentType.routing_priority` returns a numeric priority per intent (lower is higher priority). Conversational control is 0; engineering is 2; chat/question is 3. `FreyaAgent.run` dispatches on this property:

1. **Conversational Control** — `IntentType.CONVERSATIONAL_CONTROL` (priority 0). `FreyaAgent.run` short-circuits to `route_query` via `app.capabilities.handlers.ConversationalControlHandler`. Never reaches the LLM.
2. **Direct Answer** — handled before further analysis. Comprises:
   - Greeting detection (e.g., `hi`, `hello`)
   - System status detection (e.g., `python version?`, `disk space?`)
   - General knowledge questions that can be answered without tooling.
3. **Engineering Intent** — TASK, FILE_OPERATION, CODE_TASK, GIT_OPERATION, TOOL_REQUEST, and any direct-answer fallback rejected as engineering. Routed to the engineering planner.
4. **General Conversation** — CHAT and QUESTION. Routed to the LLM with the conversation history and runtime context.

### Conflict Resolution

The `IntentClassifier.classify` method picks the intent with the highest raw score. When two intents score within `0.02` of each other (`abs(best - second_best) < 0.02`), the code currently lets Python's `max()` pick the first one in iteration order; `IntentType` ordering has CHAT/QUESTION ahead of engineering. Tied keys (`score == 0.0`) fall back to CHAT (the General Conversation tier) per the no-signal fallback.

Capability routing prefers the highest-confidence capability. Patterns over keywords. Patterns cap at `0.98`; keyword expansion adds up to `0.97`. This means a strong pattern beats any keyword match.

### Low-Confidence Fallback

The classifier assigns a confidence score in `[0.0, 1.0]`. Thresholds live as constants in `app.intent.classifier`:

- `ACCEPT_CONFIDENCE_THRESHOLD = 0.70`
- `LOW_CONFIDENCE_THRESHOLD = 0.40`

`IntentClassification` exposes boolean properties (`is_ambiguous`, `is_low_confidence`, `is_control`) for callers. `FreyaAgent.run` reads these via module-level helpers (`should_clarify`, `is_low_confidence`, `is_control_intent`). When `should_clarify` is true, the runner asks a paraphrased clarifying question. When `is_low_confidence` is true and the intent is direct-answerable, the runner flags the prompt and proceeds.

No-signal fallback: when no pattern or keyword matched any intent, `classify()` returns CHAT with `confidence = 0.0`, which surfaces as `is_low_confidence = True` to callers.

---

## When Ambiguous

Some inputs carry more than one plausible intent. The current rule-based classifier does not flag ambiguity; this section specifies the policy the runtime MUST apply when ambiguity is detected.

### Ambiguous Compound Inputs

When the user input is a compound sentence with multiple intents, e.g., `"Hi, also fix the imports"`:

| Primary intent          | Secondary signal                  | Policy                                               |
|-------------------------|-----------------------------------|------------------------------------------------------|
| Engineering intent      | Greeting                          | Treat as engineering; sustain greeting tone in reply.|
| Engineering intent      | Knowledge question                | Treat as engineering; ignore the secondary.          |
| Direct Answer           | Engineering hint                  | Re-check classifier; the direct answer wins.         |
| Conversational Control  | Anything                          | Control intent wins. Always.                         |

### Below-Threshold Input

When classifier confidence is below `0.40`, the runtime MUST:

1. Default to **General Conversation**.
2. Add the original user input verbatim to the LLM prompt so the LLM has full context.
3. The reply should briefly acknowledge that Freya is unsure what the user wants — but only if the threshold is far enough below `0.40` to warrant surfacing.

Today, `FreyaAgent.run` appends a low-confidence banner to the prompt when `classification.is_low_confidence` is true and the intent is direct-answerable. Engineering-intent inputs with low confidence currently still flow into the planning pipeline; flagging them for low-confidence fallback is tracked in the Implementation Roadmap.

### Mid-Band Input (`0.40 ≤ confidence < 0.70`)

The runtime asks **one** clarifying question. The clarifying question is a paraphrase, not multiple-choice. Today, `FreyaAgent.run` consults `should_clarify(classification)` and short-circuits to a paraphrased LLM reply before any other routing. The exact low-band confidence of the keyword-only classifier rarely falls in the mid-band (single-keyword matches score ~`0.15`), so this path is currently exercised mostly by callers who construct `IntentClassification` with mid-band confidence via `dataclasses.replace`.

Multi-choice menus are forbidden — they feel mechanical.

### Best-Guess Policy

When clarification is impossible (e.g., mid-band on a one-shot tool call), the runtime picks the highest-confidence intent and proceeds. Low-confidence prompts are recorded into `ProjectMemory` via the existing `memory.record(...)` path with an explicit `"clarification"` or `"low_confidence"` marker.

---

## Acceptance Tests / Behavioral Checks

These are the behavioral checks that gate a "complete" status on each capability. The runtime MUST pass each of these tests; any failure is a regression.

### Intent Classification

| # | Input                       | Expected intent   |
|---|-----------------------------|-------------------|
| 1 | `hi`                        | CHAT              |
| 2 | `what is recursion?`        | QUESTION          |
| 3 | `fix the login bug`         | TASK              |
| 4 | `list the files`            | FILE_OPERATION    |
| 5 | `refactor the auth module`* | CODE_TASK         |
| 6 | `what's my python version?` | SYSTEM_STATUS     |
| 7 | `commit my changes`         | GIT_OPERATION     |
| 8 | `search the web for X`      | TOOL_REQUEST      |

\* `refactor` is a strong CODE_TASK signal even though it is also a verb in chat.

### Routing

| # | Intent         | Expected routing target              |
|---|----------------|--------------------------------------|
| 1 | CHAT           | General Conversation                 |
| 2 | QUESTION       | General Conversation (knowledge path)|
| 3 | TASK           | Engineering Planner                  |
| 4 | FILE_OPERATION | Engineering Planner                  |
| 5 | CODE_TASK      | Engineering Planner                  |
| 6 | SYSTEM_STATUS  | Direct Answer                        |
| 7 | GIT_OPERATION  | Engineering Planner                  |
| 8 | TOOL_REQUEST   | Direct Answer or Engineering Planner |

### Conversational Control

| # | Input        | Expected behavior                                                            |
|---|--------------|------------------------------------------------------------------------------|
| 1 | `stop`       | Interrupt in-flight planner. Acknowledge briefly with `"Stopped. What's next?"`. Never expose internal field names like `control_command`. |
| 2 | `cancel`     | Cancel any pending action. No-op when nothing pending. Acknowledge with `"Cancelled."`. Never expose internal field names. |
| 3 | `undo`       | Revert last mutation in current session.                                      |
| 4 | `undo` (no mutations) | Conversational one-liner (`"Nothing to undo in this session."`), not an error. |
| 5 | `status`     | Brief, user-friendly summary. No internal identifiers unless asked.          |
| 6 | `Hi, stop`   | Conversational control wins; ignore greeting.                                 |

### Ambiguity

| # | Input                   | Expected behavior                                              |
|---|-------------------------|----------------------------------------------------------------|
| 1 | `Hi, also fix the bug`  | Engineering with greeting tone sustainer.                      |
| 2 | `fix this` (mid-band)   | Single paraphrased clarifying question.                        |
| 3 | Empty input             | Ask user to clarify what they want.                            |
| 4 | Single emoji 🙂          | General conversation reply.                                    |
| 5 | Unknown jargon `<x>`    | Best-guess to General Conversation; log `low_confidence=true`. |

### Conversation History / Runtime Context

| # | Input                              | Expected behavior                                |
|---|------------------------------------|--------------------------------------------------|
| 1 | `thanks` (after a prior turn)      | Reply with awareness of prior turn.              |
| 2 | `what about now?` (follow-up)      | Reply uses prior turn to interpret `now`.        |
| 3 | `cancel that` (after a request)    | Conversational control wins; cancel applies.     |

### Direct Answer

| # | Input           | Expected behavior                                       |
|---|-----------------|---------------------------------------------------------|
| 1 | `hi`            | Greeting reply, no LLM call.                           |
| 2 | `python version`| Direct answer from runtime, no LLM call.               |
| 3 | `disk usage?`   | Direct answer from runtime, no LLM call.               |
| 4 | `time?`         | Direct answer from runtime, no LLM call.               |

### Mismatches to Avoid

These inputs MUST NOT enter the engineering planner:

- Pure greetings.
- Pure system status questions.
- Pure knowledge questions.
- Conversational control commands.

---

## Missing Capabilities

| Capability                       | Priority | Status              |
|----------------------------------|----------|---------------------|
| Statistical Intent Classification| Medium   | ⚪ NOT IMPLEMENTED  |
| Entity Extraction                | Medium   | ⚪ NOT IMPLEMENTED  |
| Slot Filling                     | Medium   | ⚪ NOT IMPLEMENTED  |
| Multi-Intent Detection           | Low      | ⚪ NOT IMPLEMENTED  |
| User Preference Learning         | Low      | ⚪ NOT IMPLEMENTED  |

---

## Open Bugs

None currently identified.

---

## Technical Debt

- Rule-based intent classification should eventually be enhanced with statistical or semantic intent recognition.

---

## Implementation Roadmap

These items track the work open in this pillar. Items are checked off only when their corresponding doc section is implemented AND the acceptance tests pass.

Spec + code complete in this revision:

- [x] Acceptance Tests / Behavioral Checks section, with concrete tests added to `tests/test_intent_classification.py`, `tests/test_capability_routing.py`, and `tests/test_agent_conversation.py`.
- [x] Routing Semantics section, implemented via `IntentType.routing_priority`, `classify()` no-signal fallback, and the dispatch logic in `FreyaAgent.run`.
- [x] When Ambiguous section, implemented via `IntentClassification.is_ambiguous` / `is_low_confidence` properties and the `should_clarify` / `is_low_confidence` module helpers used in `FreyaAgent.run`.
- [x] Conversational Control capability, implemented via `IntentType.CONVERSATIONAL_CONTROL`, `ConversationalControlHandler`, and the `classification.is_control` short-circuit in `FreyaAgent.run`.

Improvements beyond Missing Capabilities:

- [ ] Centralize Conversational Control fully: hook the dispatched control commands to actual planner interrupt and mutation history (currently the handlers emit an acknowledgement).
- [ ] Better ambiguity detection — extend the mid-band to engineering intents with low confidence and apply the clarification policy there.
- [ ] Long-term conversation summarization
- [ ] Statistical intent classification

---

## Section Summary

| Category                | Count                                                     |
|-------------------------|-----------------------------------------------------------|
| ✅ Completed Capabilities | 9                                                       |
| 🟡 Partial Capabilities   | 1                                                       |
| 🔵 Foundation Capabilities| 0                                                       |
| ⚪ Not Implemented       | 5                                                         |
| Overall Pillar Status   | 🟢 MOSTLY COMPLETE                                       |
