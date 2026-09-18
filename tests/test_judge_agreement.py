from __future__ import annotations

import pytest

from support_agent.judge.agreement import (
    binary_pass_agreement,
    confusion_table,
    exact_agreement,
    order_bias_flip_rate,
    spearman_correlation,
    weighted_cohen_kappa,
    within_one_agreement,
)


def test_hand_calculated_exact_and_within_one_agreement():
    left = [1, 2, 3, 5]
    right = [1, 3, 1, 5]
    assert exact_agreement(left, right) == 0.5
    assert within_one_agreement(left, right) == 0.75


def test_weighted_kappa_fixtures():
    assert weighted_cohen_kappa([1, 2, 3], [1, 2, 3]) == 1.0
    assert weighted_cohen_kappa([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_and_binary_agreement_fixtures():
    assert spearman_correlation([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman_correlation([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    binary = binary_pass_agreement([True, True, False], [True, False, False])
    assert binary["exact_agreement"] == pytest.approx(2 / 3)
    assert confusion_table(["A", "B"], ["B", "B"])["matrix"] == [[0, 1], [0, 1]]


def test_order_bias_flip_rate_accounts_for_swapped_labels():
    assert order_bias_flip_rate(["A", "B", "TIE"], ["B", "A", "TIE"]) == 0.0
    assert order_bias_flip_rate(["A", "B"], ["A", "A"]) == 0.5
