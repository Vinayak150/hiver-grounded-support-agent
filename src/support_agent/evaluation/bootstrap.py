"""Deterministic percentile bootstrap confidence intervals."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence

import numpy as np


def _validate(samples: int, confidence_level: float, count: int) -> None:
    if count <= 0:
        raise ValueError("Bootstrap inputs must be non-empty.")
    if samples <= 0:
        raise ValueError("Bootstrap sample count must be positive.")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("Confidence level must be strictly between zero and one.")


def percentile_bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float],
    *,
    samples: int = 2000,
    seed: int = 20260918,
    confidence_level: float = 0.95,
) -> dict[str, int | float]:
    _validate(samples, confidence_level, len(values))
    generator = random.Random(seed)
    estimates = []
    for _ in range(samples):
        resampled = [values[generator.randrange(len(values))] for _ in values]
        estimates.append(float(statistic(resampled)))
    alpha = (1.0 - confidence_level) / 2.0
    return {
        "estimate": float(statistic(values)),
        "lower": float(np.percentile(estimates, alpha * 100)),
        "upper": float(np.percentile(estimates, (1.0 - alpha) * 100)),
        "confidence_level": confidence_level,
        "bootstrap_samples": samples,
        "seed": seed,
        "sample_count": len(values),
    }


def bootstrap_ratio_ci(
    numerators: Sequence[float],
    denominators: Sequence[float],
    *,
    samples: int = 2000,
    seed: int = 20260918,
    confidence_level: float = 0.95,
) -> dict[str, int | float]:
    if len(numerators) != len(denominators):
        raise ValueError("Bootstrap numerator and denominator inputs must align.")
    _validate(samples, confidence_level, len(numerators))

    def ratio(indices: Sequence[int]) -> float:
        numerator = sum(numerators[index] for index in indices)
        denominator = sum(denominators[index] for index in indices)
        return 0.0 if denominator == 0 else numerator / denominator

    generator = random.Random(seed)
    estimates = []
    for _ in range(samples):
        indices = [generator.randrange(len(numerators)) for _ in numerators]
        estimates.append(ratio(indices))
    alpha = (1.0 - confidence_level) / 2.0
    all_indices = list(range(len(numerators)))
    return {
        "estimate": ratio(all_indices),
        "lower": float(np.percentile(estimates, alpha * 100)),
        "upper": float(np.percentile(estimates, (1.0 - alpha) * 100)),
        "confidence_level": confidence_level,
        "bootstrap_samples": samples,
        "seed": seed,
        "sample_count": len(numerators),
        "numerator": sum(numerators),
        "denominator": sum(denominators),
    }
