# Natural Conversation

## Status
🟡 **Partially Implemented** (≈ 95 % complete)

## Overview
Freya’s conversation pipeline is fully functional for routing, intent classification, and direct answering. Only a few control‑flow enhancements remain.

## Core Principles
- **Plain English** – Use everyday words; hide all internal terms.
- **Conversational tone** – Keep replies short, friendly, and goal‑focused.
- **Hide implementation details** – Never expose routing, confidence scores, or handlers unless asked.
- **User‑goal framing** – Explain what the user is trying to achieve, not how the system works.
- **Brevity** – one‑ or two‑sentence replies; short clarifying questions only.

## Architecture (High‑Level)
```
User Input → Normalization → Intent Classification → Routing → Handler
```
- **Intent Classification** – Maps input to one of ~15 intents with confidence.
- **Routing** – Uses `IntentType.routing_priority`; conversational control has highest priority.
- **Handler** – Executes the appropriate action (direct answer, planner, control command).

## Capability Summary
| Capability | Status | Completion |
|-----------|--------|------------|
| Intent Classification | ✅ Complete | 100 % |
| Capability Routing | ✅ Complete | 100 % |
| Runtime Context | ✅ Complete | 100 % |
| Conversation History | ✅ Complete | 100 % |
| Direct Answer Routing | ✅ Complete | 100 % |
| **Conversational Control** | 🟡 Partial | 90 % |
| Greeting Handling | ✅ Complete | 100 % |
| Knowledge Question Handling | ✅ Complete | 100 % |
| System Status Detection | ✅ Complete | 100 % |
| Engineering Task Detection | ✅ Complete | 100 % |
| Statistical Intent Classification | ✅ Complete | 100 % |
| Entity Extraction & Slot Filling | ✅ Complete | 100 % |
| Multi‑Intent Detection | ✅ Complete | 100 % |
| User Preference Learning | ✅ Complete | 100 % |
| Plain English Response System | ✅ Complete | 100 % |

## Key Implementations
- **Intent Classification** – Keyword + pattern matching, confidence thresholds (ACCEPT = 0.70, LOW = 0.40), follow‑up context boosts.
- **Conversational Control** – Handles `stop`, `cancel`, `undo`, `redo`, `status`; short‑circuits routing; emits plain‑English acks.
- **Plain English Formatter** – Translates 115+ technical terms to everyday language; masks all internal field names as `[internal]`.
- **Entity Extraction** – Regex & keyword extraction for paths, URLs, hashes, etc.; LLM fallback for complex entities.
- **Multi‑Intent Detection** – Splits compound requests (conjunction, semicolon, sentence, keyword) and orders them.

## Remaining Implementation Tasks
| Priority | Objective | Description | Why it Matters | Dependencies | Success Criteria |
|----------|-----------|-------------|----------------|--------------|------------------|
| ⭐⭐⭐⭐⭐ **Critical** | Centralize Conversational Control | Move control handling into a single dedicated handler and hook interruptions to pause/cancel in‑flight planners. | Enables true interruptible flows; prevents runaway executions. | Current `ConversationalControlHandler`; planner signal integration | Planner can be safely stopped/cancelled via control commands. |
| ⭐⭐⭐⭐ **High** | Extend `undo` support | Allow multi‑step undo across sessions and support redo. | Improves user ability to correct mistakes without restarting. | `ConversationHistory` persistence | `undo` works across session boundaries and redo restores reverted steps. |
| ⭐⭐⭐ **Medium** | Better Ambiguity Detection | Apply low‑confidence fallback to engineering intents and add richer ambiguity scoring. | Reduces unintended planner launches when intent is unclear. | Current confidence thresholds | Ambiguous inputs trigger clear clarifying questions or fallback to general conversation. |
| ⭐⭐ **Low** | Long‑Term Conversation Summarization | Summarize chat history for long sessions and inject summary into prompts. | Keeps context concise; avoids prompt overload. | Conversation History storage | Summarized context is correctly used for subsequent replies. |
| ⭐ **Future** | Voice‑style & Accessibility Enhancements | Add SSML formatting, screen‑reader friendly cues, and adjustable verbosity. | Improves accessibility for diverse users. | Plain English system | Voice‑oriented output passes accessibility tests. |

---  
*This document serves as the single source of truth for the Natural Conversation pillar. It will be updated as implementation progresses.*