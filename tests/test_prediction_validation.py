from app.self_observation.predictive_diagnostics import PredictiveDiagnostics
from app.self_observation.predictive_models import PredictionResult, PredictionType


def service():
    return PredictiveDiagnostics()


def prediction(**kwargs):
    values = {
        "prediction_type": PredictionType.FAILURE_PROBABILITY,
        "predicted_state": "healthy",
        "confidence_score": 0.8,
        "evidence": ["health trend"],
        "metadata": {"hypothesis_id": "hyp_1"},
    }
    values.update(kwargs)
    return PredictionResult(**values)


def test_prediction_outcomes_are_evaluated_and_provenance_preserved():
    diagnostics = service()
    correct = prediction()
    incorrect = prediction(predicted_state="unhealthy")
    unresolved = prediction(predicted_state=None, predicted_value=None)
    for item in (correct, incorrect, unresolved):
        diagnostics._record_prediction(item)

    first = diagnostics.record_actual_outcome(correct.prediction_id, actual_state="healthy", observation_id="obs_1", evidence={"source": "health"})
    second = diagnostics.record_actual_outcome(incorrect.prediction_id, actual_state="healthy", observation_id="obs_2")
    third = diagnostics.record_actual_outcome(unresolved.prediction_id, observation_id="obs_3")
    assert first.evaluation == "CORRECT"
    assert second.evaluation == "INCORRECT"
    assert third.evaluation == "UNRESOLVED"
    assert first.observation_id == "obs_1"
    assert first.hypothesis_id == "hyp_1"
    assert diagnostics.get_prediction_accuracy()["counts"] == {"CORRECT": 1, "INCORRECT": 1, "PARTIAL": 0, "UNRESOLVED": 1}
    assert diagnostics.get_prediction_accuracy()["accuracy"] == 0.5

    assert diagnostics.record_actual_outcome(correct.prediction_id, actual_state="healthy") is None
    assert len(diagnostics.get_validation_history()) == 3
    diagnostics.stop()


def test_prediction_with_missing_actual_outcome_is_not_counted_as_correct():
    diagnostics = service()
    item = prediction()
    diagnostics._record_prediction(item)
    record = diagnostics.record_actual_outcome(item.prediction_id)
    assert record.evaluation == "UNRESOLVED"
    assert diagnostics.get_prediction_accuracy()["resolved"] == 0
    diagnostics.stop()
