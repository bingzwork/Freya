# Freya Pasted27 Multimodal Intent-Routing Audit

## Verdict scope

Pasted27 addresses a general architectural defect, not a one-person special case. The defect was that an image attachment could hijack `/api/chat` before Freya resolved the user’s requested operation. The repair makes the operation explicit in the semantic model and lets the user’s instruction select the capability.

## Root cause

Before Pasted27, `/api/chat` called `attachment_context()` for every request. For image attachments, that helper unconditionally called the vision path. If visual context was produced, the handler returned the vision text directly; otherwise, a second fallback called vision analysis for any remaining image attachment. This produced a modality-first decision:

```text
image attached -> vision description
```

That behavior was incorrect for requests such as “This is Marianne Nalam. show me more photos of her,” “Find where this came from,” “Compare this with an RTX 5060,” and “Find the cheapest one in Shopee.” The attachment supplied input context, but it did not define the requested operation.

## Correct routing contract

Freya now follows this order:

```text
parse modalities
  -> resolve requested operation
  -> resolve entities and provenance
  -> assign attachment role
  -> select capability
  -> execute through the canonical router
```

The `RequestSemanticModel` now carries `input_modalities`, `requested_operation`, `attachment_role`, `entity_source`, `resolved_entities`, and typed capability requirements. `RequestSemanticAnalyzer.analyze()` receives `attachment_paths` and an optional recent image entity so the semantic decision is made before attachment execution.

## Attachment-role model

| Role | Meaning | Example | Vision default |
| --- | --- | --- | --- |
| `PRIMARY_SUBJECT` | The image itself is the subject of a visual question or description. | “Describe this photo.” | Yes when the operation needs it |
| `REFERENCE_CONTEXT` | The image provides context for a text-led operation. | “This is the printer. Find the cheapest one in Shopee.” | No |
| `SEARCH_SEED` | The image is the seed for reverse or similar-image retrieval. | “Find where this came from.” | Only as a supporting step when needed |
| `EDIT_TARGET` | The image is the target of an edit operation. | “Remove the background.” | No generic description |
| `DOCUMENT_SOURCE` | A non-image document supplies extractable context. | “Find newer research about this paper.” | No image vision |
| `UNKNOWN` | No reliable role was established. | An unqualified attachment | No generic capability hijack |

`REFERENCE_CONTEXT` is intentionally not a capability. It tells the router that the attachment may be passed as supporting context while the primary request continues through comparison, shopping, news, research, or another appropriate capability.

## Entity-source and privacy model

Freya distinguishes two permitted entity sources:

| Source | Example | Allowed interpretation |
| --- | --- | --- |
| `USER_PROVIDED` | “This is Marianne Nalam.” | A user-supplied search name or product/entity label. It may seed public search. |
| `CONVERSATION_CONTEXT` | “Show me another one” after a named image search. | A typed continuation of a recent entity. |

The implementation does **not** introduce facial recognition, biometric matching, unknown-person identification, or a claim that vision identified a person. “This is X” is user-provided context, not visual identity evidence. Privacy responses and the existing `SafetyGate` remain in force.

## Capability decision examples

| User request with an image | Semantic operation | Attachment role | Primary route | Generic vision description? |
| --- | --- | --- | --- | --- |
| “This is Marianne Nalam. show me more photos of her” | `find_more_photos` | `REFERENCE_CONTEXT` | Text-based image search using the user-provided entity | No |
| “Describe this image” | `describe` | `PRIMARY_SUBJECT` | Vision analysis | Yes |
| “What is she wearing?” | `answer_about` | `PRIMARY_SUBJECT` | Vision question answering | Yes |
| “Read the text in this image” | `extract_text` | `PRIMARY_SUBJECT` | Vision/OCR | Yes, as required by OCR |
| “Find where this came from” | `find_source` | `SEARCH_SEED` | Reverse-image search | No direct description; supporting vision may be used |
| “Find similar images” | `find_similar` | `SEARCH_SEED` | Similar-image search | No direct description; supporting vision may be used |
| “Remove the background” | `edit` | `EDIT_TARGET` | Image-edit capability | No |
| “This is the printer. Find the cheapest one in Shopee” | `find` | `REFERENCE_CONTEXT` | Shopping price search | No |
| “This is RTX 5050. Compare with RTX 5060” | `compare` | `REFERENCE_CONTEXT` | Comparison intelligence | No |

## UI routing change

`/api/chat` now passes attachment paths to the semantic analyzer. `attachment_context()` still handles documents and media metadata, but image vision is allowed only when `semantic_model.requires_vision` is true. The handler prioritizes reverse-image search, text-led image search, image edit, and explicit vision operations. Comparison, shopping, and research requests retain the image as context and continue into their established capability paths.

The response includes a `multimodal_semantic` object for UI and acceptance diagnostics without changing the established answer, image-results, vision-observations, and research-queries response fields.

## Regression and acceptance evidence

The permanent test file `tests/test_pasted27_multimodal_routing.py` covers the full intent matrix, entity provenance, privacy non-identification, recent-entity continuity, unrelated-topic isolation, and audio/video/document modality handling. Focused semantic tests pass after the operation-first changes. Final acceptance additionally requires a real image attachment in the running UI, confirmation that the named image-search request returns image cards, confirmation that “Describe this image” still invokes vision, and a browser console with no critical errors.

## Non-goals and limits

This change does not claim that every public image provider is available or that every provider returns results for every person, product, or region. Provider availability remains a research-stack limitation and is surfaced as a bounded capability result rather than silently replacing the requested operation with a description. This change also does not redesign the browser, learning, shopping, comparison, or safety architectures completed in Pasted22–Pasted26.

## References

[1]: https://docs.openwebui.com/features/ "Open WebUI Features"
[2]: https://www.librechat.ai/docs/features/agents "LibreChat Agents"
[3]: https://developers.llamaindex.ai/python/framework/use_cases/multimodal/ "LlamaIndex Multi-modal Use Cases"
