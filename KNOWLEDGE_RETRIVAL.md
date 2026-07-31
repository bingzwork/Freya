# Knowledge Retrieval

## Status
🟡 **Partially Implemented** (≈25% complete)

## Overview
Knowledge Retrieval allows Freya to search, rank, and reuse stored knowledge before acquiring new information.

## Core Responsibilities
- Search the Knowledge Base for relevant concepts.
- Rank results by relevance, confidence, and other criteria.
- Return the best matching knowledge.
- Detect insufficient knowledge and trigger acquisition only when needed.

## Workflow
1. **Analyze Request** – Understand the user's intent.
2. **Generate Search Query** – Create topic, keyword, or semantic query.
3. **Search Knowledge Base** – Retrieve matching entries.
4. **Rank Results** – Apply relevance, confidence, usage, and source quality scores.
5. **Check Confidence** – If confidence is low, either acquire new knowledge or inform the user.
6. **Return Knowledge** – Provide the top result or indicate missing knowledge.

## Search Methods
| Method | Description |
|--------|-------------|
| **Topic Search** | Exact topic lookup (e.g., “OAuth”). |
| **Keyword Search** | Match important keywords (e.g., “auth token”). |
| **Semantic Search** | Find concepts with similar meaning, even if wording differs. |
| **Related Topic Search** | Return closely related subjects (e.g., “JWT” → “OAuth”). |

## Ranking Criteria
- **Relevance** – Direct match to query.
- **Confidence** – Certainty of the stored knowledge.
- **Validation Status** – Verified vs unverified entries.
- **Recency** – How recently the knowledge was updated.
- **Usage Frequency** – How often the entry is accessed.
- **Source Quality** – Trusted sources rank higher.

## Confidence Evaluation
- After retrieval, evaluate whether the knowledge is sufficient.
- **High Confidence** (≥ 90%) → Use knowledge directly.
- **Medium Confidence** (70‑89%) → Use with caution; may add context.
- **Low Confidence** (< 70%) → Trigger Knowledge Acquisition or ask the user.

## Retrieval Decision
- **Knowledge Found** → Return best result.
- **Knowledge Missing** → Initiate Knowledge Acquisition workflow.

## Retrieval Metadata (per entry)
- **Topic**
- **Summary**
- **Confidence**
- **Validation Status**
- **Source**
- **Last Updated**
- **Related Topics**
- **Keywords**
- **Usage Count**

## Example
**User:** “Explain Dependency Injection.”  
**Process:**  
1. Generate query → “Dependency Injection”.  
2. Search → “Dependency Injection” (topic) found.  
3. Confidence: 97% → Return stored knowledge.  
4. Answer user.

**User:** “New features in Python 3.15.”  
**Process:**  
1. Search → nothing found.  
2. Trigger Knowledge Acquisition → extract, validate, store new knowledge.  
3. Then answer.

## Success Criteria
- Freya can search the Knowledge Base.
- Retrieve relevant knowledge.
- Rank multiple results.
- Determine if knowledge is sufficient.
- Only acquire new knowledge when necessary.

## Remaining Implementation Tasks

| Priority | Objective | Description | Why it Matters | Dependencies | Success Criteria |
|----------|-----------|-------------|----------------|--------------|------------------|
| ⭐⭐⭐⭐⭐ **Critical** | Build Unified Retrieval Ranking Engine | Implement cross‑source scoring that combines relevance, confidence, usage, and source quality into a single rank. | Enables accurate, single‑source‑of‑truth retrieval. | Current ranking components | Ranking produces a clear top result that matches user intent. |
| ⭐⭐⭐⭐ **High** | Implement Confidence Calibration | Add statistical calibration to confidence scores for better decision making. | Improves accuracy of “use vs acquire” decisions. | Unified ranking engine | Calibrated confidence correlates with actual correctness. |
| ⭐⭐⭐ **Medium** | Add Real‑Time Usage Analytics | Track retrieval usage to continuously refine ranking weights. | Makes ranking adaptive over time. | Analytics pipeline | Ranking weights update automatically based on usage trends. |
| ⭐⭐ **Low** | Create Retrieval UI Dashboard | Simple UI showing recent queries, results, confidence, and acquisition triggers. | Improves observability and manual oversight. | Completion of ranking and analytics | Dashboard displays live retrieval activity. |
| ⭐ **Future** | Enable Multi‑Project Retrieval | Retrieve knowledge from related projects when relevant. | Expands knowledge scope beyond a single project. | Cross‑project indexing | Accurate retrieval from multiple repos. |

---  
*This document serves as the single source of truth for Knowledge Retrieval design and roadmap. It will be updated as implementation progresses.*