from __future__ import annotations

from statistics import mean

from support_agent.evaluation.bootstrap import bootstrap_ratio_ci, percentile_bootstrap_ci


def test_percentile_bootstrap_is_deterministic_and_perfect_fixture_is_exact() -> None:
    first = percentile_bootstrap_ci([0.0, 1.0, 1.0, 0.0], mean, samples=200, seed=7)
    second = percentile_bootstrap_ci([0.0, 1.0, 1.0, 0.0], mean, samples=200, seed=7)
    assert first == second
    assert first["estimate"] == 0.5
    perfect = percentile_bootstrap_ci([1.0, 1.0, 1.0], mean, samples=50, seed=3)
    assert perfect["estimate"] == perfect["lower"] == perfect["upper"] == 1.0


def test_ratio_bootstrap_retains_counts_and_handles_zero_denominator() -> None:
    result = bootstrap_ratio_ci([1, 0, 1], [1, 1, 1], samples=100, seed=11)
    assert result["numerator"] == 2
    assert result["denominator"] == 3
    assert result["estimate"] == 2 / 3
    empty_denominator = bootstrap_ratio_ci([0, 0], [0, 0], samples=20, seed=11)
    assert empty_denominator["estimate"] == 0.0
    assert empty_denominator["lower"] == 0.0
    assert empty_denominator["upper"] == 0.0
