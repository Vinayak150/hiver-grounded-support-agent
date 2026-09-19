#!/usr/bin/env python3
"""Freeze the retained original Phase 4 candidate and its exact dependencies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.data.spotify import sha256_file, write_json  # noqa: E402

FILES = {
    "agent_config": Path("configs/agent.yaml"),
    "taxonomy": Path("configs/taxonomy.yaml"),
    "split_manifest": Path("data/manifests/split_manifest.json"),
    "frozen_candidate_manifest": Path("data/manifests/final_golden_candidate_manifest.json"),
    "phase4_development_manifest": Path("results/dev_proposed_agent_manifest.json"),
    "phase5b_comparison": Path("results/dev_phase41_comparison.json"),
    "classifier_implementation": Path("src/support_agent/classification/classifier.py"),
    "retriever_implementation": Path("src/support_agent/retrieval/hybrid.py"),
    "risk_implementation": Path("src/support_agent/agent/risk.py"),
    "orchestrator_implementation": Path("src/support_agent/agent/orchestrator.py"),
    "generator_implementation": Path("src/support_agent/generation/grounded.py"),
    "verifier_implementation": Path("src/support_agent/generation/verifier.py"),
}


def build_manifest() -> dict[str, object]:
    config = json.loads(FILES["agent_config"].read_text(encoding="utf-8"))
    development = json.loads(
        FILES["phase4_development_manifest"].read_text(encoding="utf-8")
    )
    phase5b = json.loads(FILES["phase5b_comparison"].read_text(encoding="utf-8"))
    if config["version"] != "spotify-grounded-agent-v1":
        raise ValueError("The default agent config is no longer original Phase 4 behavior.")
    if phase5b["phase41_decision"] != "PHASE_4_1_REJECTED":
        raise ValueError("Phase 4.1 must remain rejected in the final-system manifest.")
    return {
        "phase": "6A",
        "brand": "SpotifyCares",
        "final_system_version": "spotify-grounded-agent-v1.0-final-candidate",
        "implementation_version": config["version"],
        "retained_candidate": "ORIGINAL_PHASE_4",
        "default_config": str(FILES["agent_config"]),
        "phase41_status": "REJECTED",
        "frozen": True,
        "development_only_calibrated_thresholds": development["evidence_gate"]["thresholds"],
        "classifier": config["classifier"],
        "retrieval": config["retrieval"],
        "calibration": config["calibration"],
        "risk_rules": config["risk"],
        "generation": config["generation"],
        "verifier": config["verifier"],
        "protection": {
            "classifier_training_split": "TRAIN",
            "retrieval_corpus_split": "TRAIN",
            "calibration_split": "DEVELOPMENT",
            "frozen_evaluation_used_for_optimization": False,
            "human_gold_used_for_model_selection": 0,
            "ai_provisional_used_as_gold": False,
            "phase41_is_default": False,
        },
        "hash_algorithm": "sha256",
        "file_hashes": {name: sha256_file(path) for name, path in sorted(FILES.items())},
    }


def main() -> int:
    output = Path("data/manifests/final_system_manifest.json")
    manifest = build_manifest()
    write_json(output, manifest)
    print(f"FINAL_SYSTEM={manifest['final_system_version']}")
    print(f"PHASE_4_1_STATUS={manifest['phase41_status']}")
    print(f"FINAL_SYSTEM_MANIFEST={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
