from __future__ import annotations

import pytest

from support_agent.evaluation.metrics import (
    action_metrics,
    brier_score,
    confusion_matrix,
    correct_and_safe_automation_coverage,
    expected_calibration_error,
    intent_classification_metrics,
    mean_reciprocal_rank,
    recall_at_k,
)


def test_perfect_and_all_wrong_intent_predictions() -> None:
    perfect = intent_classification_metrics(["a", "b", "a"], ["a", "b", "a"])
    assert perfect["accuracy"] == 1.0
    assert perfect["macro_f1"] == 1.0
    assert perfect["weighted_f1"] == 1.0
    wrong = intent_classification_metrics(["a", "b"], ["b", "a"], labels=["a", "b"])
    assert wrong["accuracy"] == 0.0
    assert wrong["macro_f1"] == 0.0


def test_missing_class_prediction_has_hand_calculated_scores() -> None:
    result = intent_classification_metrics(
        ["a", "a", "b", "b"], ["a", "a", "a", "a"], labels=["a", "b"]
    )
    assert result["accuracy"] == 0.5
    assert result["macro_f1"] == pytest.approx(1 / 3)
    assert result["weighted_f1"] == pytest.approx(1 / 3)
    assert result["per_class"]["a"] == {
        "precision": 0.5,
        "recall": 1.0,
        "f1": pytest.approx(2 / 3),
        "support": 2,
    }
    assert result["per_class"]["b"]["f1"] == 0.0


def test_confusion_matrix_respects_explicit_ordering() -> None:
    result = confusion_matrix(["a", "b", "a"], ["b", "b", "a"], labels=["b", "a"])
    assert result == {"labels": ["b", "a"], "matrix": [[1, 0], [1, 1]]}


def test_action_metrics_and_zero_denominators() -> None:
    result = action_metrics(
        ["ESCALATE", "ESCALATE", "AUTO_HANDLE", "AUTO_HANDLE"],
        ["ESCALATE", "AUTO_HANDLE", "ESCALATE", "AUTO_HANDLE"],
    )
    assert result["escalation_precision"]["value"] == 0.5
    assert result["escalation_recall"]["value"] == 0.5
    assert result["escalation_f1"] == 0.5
    assert result["false_escalation_rate"]["value"] == 0.5
    assert result["missed_escalation_rate"]["value"] == 0.5
    assert result["unsafe_auto_handle_rate"]["value"] == 0.5
    assert result["automation_coverage"]["value"] == 0.5

    no_predicted_escalation = action_metrics(
        ["ESCALATE", "AUTO_HANDLE"], ["AUTO_HANDLE", "AUTO_HANDLE"]
    )
    assert no_predicted_escalation["escalation_precision"] == {
        "value": 0.0,
        "numerator": 0,
        "denominator": 0,
    }
    no_gold_escalation = action_metrics(
        ["AUTO_HANDLE", "AUTO_HANDLE"], ["ESCALATE", "AUTO_HANDLE"]
    )
    assert no_gold_escalation["escalation_recall"]["value"] == 0.0


def test_retrieval_probability_and_future_safe_coverage_metrics() -> None:
    recall = recall_at_k([{"a"}, {"b", "c"}], [["a"], ["c"]], 1)
    assert recall["value"] == 0.75
    mrr = mean_reciprocal_rank([{"a"}, {"b"}], [["a"], ["x", "b"]])
    assert mrr["value"] == 0.75
    assert expected_calibration_error(["a", "b"], ["a", "a"], [0.8, 0.6], bins=2) == pytest.approx(
        0.2
    )
    assert brier_score([1, 0], [0.8, 0.3]) == pytest.approx(0.065)
    with pytest.raises(ValueError, match="response-quality"):
        correct_and_safe_automation_coverage(
            ["a"], ["a"], ["AUTO_HANDLE"], ["AUTO_HANDLE"], None
        )


def test_metric_inputs_reject_invalid_lengths() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        intent_classification_metrics(["a"], ["a", "b"])
    with pytest.raises(ValueError, match="equal lengths"):
        brier_score([1], [0.5, 0.2])
