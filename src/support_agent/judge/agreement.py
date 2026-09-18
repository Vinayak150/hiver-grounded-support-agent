"""Agreement utilities for LLM repeatability and future human comparison."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence


def _validate(left: Sequence[object], right: Sequence[object]) -> None:
    if not left or len(left) != len(right):
        raise ValueError("Agreement inputs must be non-empty and aligned.")


def exact_agreement(left: Sequence[object], right: Sequence[object]) -> float:
    _validate(left, right)
    return sum(a == b for a, b in zip(left, right, strict=True)) / len(left)


def within_one_agreement(left: Sequence[int], right: Sequence[int]) -> float:
    _validate(left, right)
    return sum(abs(a - b) <= 1 for a, b in zip(left, right, strict=True)) / len(left)


def weighted_cohen_kappa(
    left: Sequence[int], right: Sequence[int], *, weights: str = "quadratic"
) -> float:
    _validate(left, right)
    if weights not in {"linear", "quadratic"}:
        raise ValueError("weights must be linear or quadratic.")
    labels = sorted(set(left) | set(right))
    if len(labels) == 1:
        return 1.0
    positions = {label: index for index, label in enumerate(labels)}
    maximum = len(labels) - 1

    def weight(a: int, b: int) -> float:
        distance = abs(positions[a] - positions[b]) / maximum
        return distance if weights == "linear" else distance**2

    observed = sum(weight(a, b) for a, b in zip(left, right, strict=True)) / len(left)
    left_counts, right_counts = Counter(left), Counter(right)
    expected = sum(
        weight(a, b) * left_counts[a] * right_counts[b] for a in labels for b in labels
    ) / (len(left) ** 2)
    return 1.0 if expected == 0 else 1.0 - observed / expected


def _ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for position in ordered[start:end]:
            ranks[position] = rank
        start = end
    return ranks


def spearman_correlation(left: Sequence[float], right: Sequence[float]) -> float:
    _validate(left, right)
    a, b = _ranks(left), _ranks(right)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    denominator = math.sqrt(sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b))
    return 0.0 if denominator == 0 else numerator / denominator


def confusion_table(left: Sequence[object], right: Sequence[object]) -> dict[str, object]:
    _validate(left, right)
    labels = sorted(set(left) | set(right), key=str)
    counts = Counter(zip(left, right, strict=True))
    return {
        "labels": labels,
        "matrix": [[counts[(a, b)] for b in labels] for a in labels],
    }


def binary_pass_agreement(left: Sequence[bool], right: Sequence[bool]) -> dict[str, object]:
    return {
        "exact_agreement": exact_agreement(left, right),
        "confusion_table": confusion_table(left, right),
    }


def order_bias_flip_rate(first: Sequence[str], swapped: Sequence[str]) -> float:
    _validate(first, swapped)
    consistent = {("A", "B"), ("B", "A"), ("TIE", "TIE")}
    return sum((a, b) not in consistent for a, b in zip(first, swapped, strict=True)) / len(first)
