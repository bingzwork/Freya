from app.research.intelligence import RequestSemanticAnalyzer, ResearchIntent


def semantic(text, *, image=True, recent=""):
    return RequestSemanticAnalyzer.analyze(text, context={"attachment_paths": ["/workspace/data/ui_uploads/photo.png"] if image else [], "recent_image_entity": recent})


def test_named_image_search_uses_user_entity_and_reference_context_without_vision():
    model = semantic("This is Marianne Nalam. show me more photos of her")
    assert model.intent == ResearchIntent.IMAGE_SEARCH.value
    assert model.operation == "find_more_photos"
    assert model.requested_operation == "find_more_photos"
    assert model.entities == ["Marianne Nalam"]
    assert model.entity_source == "USER_PROVIDED"
    assert model.attachment_role == "REFERENCE_CONTEXT"
    assert model.requires_image_search is True
    assert model.requires_vision is False
    assert model.requires_reverse_image_search is False


def test_image_attachment_does_not_override_explicit_operation_matrix():
    cases = {
        "Describe this photo.": ("IMAGE_DESCRIPTION", "describe", True),
        "What is she wearing?": ("VISION_QA", "answer_about", True),
        "Read the text in this image.": ("OCR", "extract_text", True),
        "Find where this exact image came from.": ("REVERSE_IMAGE_SEARCH", "find_source", True),
        "Find similar images.": ("SIMILAR_IMAGE_SEARCH", "find_similar", True),
        "Remove the background.": ("IMAGE_EDIT", "edit", False),
        "This is an RTX 5050. Compare it with RTX 5060.": (ResearchIntent.TECHNICAL_COMPARISON.value, "compare", False),
    }
    for text, expected in cases.items():
        model = semantic(text)
        assert (model.intent, model.operation, model.requires_vision) == expected, (text, model.to_dict())


def test_multimodal_shopping_uses_reference_context_not_image_description():
    model = semantic("This is the printer I meant. Find the cheapest one in Shopee.")
    assert model.intent == ResearchIntent.SHOPPING_PRICE_SEARCH.value
    assert model.requires_shopping is True
    assert model.attachment_role == "REFERENCE_CONTEXT"
    assert model.requires_vision is False
    assert model.requires_web_search is True


def test_product_name_from_attachment_context_enters_comparison_semantics():
    model = semantic("This is an RTX 5050. Compare it with RTX 3050.")
    assert model.intent == ResearchIntent.TECHNICAL_COMPARISON.value
    assert model.operation == "compare"
    assert model.entities
    assert any("RTX 5050".lower() in entity.lower() for entity in model.entities)
    assert model.requires_vision is False
    assert model.requires_web_search is True


def test_conversation_image_entity_is_reused_only_for_explicit_followup():
    model = semantic("show me another one", recent="Marianne Nalam")
    assert model.intent == ResearchIntent.IMAGE_SEARCH.value
    assert model.operation == "find_more_photos"
    assert model.entity_source == "CONVERSATION_CONTEXT"
    assert model.entities == ["Marianne Nalam"]
    assert model.attachment_role == "REFERENCE_CONTEXT"


def test_unrelated_new_topic_does_not_inherit_recent_image_entity():
    model = semantic("what is the latest NVIDIA news?", recent="Marianne Nalam")
    assert model.intent == ResearchIntent.NEWS_RESEARCH.value
    assert model.entity_source == ""
    assert "Marianne Nalam" not in model.entities
    assert model.requires_vision is False


def test_user_supplied_name_is_not_visual_identity_or_face_recognition():
    named = semantic("This is Jane Example. Find public photos of Jane Example.")
    unknown = semantic("Who is this person?")
    assert named.entity_source == "USER_PROVIDED"
    assert named.requires_image_search is True
    assert "VISUALLY_IDENTIFIED" not in str(named.to_dict())
    assert unknown.requires_vision is False or unknown.intent in {"VISION_QA", "FACTUAL_LOOKUP"}
    assert "identified" not in str(unknown.to_dict()).lower()


def test_image_search_without_attachment_still_routes_to_image_search():
    model = semantic("Show me more photos of Mount Fuji", image=False)
    assert model.intent == ResearchIntent.IMAGE_SEARCH.value
    assert model.operation == "find_more_photos"
    assert model.requires_image_search is False or model.intent == ResearchIntent.IMAGE_SEARCH.value


def test_audio_video_document_modalities_do_not_force_image_vision():
    audio = RequestSemanticAnalyzer.analyze("Find more songs by this artist", context={"attachment_paths": ["/workspace/audio.mp3"]})
    video = RequestSemanticAnalyzer.analyze("Find the original source of this clip", context={"attachment_paths": ["/workspace/clip.mp4"]})
    document = RequestSemanticAnalyzer.analyze("Find newer research about this topic", context={"attachment_paths": ["/workspace/paper.pdf"]})
    assert audio.input_modalities == ["audio"] and audio.requires_vision is False
    assert video.input_modalities == ["video"] and video.requires_vision is False
    assert document.input_modalities == ["document"] and document.requires_vision is False
