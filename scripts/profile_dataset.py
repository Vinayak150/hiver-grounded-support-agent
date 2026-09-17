#!/usr/bin/env python3
"""Run Phase 1 profiling on a local TWCS CSV without exposing raw text in outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from support_agent.data.profiling import profile_dataset  # noqa: E402
from support_agent.data.schema import SchemaValidationError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path, help="Local, uncommitted TWCS CSV path"
    )
    parser.add_argument("--config", required=True, type=Path, help="Profiling YAML configuration")
    parser.add_argument(
        "--manifest", type=Path, default=REPOSITORY_ROOT / "data/manifests/twcs_manifest.json"
    )
    parser.add_argument(
        "--profile-csv", type=Path, default=REPOSITORY_ROOT / "results/brand_profile.csv"
    )
    parser.add_argument(
        "--profile-json", type=Path, default=REPOSITORY_ROOT / "results/brand_profile.json"
    )
    parser.add_argument(
        "--brand-report", type=Path, default=REPOSITORY_ROOT / "docs/BRAND_SELECTION.md"
    )
    arguments = parser.parse_args()
    try:
        result = profile_dataset(
            input_path=arguments.input,
            config_path=arguments.config,
            manifest_path=arguments.manifest,
            profile_csv_path=arguments.profile_csv,
            profile_json_path=arguments.profile_json,
            brand_report_path=arguments.brand_report,
        )
    except (FileNotFoundError, SchemaValidationError, ValueError) as error:
        print(f"Phase 1 profiling blocked: {error}", file=sys.stderr)
        return 2
    print("Phase 1 profiling completed.")
    print(f"Manifest: {result.manifest_path}")
    print(f"Candidate profile: {result.profile_csv_path}")
    print(f"Selected brand: {result.selected_brand or 'none (no eligible outbound account)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
