#!/usr/bin/env python3
"""Validate engineering-submission invariants separately from human-gold readiness."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.annotation.store import load_frozen_candidates  # noqa: E402
from support_agent.data.spotify import sha256_file, write_json  # noqa: E402
from support_agent.evaluation.gold import validate_human_gold  # noqa: E402

REQUIRED_FILES = (
    "README.md",
    "CITATIONS.md",
    "docs/FINAL_REPORT.md",
    "docs/FINAL_DECISION_LOG.md",
    "docs/PHASE5B_FAILURE_AUDIT.md",
    "data/manifests/final_system_manifest.json",
    "data/manifests/final_golden_candidate_manifest.json",
    "data/annotations/final_golden_candidates.csv",
    "results/dev_baseline_fixed.jsonl",
    "results/dev_baseline_lexical.jsonl",
    "results/dev_baseline_manifest.json",
    "results/dev_proposed_agent.jsonl",
    "results/dev_proposed_agent_manifest.json",
    "results/dev_judge_v2_results.jsonl",
    "results/dev_judge_v2_summary.json",
    "results/dev_failure_audit.json",
    "results/dev_phase41_comparison.json",
    "results/top5_failure_modes.json",
)


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def _secret_findings() -> list[str]:
    prefix_patterns = ("gsk" + "_", "sk" + "-")
    findings = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for prefix in prefix_patterns:
                for match in re.finditer(re.escape(prefix) + r"[A-Za-z0-9_-]{20,}", line):
                    findings.append(f"{path.relative_to(ROOT)}:{line_number}:{match.group()[:6]}...")
    return findings


def validate_submission(*, run_tests: bool) -> dict[str, object]:
    checks: dict[str, object] = {}
    errors: list[str] = []
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    checks["required_files"] = {"passed": not missing, "missing": missing}
    if missing:
        errors.append("Required submission files are missing.")

    final_system_path = ROOT / "data/manifests/final_system_manifest.json"
    if final_system_path.exists():
        final_system = json.loads(final_system_path.read_text(encoding="utf-8"))
        system_ok = (
            final_system.get("brand") == "SpotifyCares"
            and final_system.get("final_system_version")
            == "spotify-grounded-agent-v1.0-final-candidate"
            and final_system.get("retained_candidate") == "ORIGINAL_PHASE_4"
            and final_system.get("phase41_status") == "REJECTED"
            and final_system.get("default_config") == "configs/agent.yaml"
            and final_system.get("protection", {}).get("phase41_is_default") is False
        )
        hash_mismatches = [
            name
            for name, expected in final_system.get("file_hashes", {}).items()
            if not (ROOT / {
                "agent_config": "configs/agent.yaml",
                "taxonomy": "configs/taxonomy.yaml",
                "split_manifest": "data/manifests/split_manifest.json",
                "frozen_candidate_manifest": "data/manifests/final_golden_candidate_manifest.json",
                "phase4_development_manifest": "results/dev_proposed_agent_manifest.json",
                "phase5b_comparison": "results/dev_phase41_comparison.json",
                "classifier_implementation": "src/support_agent/classification/classifier.py",
                "retriever_implementation": "src/support_agent/retrieval/hybrid.py",
                "risk_implementation": "src/support_agent/agent/risk.py",
                "orchestrator_implementation": "src/support_agent/agent/orchestrator.py",
                "generator_implementation": "src/support_agent/generation/grounded.py",
                "verifier_implementation": "src/support_agent/generation/verifier.py",
            }[name]).exists()
            or sha256_file(ROOT / {
                "agent_config": "configs/agent.yaml",
                "taxonomy": "configs/taxonomy.yaml",
                "split_manifest": "data/manifests/split_manifest.json",
                "frozen_candidate_manifest": "data/manifests/final_golden_candidate_manifest.json",
                "phase4_development_manifest": "results/dev_proposed_agent_manifest.json",
                "phase5b_comparison": "results/dev_phase41_comparison.json",
                "classifier_implementation": "src/support_agent/classification/classifier.py",
                "retriever_implementation": "src/support_agent/retrieval/hybrid.py",
                "risk_implementation": "src/support_agent/agent/risk.py",
                "orchestrator_implementation": "src/support_agent/agent/orchestrator.py",
                "generator_implementation": "src/support_agent/generation/grounded.py",
                "verifier_implementation": "src/support_agent/generation/verifier.py",
            }[name])
            != expected
        ]
        checks["final_system"] = {
            "passed": system_ok and not hash_mismatches,
            "hash_mismatches": hash_mismatches,
        }
        if not system_ok or hash_mismatches:
            errors.append("Final retained system identity or hashes are invalid.")
    else:
        checks["final_system"] = {"passed": False}
        errors.append("Final-system manifest is missing.")

    candidates = load_frozen_candidates(ROOT / "data/annotations/final_golden_candidates.csv")
    frozen = json.loads(
        (ROOT / "data/manifests/final_golden_candidate_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    splits = json.loads(
        (ROOT / "data/manifests/split_manifest.json").read_text(encoding="utf-8")
    )
    types = Counter(candidate.candidate_type for candidate in candidates)
    protected = set(splits["thread_ids"]["TRAIN"]) | set(
        splits["thread_ids"]["DEVELOPMENT"]
    )
    frozen_ok = (
        len(candidates) == 200
        and len({candidate.case_id for candidate in candidates}) == 200
        and set(frozen["case_ids"]) == {candidate.case_id for candidate in candidates}
        and types == {"REPRESENTATIVE": 160, "CHALLENGE": 40}
        and not protected & {candidate.thread_id for candidate in candidates}
    )
    checks["frozen_evaluation"] = {
        "passed": frozen_ok,
        "case_count": len(candidates),
        "train_development_overlap": len(
            protected & {candidate.thread_id for candidate in candidates}
        ),
    }
    if not frozen_ok:
        errors.append("Frozen 200-case manifest or split protection is invalid.")

    raw_tracked = [
        str(path.relative_to(ROOT))
        for path in _tracked_files()
        if path.relative_to(ROOT).as_posix().startswith("data/raw/")
    ]
    checks["raw_data_untracked"] = {"passed": not raw_tracked, "tracked": raw_tracked}
    if raw_tracked:
        errors.append("Raw TWCS data is tracked.")
    secrets = _secret_findings()
    checks["secret_scan"] = {"passed": not secrets, "findings": secrets}
    if secrets:
        errors.append("Possible provider secrets are present in tracked files.")

    report = (ROOT / "docs/FINAL_REPORT.md").read_text(encoding="utf-8")
    required_report_sections = [f"## {number}." for number in range(1, 10)]
    report_ok = all(section in report for section in required_report_sections)
    decision_text = (ROOT / "docs/FINAL_DECISION_LOG.md").read_text(encoding="utf-8")
    decision_count = len(re.findall(r"^\| \d+ \|", decision_text, flags=re.MULTILINE))
    checks["documentation"] = {
        "passed": report_ok and 12 <= decision_count <= 15,
        "report_sections_present": report_ok,
        "curated_decision_count": decision_count,
    }
    if not report_ok or not 12 <= decision_count <= 15:
        errors.append("Final report or curated decision log is incomplete.")

    phase5b = json.loads(
        (ROOT / "results/dev_phase41_comparison.json").read_text(encoding="utf-8")
    )
    checks["phase41_rejected"] = {
        "passed": phase5b.get("phase41_decision") == "PHASE_4_1_REJECTED"
    }
    if not checks["phase41_rejected"]["passed"]:
        errors.append("Phase 4.1 is not marked rejected.")

    tests_passed = None
    if run_tests:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        tests_passed = completed.returncode == 0
        test_output = completed.stdout + completed.stderr
        count_match = re.search(r"(\d+) passed", test_output)
        checks["tests"] = {"passed": tests_passed}
        if count_match:
            checks["tests"]["test_count"] = int(count_match.group(1))
        if not tests_passed:
            checks["tests"]["failure_summary"] = test_output.strip().splitlines()[-1]
        if not tests_passed:
            errors.append("Test suite failed during submission validation.")
    else:
        checks["tests"] = {"passed": None, "status": "SKIPPED_BY_FLAG"}

    gold = validate_human_gold(
        gold_path=ROOT / "data/annotations/golden_annotations.csv",
        candidates_path=ROOT / "data/annotations/final_golden_candidates.csv",
        frozen_manifest_path=ROOT / "data/manifests/final_golden_candidate_manifest.json",
        split_manifest_path=ROOT / "data/manifests/split_manifest.json",
        taxonomy_path=ROOT / "configs/taxonomy.yaml",
        annotation_config_path=ROOT / "configs/annotation.yaml",
    )
    engineering_ready = not errors
    return {
        "phase": "6A",
        "engineering_submission_ready": engineering_ready,
        "final_evaluation_ready": gold.final_evaluation_ready,
        "engineering_blockers": errors,
        "final_evaluation_blockers": list(gold.errors),
        "human_gold_count": gold.human_label_count,
        "required_human_gold_minimum": gold.required_minimum,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("results/submission_validation.json")
    )
    arguments = parser.parse_args()
    result = validate_submission(run_tests=arguments.run_tests)
    write_json(arguments.output, result)
    print(
        "ENGINEERING_SUBMISSION_READY="
        + ("YES" if result["engineering_submission_ready"] else "NO")
    )
    print(
        "FINAL_EVALUATION_READY="
        + ("YES" if result["final_evaluation_ready"] else "NO")
    )
    print(f"HUMAN_GOLD_COUNT={result['human_gold_count']}")
    if result["engineering_blockers"]:
        print("ENGINEERING_BLOCKERS=" + json.dumps(result["engineering_blockers"]))
    if result["final_evaluation_blockers"]:
        print("FINAL_EVALUATION_BLOCKERS=" + json.dumps(result["final_evaluation_blockers"]))
    return 0 if result["engineering_submission_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
