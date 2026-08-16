from unittest.mock import MagicMock

from app.intent import IntentType
from app.intent.classifier import IntentClassifier
from app.routing.unified_router import ControlCommandParser, UnifiedRouter


def make_router():
    router = UnifiedRouter.__new__(UnifiedRouter)
    router._control_parser = ControlCommandParser()
    router._intent_classifier = IntentClassifier()
    router._knowledge_first_resolver = MagicMock()
    return router


def test_mutating_request_uses_execution_route_before_knowledge_fallback():
    router = make_router()
    result = router.route("delete temp.txt")
    assert result.intent is IntentType.FILE_OPERATION
    assert result.is_engineering is True
    assert result.is_direct_answer is False
    router._knowledge_first_resolver.resolve.assert_not_called()


def test_read_only_file_request_keeps_the_same_planning_contract():
    router = make_router()
    result = router.route("read temp.txt")
    assert result.intent is IntentType.FILE_OPERATION
    assert result.is_engineering is True
    assert result.is_direct_answer is False
    router._knowledge_first_resolver.resolve.assert_not_called()
