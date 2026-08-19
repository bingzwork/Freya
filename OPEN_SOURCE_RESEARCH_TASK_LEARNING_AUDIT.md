# Pasted24 Research-Task-Learning Audit

## Scope

Freya now has a general research-task-learning orchestration boundary for complex external subjects, including repositories, frameworks, tools, papers, systems, APIs, and architectures. The behavior is not tied to Browser Use or to a new public capability registration.

## Routing

Knowledge-first routing remains the entry gate. Ordinary knowledge questions remain local-answer candidates, bounded research requests remain ordinary research, explicit substantial study requests become `ARCHITECTURE_STUDY_TASK` or `DEEP_RESEARCH_TASK`, explicit study-plus-learning requests become `RESEARCH_AND_LEARNING_TASK`, and implementation requests remain `IMPLEMENTATION_TASK`.

An explicit study request is not short-circuited merely because local memory contains related knowledge. Existing knowledge is retained as context, while current, repository, GitHub, documentation, or inspection language marks fresh external evidence as required.

## Task orchestration

The UI submits substantial study requests to the existing `BackgroundJobService`. The job carries safe task metadata, appears in the existing Agent Console task snapshot, emits bounded activity events such as `SEARCHING`, `THINKING`, `LEARNING`, and `SUCCESS`, and has a bounded wall-clock wait. The task invokes the registered `ResearchCapability` with `DEEP_RESEARCH` limits rather than adding a crawler or parallel scheduler.

## Structured findings and verification

Raw research facts are converted into structured findings containing a conclusion, usefulness class, verification status, confidence, relationship-to-Freya classification, and source provenance. A finding is learnable only when it has source provenance, sufficient confidence, and no unresolved research conflict. Partial or failed research is reported honestly and cannot silently become learned knowledge.

## Learning and memory

Learning is submitted only when the user explicitly asks to learn, remember, retain, or extract reusable lessons. Verified findings are distilled through the existing `LearningPipeline`; the pipeline remains responsible for validation, distillation, admission, and MemoryCoordinator storage. The orchestrator caps the durable candidate set so raw multi-source fact volume is not copied into long-term memory. Rejected or unavailable candidates are reported as rejected rather than claimed as stored.

## Implementation separation

Learning does not authorize code changes, dependency installation, configuration changes, or external actions. Requests such as “use what you learned to improve Freya” are classified as a separate implementation task and continue through existing implementation routing and safety gates.

## Operational limitations

The current implementation uses the existing public research adapters and their bounded deep-research limits. Repository-specific file traversal and richer architecture comparison can be added through the existing research/browser/file capabilities; this orchestration layer does not clone repositories automatically. Learning admission remains subject to the existing pipeline policy and may reject otherwise verified findings when they are not novel, actionable, or suitable for durable storage.
