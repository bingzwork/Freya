# Open-Source Multimodal Routing Audit

**Scope.** Pasted27 repairs a modality-first routing defect in Freya: an attached image was treated as an implicit request for visual description even when the user explicitly requested image search, reverse search, comparison, shopping, or another operation. This audit records the public open-source patterns reviewed and the bounded design choices applied to Freya.

## Sources reviewed

| System | Official source | Relevant pattern | Freya decision |
| --- | --- | --- | --- |
| Open WebUI | [Features documentation](https://docs.openwebui.com/features/) | File/image uploads, vision models, image generation, web search, tools, and context injection are presented as distinct capabilities. | **Adopted:** an attachment is available context; capability selection remains request-driven. **Rejected:** a universal “attachment means describe” shortcut. |
| LibreChat | [Agents documentation](https://www.librechat.ai/docs/features/agents) | Agent capabilities distinguish File Search, File Context, OCR, web search, and image generation/editing. File Context and File Search use uploads as context or retrieval input. | **Adopted:** typed capability selection and separate context/retrieval/editing paths. **Rejected:** treating all image/document uploads as one generic vision tool. |
| LlamaIndex | [Multimodal use cases](https://developers.llamaindex.ai/python/framework/use_cases/multimodal/) | Multimodal RAG accepts text or image input, stores text or images, and supports image-to-image retrieval, structured image retrieval, and retrieval-augmented captioning. | **Adopted:** modality, entity, attachment role, and operation are separate semantic fields. **Rejected:** importing a large multimodal index or model dependency into Freya’s local MVP. |

These sources establish architectural patterns, not a claim that Freya is a copy of any system. The implementation remains local, synchronous where existing Freya contracts require it, and constrained by the canonical router and safety gate.

## Common pattern extracted

The systems reviewed converge on a useful separation:

> **Input modality describes what is available; the requested operation describes what the assistant should do.**

An image may be a subject to describe, a search seed for reverse or similar-image retrieval, reference context for a comparison or shopping request, or an edit target. Vision inference is therefore a capability selected by the operation, not a default consequence of attachment presence.

## Freya implementation mapping

Freya now performs the following ordered resolution:

1. Detect input modalities from approved attachment paths.
2. Resolve the explicit requested operation from the user’s text.
3. Resolve explicit user entities and, only for typed follow-ups, inherit a recent image entity.
4. Assign an attachment role: `PRIMARY_SUBJECT`, `REFERENCE_CONTEXT`, `SEARCH_SEED`, `EDIT_TARGET`, `DOCUMENT_SOURCE`, or `UNKNOWN`.
5. Select the capability using typed `requires_*` flags.

The primary routing flags are `requires_vision`, `requires_web_search`, `requires_image_search`, `requires_reverse_image_search`, `requires_image_edit`, and `requires_shopping`. The `/api/chat` handler passes attachment paths into `RequestSemanticAnalyzer`, suppresses generic visual context unless `requires_vision` is true, and routes explicit image-search or non-vision operations before any fallback attachment handling.

## Deliberate non-adoptions

Freya does not implement facial recognition, unknown-person identification, biometric inference, or an automatic claim that a visual subject is a named person. A user-provided statement such as “This is Marianne Nalam” is preserved as **user-provided search context** and may be used for public image search. It is not converted into a visual identification result.

Freya also does not add a new external multimodal index, a second router, or a parallel tool registry. Reverse/similar image search continues through the existing research capability and provider chain; vision continues through the existing vision capability; comparison, shopping, browser, learning, and safety systems remain canonical.

## Verification basis

The permanent Pasted27 tests cover named image search, description, visual question answering, OCR, reverse search, similar-image search, editing, shopping, comparison, privacy separation, follow-up continuity, unrelated-topic isolation, and audio/video/document modality detection. The UI acceptance must additionally confirm that a named image-search request renders image results rather than a generic image description.

## References

[1]: https://docs.openwebui.com/features/ "Open WebUI Features"
[2]: https://www.librechat.ai/docs/features/agents "LibreChat Agents"
[3]: https://developers.llamaindex.ai/python/framework/use_cases/multimodal/ "LlamaIndex Multi-modal Use Cases"
