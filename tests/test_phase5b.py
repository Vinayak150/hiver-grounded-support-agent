from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.audit_phase5b as audit
import scripts.finalize_phase5b as finalize
import scripts.run_phase5b as phase5b


def test_phase5b_holdout_is_frozen_disjoint_and_stratified():
    config = json.loads(Path("configs/judge_phase5b.yaml").read_text(encoding="utf-8"))
    manifest = phase5b.build_holdout(config)
    phase5a_ids = {
        item["case_id"]
        for item in json.loads(
            Path("results/dev_judge_v2_sample_manifest.json").read_text(encoding="utf-8")
        )["cases"]
    }
    ids = {item["case_id"] for item in manifest["cases"]}
    assert len(ids) == 60
    assert manifest["changed_case_count"] == 22
    assert manifest["unchanged_case_count"] == 38
    assert not ids & phase5a_ids
    assert manifest["protection"]["frozen_200_excluded"]


def test_phase5b_paired_outcome_prioritizes_safety_and_pass():
    base = {
        "groundedness": 4,
        "relevance": 4,
        "helpfulness": 4,
        "safety": 5,
        "brand_context": 3,
        "overall_pass": True,
        "critical_failure": False,
        "failure_codes": [],
    }
    unsafe = {**base, "safety": 4, "failure_codes": ["P"]}
    outcome, safety_regression = phase5b._paired_outcome(base, unsafe)
    assert (outcome, safety_regression) == ("REGRESSED", True)
    failed = {**base, "groundedness": 3, "overall_pass": False}
    outcome, safety_regression = phase5b._paired_outcome(failed, base)
    assert (outcome, safety_regression) == ("IMPROVED", False)


def test_phase5b_expected_frozen_hashes_are_current():
    assert {str(path): audit.sha256_file(path) for path in audit.FROZEN_PHASE5A} == (
        audit.EXPECTED_HASHES
    )


def test_phase5b_completed_pair_manifest_uses_only_45_complete_pairs():
    manifest = finalize.build_completed_manifest()
    assert manifest["original_holdout_size"] == 60
    assert manifest["completed_pairs"] == 45
    assert manifest["missing_pairs"] == 15
    assert manifest["completion_rate"] == 0.75
    assert len(manifest["completed_case_ids"]) == 45
    assert len(manifest["missing_case_ids"]) == 15
    assert not set(manifest["completed_case_ids"]) & set(manifest["missing_case_ids"])
    assert manifest["pre_judge_missingness_audit"]["score_fields_used"] is False


def test_phase5b_final_comparison_reconciles_to_raw_complete_pairs():
    manifest = finalize.build_completed_manifest()
    comparison = finalize.build_comparison(manifest)
    assert comparison["completed_pairs"] == 45
    assert comparison["original_metrics"]["case_count"] == 45
    assert comparison["revised_metrics"]["case_count"] == 45
    assert sum(comparison["paired_outcomes"]["counts"].values()) == 45
    assert sum(comparison["paired_outcomes"]["binary_pass_transitions"].values()) == 45
    assert sum(comparison["critical_failure_transitions"].values()) == 45
    assert comparison["new_provider_calls"] == 0
