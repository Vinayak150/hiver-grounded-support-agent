from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from support_agent.data.audit import (
    AuditSignals,
    deterministic_rank,
    normalized_entropy,
    saturated_corpus_score,
    select_weighted,
    weighted_score,
)


def _signals(brand: str, grounding: float) -> AuditSignals:
    return AuditSignals(brand, 1.0, grounding, 0.8, 0.9, 0.7, 0.99, 0.2, 0.5)


def test_saturated_corpus_score_caps_extra_volume() -> None:
    assert saturated_corpus_score(5_000, 10_000) == 0.5
    assert saturated_corpus_score(10_000, 10_000) == 1.0
    assert saturated_corpus_score(50_000, 10_000) == 1.0
    with pytest.raises(ValueError):
        saturated_corpus_score(1, 0)


def test_entropy_and_deterministic_sampling_rank_are_stable() -> None:
    assert normalized_entropy(Counter()) == 0.0
    assert normalized_entropy(Counter({"only": 3})) == 0.0
    assert normalized_entropy(Counter({"a": 1, "b": 1})) == 1.0
    assert deterministic_rank("seed", "brand", "stratum", "root") == deterministic_rank(
        "seed", "brand", "stratum", "root"
    )
    roots = ["thread-c", "thread-a", "thread-b"]
    sample = sorted(
        roots, key=lambda root: deterministic_rank("seed", "brand", "stratum", root)
    )[:2]
    assert sample == sorted(
        roots, key=lambda root: deterministic_rank("seed", "brand", "stratum", root)
    )[:2]
    assert len(set(sample)) == 2


def test_weighted_selection_requires_complete_weights_and_breaks_ties() -> None:
    weights = {
        "corpus": 0.0,
        "grounding": 1.0,
        "low_generic": 0.0,
        "anti_template": 0.0,
        "topic_diversity": 0.0,
        "reconstruction": 0.0,
        "escalation_value": 0.0,
        "manual_value": 0.0,
    }
    winner, scores = select_weighted([_signals("Zeta", 0.8), _signals("Alpha", 0.8)], weights)
    assert winner == "Alpha"
    assert scores["Alpha"] == 0.8
    with pytest.raises(ValueError):
        weighted_score(_signals("Alpha", 0.8), {"grounding": 1.0})


def test_committed_sensitivity_analysis_freezes_configured_brand() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "configs" / "brand_audit.json").read_text())
    audit = json.loads((root / "results" / "brand_selection_audit.json").read_text())

    assert audit["final_post_audit_brand"] == config["final_post_audit_brand"]
    assert set(audit["sensitivity_analysis"]) == set(config["weight_sets"])
    assert {
        result["winner"] for result in audit["sensitivity_analysis"].values()
    } == {config["final_post_audit_brand"]}
