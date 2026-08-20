from app.research.intelligence import RequestSemanticAnalyzer, SynthesisEngine


def test_ram_style_news_question_uses_news_output_contract():
    semantic = RequestSemanticAnalyzer.analyze("why are RAM so expensive now?")
    assert semantic.intent == "NEWS_RESEARCH"
    assert semantic.response_type == "news_developments"
    assert semantic.output_goal == "news_developments"


def test_news_synthesis_prefers_excerpts_over_headline_fragments():
    semantic = RequestSemanticAnalyzer.analyze("why are RAM so expensive now?")
    answer = SynthesisEngine.synthesize(
        semantic,
        [
            {
                "claim": "Why are RAM prices so high right now?",
                "evidence": "AI-server demand is absorbing a larger share of memory production while manufacturers shift capacity toward higher-margin data-center products.",
                "source_title": "Why are RAM prices so high right now? - Engadget",
                "source_url": "https://example.com/ram",
            },
            {
                "claim": "How high are DDR5 RAM prices right now?",
                "evidence": "Reduced consumer supply and strong data-center demand are pushing DDR5 contract prices higher than earlier in the year.",
                "source_title": "DDR5 prices report",
                "source_url": "https://example.com/ddr5",
            },
        ],
        [],
        [],
    )["answer"]
    assert "Recent reporting about" in answer
    assert "AI-server demand is absorbing" in answer
    assert "Reduced consumer supply" in answer
    assert "date not exposed" not in answer
    assert "Here are the most relevant recent developments" not in answer
    assert "How high are DDR5 RAM prices right now?" not in answer


def test_news_synthesis_does_not_promote_bare_headlines_to_facts():
    semantic = RequestSemanticAnalyzer.analyze("why are RAM so expensive now?")
    answer = SynthesisEngine.synthesize(
        semantic,
        [
            {
                "claim": "Why are RAM prices reaching new records in 2026?",
                "evidence": "Why are RAM prices reaching new records in 2026?",
                "source_title": "Why are RAM prices reaching new records in 2026?",
                "source_url": "https://example.com/headline",
            }
        ],
        [],
        [],
    )["answer"]
    assert "did not expose enough readable evidence" in answer
    assert "Why are RAM prices reaching new records" not in answer


def test_everyday_technical_wrapper_normalizes_to_subject_query():
    semantic = RequestSemanticAnalyzer.analyze("How does FastAPI library handle middleware? Check the repository.")
    assert semantic.research_query == "FastAPI handle middleware"
    assert "grammar" not in semantic.research_query.lower()


def test_current_developments_are_news_not_generic_current_lookup():
    semantic = RequestSemanticAnalyzer.analyze("What are the latest developments affecting grocery prices?")
    assert semantic.intent == "NEWS_RESEARCH"
    assert semantic.response_type == "news_developments"
    assert semantic.research_query == "the latest developments affecting grocery prices"


def test_internal_chat_payload_markers_are_detected_at_ui_boundary():
    from ui_server import _looks_like_internal_chat_leak
    assert _looks_like_internal_chat_leak("success: True, analysis: {'answerability': {}}")
    assert _looks_like_internal_chat_leak("Lesson [pattern/recommended] Learning from watchdog_observation events")
    assert _looks_like_internal_chat_leak("No provider is configured for this operation")
    assert _looks_like_internal_chat_leak("Found 0 tasks")
    assert not _looks_like_internal_chat_leak("A concise explanation with practical next steps.")


def test_recommendation_and_troubleshooting_routes_are_user_research_intents():
    from ui_server import _is_recommendation_request, _is_troubleshooting_request
    assert _is_recommendation_request("What is the best browser automation approach for Freya and why?")
    assert _is_troubleshooting_request("Why is my home Wi-Fi slow even when the signal looks strong?")
    assert not _is_troubleshooting_request("Why are you idle?")
