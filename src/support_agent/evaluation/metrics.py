"""Label-driven metrics that remain dormant until valid human gold exists."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import TypeVar

Label = TypeVar("Label", bound=str)


def _validate_pair(left: Sequence[object], right: Sequence[object]) -> None:
    if len(left) != len(right):
        raise ValueError("Metric inputs must have equal lengths.")
    if not left:
        raise ValueError("Metric inputs must be non-empty.")


def _safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _ratio(numerator: int, denominator: int) -> dict[str, int | float]:
    return {
        "value": _safe_divide(numerator, denominator),
        "numerator": numerator,
        "denominator": denominator,
    }


def confusion_matrix(
    gold: Sequence[Label], predicted: Sequence[Label], labels: Sequence[Label] | None = None
) -> dict[str, object]:
    _validate_pair(gold, predicted)
    ordered = list(labels) if labels is not None else sorted(set(gold) | set(predicted))
    if len(ordered) != len(set(ordered)):
        raise ValueError("Confusion-matrix labels must be unique.")
    unknown = (set(gold) | set(predicted)) - set(ordered)
    if unknown:
        raise ValueError(f"Confusion-matrix labels omit observed values: {sorted(unknown)}")
    index = {label: position for position, label in enumerate(ordered)}
    matrix = [[0 for _ in ordered] for _ in ordered]
    for truth, prediction in zip(gold, predicted, strict=True):
        matrix[index[truth]][index[prediction]] += 1
    return {"labels": ordered, "matrix": matrix}


def intent_classification_metrics(
    gold: Sequence[Label], predicted: Sequence[Label], labels: Sequence[Label] | None = None
) -> dict[str, object]:
    matrix_payload = confusion_matrix(gold, predicted, labels)
    ordered = matrix_payload["labels"]
    matrix = matrix_payload["matrix"]
    per_class = {}
    total = len(gold)
    correct = 0
    weighted_f1_sum = 0.0
    f1_values = []
    for index, label in enumerate(ordered):
        true_positive = matrix[index][index]
        false_positive = sum(matrix[row][index] for row in range(len(ordered))) - true_positive
        false_negative = sum(matrix[index]) - true_positive
        support = sum(matrix[index])
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
        correct += true_positive
        f1_values.append(f1)
        weighted_f1_sum += f1 * support
    return {
        "accuracy": _safe_divide(correct, total),
        "macro_f1": sum(f1_values) / len(f1_values),
        "weighted_f1": _safe_divide(weighted_f1_sum, total),
        "per_class": per_class,
        "confusion_matrix": matrix_payload,
        "sample_count": total,
    }


def action_metrics(
    gold: Sequence[str], predicted: Sequence[str], escalation_label: str = "ESCALATE"
) -> dict[str, object]:
    _validate_pair(gold, predicted)
    allowed = {"AUTO_HANDLE", "ESCALATE"}
    unknown = (set(gold) | set(predicted)) - allowed
    if unknown:
        raise ValueError(f"Unknown action labels: {sorted(unknown)}")
    true_positive = sum(
        truth == escalation_label and guess == escalation_label
        for truth, guess in zip(gold, predicted, strict=True)
    )
    false_positive = sum(
        truth != escalation_label and guess == escalation_label
        for truth, guess in zip(gold, predicted, strict=True)
    )
    false_negative = sum(
        truth == escalation_label and guess != escalation_label
        for truth, guess in zip(gold, predicted, strict=True)
    )
    true_negative = len(gold) - true_positive - false_positive - false_negative
    precision = _safe_divide(true_positive, true_positive + false_positive)
    recall = _safe_divide(true_positive, true_positive + false_negative)
    return {
        "escalation_precision": _ratio(true_positive, true_positive + false_positive),
        "escalation_recall": _ratio(true_positive, true_positive + false_negative),
        "escalation_f1": _safe_divide(2 * precision * recall, precision + recall),
        "false_escalation_rate": _ratio(false_positive, false_positive + true_negative),
        "missed_escalation_rate": _ratio(false_negative, true_positive + false_negative),
        "unsafe_auto_handle_rate": _ratio(false_negative, false_negative + true_negative),
        "automation_coverage": _ratio(false_negative + true_negative, len(gold)),
        "confusion_counts": {
            "true_escalation": true_positive,
            "false_escalation": false_positive,
            "missed_escalation": false_negative,
            "safe_auto_handle": true_negative,
        },
    }


def correct_and_safe_automation_coverage(
    gold_intents: Sequence[str],
    predicted_intents: Sequence[str],
    gold_actions: Sequence[str],
    predicted_actions: Sequence[str],
    response_quality_approved: Sequence[bool] | None,
) -> dict[str, int | float]:
    """Future metric requiring human response-quality evidence; never infer it."""

    if response_quality_approved is None:
        raise ValueError("Human response-quality evidence is required for this metric.")
    lengths = {
        len(gold_intents),
        len(predicted_intents),
        len(gold_actions),
        len(predicted_actions),
        len(response_quality_approved),
    }
    if len(lengths) != 1 or not gold_intents:
        raise ValueError("Correct-and-safe coverage inputs must be non-empty and aligned.")
    numerator = sum(
        predicted_action == "AUTO_HANDLE"
        and gold_action == "AUTO_HANDLE"
        and predicted_intent == gold_intent
        and quality
        for gold_intent, predicted_intent, gold_action, predicted_action, quality in zip(
            gold_intents,
            predicted_intents,
            gold_actions,
            predicted_actions,
            response_quality_approved,
            strict=True,
        )
    )
    return _ratio(numerator, len(gold_intents))


def recall_at_k(
    relevant_ids: Sequence[set[str]], retrieved_ids: Sequence[Sequence[str]], k: int
) -> dict[str, int | float]:
    _validate_pair(relevant_ids, retrieved_ids)
    if k <= 0:
        raise ValueError("k must be positive.")
    eligible = 0
    recall_sum = 0.0
    for relevant, retrieved in zip(relevant_ids, retrieved_ids, strict=True):
        if not relevant:
            continue
        eligible += 1
        recall_sum += len(relevant & set(retrieved[:k])) / len(relevant)
    return {
        "value": _safe_divide(recall_sum, eligible),
        "numerator": recall_sum,
        "denominator": eligible,
    }


def mean_reciprocal_rank(
    relevant_ids: Sequence[set[str]], retrieved_ids: Sequence[Sequence[str]]
) -> dict[str, int | float]:
    _validate_pair(relevant_ids, retrieved_ids)
    eligible = 0
    reciprocal_sum = 0.0
    for relevant, retrieved in zip(relevant_ids, retrieved_ids, strict=True):
        if not relevant:
            continue
        eligible += 1
        reciprocal_sum += next(
            (1.0 / rank for rank, item in enumerate(retrieved, start=1) if item in relevant),
            0.0,
        )
    return {
        "value": _safe_divide(reciprocal_sum, eligible),
        "numerator": reciprocal_sum,
        "denominator": eligible,
    }


def expected_calibration_error(
    gold: Sequence[str], predicted: Sequence[str], confidences: Sequence[float], bins: int = 10
) -> float:
    _validate_pair(gold, predicted)
    if len(confidences) != len(gold):
        raise ValueError("Confidence inputs must align with labels.")
    if bins <= 0:
        raise ValueError("bins must be positive.")
    if any(not 0.0 <= confidence <= 1.0 for confidence in confidences):
        raise ValueError("Confidences must be between zero and one.")
    bucket_counts: Counter[int] = Counter()
    bucket_confidence: Counter[int] = Counter()
    bucket_correct: Counter[int] = Counter()
    for truth, guess, confidence in zip(gold, predicted, confidences, strict=True):
        bucket = min(int(confidence * bins), bins - 1)
        bucket_counts[bucket] += 1
        bucket_confidence[bucket] += confidence
        bucket_correct[bucket] += truth == guess
    total = len(gold)
    return sum(
        bucket_counts[bucket]
        / total
        * abs(
            bucket_correct[bucket] / bucket_counts[bucket]
            - bucket_confidence[bucket] / bucket_counts[bucket]
        )
        for bucket in bucket_counts
    )


def brier_score(gold_binary: Sequence[int], positive_probabilities: Sequence[float]) -> float:
    _validate_pair(gold_binary, positive_probabilities)
    if set(gold_binary) - {0, 1}:
        raise ValueError("Brier gold labels must be binary zero/one values.")
    if any(not 0.0 <= probability <= 1.0 for probability in positive_probabilities):
        raise ValueError("Probabilities must be between zero and one.")
    return sum(
        (probability - truth) ** 2
        for truth, probability in zip(gold_binary, positive_probabilities, strict=True)
    ) / len(gold_binary)
