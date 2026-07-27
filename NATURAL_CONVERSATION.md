# Natural Conversation

> **Pillar Status:** 🟢 MOSTLY COMPLETE · **Completion:** 90% · **Last Updated:** 2026-07-27

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
| 6 | Conversational Control          | 🟡 PARTIAL     | 80%        |
| 7 | Greeting Handling               | ✅ COMPLETE     | 100%       |
| 8 | Knowledge Question Handling     | ✅ COMPLETE     | 100%       |
| 9 | System Status Detection         | ✅ COMPLETE     | 100%       |
| 10| Engineering Task Detection      | ✅ COMPLETE     | 100%       |

`🟡 PARTIAL` on Conversational Control reflects that the capability is now formally defined by this document and the approval flow exists in the runtime (see `HUMAN_OVERSIGHT.md`), but the unified stop / cancel / undo surface is not yet centralized.

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
**Completion:** 80%
**Current State:** Capability defined in this document. Individual handlers (interrupt, undo of the last mutation) exist in the runtime; the unified control surface is not yet centralized behind a single dispatcher.

### Purpose

Conversational control covers short, imperative meta-commands that interrupt or steer the current flow rather than contribute to it. These commands must short-circuit routing regardless of any other signal in the input.

### Supported Commands

| Command | Trigger phrases                          | Behavior                                                                                           |
|---------|------------------------------------------|----------------------------------------------------------------------------------------------------|
| `stop`  | `stop`, `halt`, `wait`                    | Interrupt the in-flight planner or LLM call. Returns control to the user with a brief acknowledgement. |
| `cancel`| `cancel`, `nevermind`, `abort`           | Cancel any pending action before execution. No-op when nothing is pending.                         |
| `undo`  | `undo`, `revert`                         | Revert the most recent mutation. Only meaningful when at least one mutation has been applied.       |
| `redo`  | `redo`                                   | Re-apply the most recently undone mutation. No-op when nothing has been undone.                    |
| `status`| `status`, `what are you doing?`          | Return a developer-friendly description of the current plan, step, and last completed action.      |

### Routing Rule

Conversational control is the highest-priority intent. When classification produces a control intent, the dispatcher MUST bypass all other routing decisions and return the control response without invoking the engineering planner or the general conversation flow.

### Behavioral Rules

- `stop` and `cancel` MUST be safe to issue at any point, including during a mutating confirmation prompt. The approval flow integrates via `HUMAN_OVERSIGHT.md`.
- `undo` MUST scope to mutations performed in the current session. It MUST NOT undo operations from a previous session.
- If `undo` is requested and no mutations have been performed in this session, respond conversationally with a one-line acknowledgement rather than an error.

Missing

- Centralized dispatcher behind a single capability handler.
- Cross-session undo.

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

Intent classification returns eight intents (CHAT, QUESTION, TASK, FILE_OPERATION, CODE_TASK, SYSTEM_STATUS, TOOL_REQUEST, GIT_OPERATION, plus the implicit CONVERSATIONAL_CONTROL family). The routing layer applies the following priority order:

1. **Conversational Control** — executed first when matched. Short-circuits all other routing. See [Conversational Control](#conversational-control).
2. **Direct Answer** — handled before further analysis. Comprises:
   - Greeting detection (e.g., `hi`, `hello`)
   - System status detection (e.g., `python version?`, `disk space?`)
   - General knowledge questions that can be answered without tooling.
3. **Engineering Intent** — TASK, FILE_OPERATION, CODE_TASK, GIT_OPERATION, and any direct-answer fallback rejected as engineering. Routed to the engineering planner.
4. **General Conversation** — CHAT and QUESTION. Routed to the LLM with the conversation history and runtime context.

### Conflict Resolution

The dispatcher uses **first-match by priority**. When two intents match at the same priority tier:

- Select the intent with the higher confidence score.
- On a tie, prefer the more specific intent (e.g., CODE_TASK over generic TASK).
- If still tied, fall through to the next priority tier.

### Low-Confidence Fallback

The classifier assigns a confidence score in `[0.0, 1.0]`. The thresholds are:

- `confidence ≥ 0.70` — accept the classified intent.
- `0.40 ≤ confidence < 0.70` — apply the [When Ambiguous](#when-ambiguous) policy.
- `confidence < 0.40` — treat as General Conversation and add a low-confidence signal to the prompt so the LLM is aware the user input was ambiguous.

These thresholds are tunable; values are managed in configuration alongside other rule-based classifier tunables.

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
2. Add the original user input verbatim to the LLM prompt as an `UncertainUserInput` block so the LLM has full context.
3. The reply should briefly acknowledge that Freya is unsure what the user wants — but only if the threshold is far enough below `0.40` to warrant surfacing.

### Mid-Band Input (`0.40 ≤ confidence < 0.70`)

The runtime asks **one** clarifying question. The clarifying question is a paraphrase, not multiple-choice. Example: for input `"fix this"` with mid-band confidence, the runtime asks: `"Did you mean to fix a specific file or run the project's repair loop?"`

Multi-choice menus are forbidden — they feel mechanical.

### Best-Guess Policy

When clarification is impossible (e.g., mid-band on a one-shot tool call), the runtime picks the highest-confidence intent and proceeds. Prompts that went through a best-guess fallback are logged with `low_confidence=true` for later review in `monitoring/`.

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

| # | Input        | Expected behavior                                       |
|---|--------------|---------------------------------------------------------|
| 1 | `stop`       | Interrupt in-flight planner. Acknowledge briefly.       |
| 2 | `cancel`     | Cancel any pending action. No-op when nothing pending.  |
| 3 | `undo`       | Revert last mutation in current session.                |
| 4 | `undo` (no mutations) | Conversational one-liner, not an error.       |
| 5 | `status`     | Return current plan / step / last completed action.     |
| 6 | `Hi, stop`   | Conversational control wins; ignore greeting.           |

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

These items track the work open in this pillar. Items are checked off only when their corresponding doc section is implemented and the acceptance tests pass.

Spec hardening completed in this revision:

- [x] Acceptance Tests / Behavioral Checks section (this document)
- [x] Routing Semantics section (this document)
- [x] When Ambiguous section (this document)
- [x] Conversational Control capability section (this document)

Improvements beyond Missing Capabilities:

- [ ] Centralize Conversational Control into one dispatcher
- [ ] Better ambiguity detection — coverage below `0.40`
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
