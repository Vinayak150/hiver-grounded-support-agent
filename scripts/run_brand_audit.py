#!/usr/bin/env python3
"""Run the Phase 1.5 saturated brand-selection audit without committing raw text."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from support_agent.data.audit import (  # noqa: E402
    audit_message_categories,
    derive_text_signals,
    deterministic_rank,
    linked_inbound_rows,
    profile_to_signals,
    select_weighted,
)
from support_agent.data.loader import TwcsCsvLoader  # noqa: E402
from support_agent.data.profiling import BrandProfile, load_config  # noqa: E402
from support_agent.data.threads import ThreadIndex  # noqa: E402

LABEL_FIELDS = [
    "historical_reply_value",
    "publicly_actionable",
    "private_lookup_required",
    "template_like",
    "multi_turn_usefulness",
    "reviewer_note",
]
OUTPUT_FIELDS = [
    "brand",
    "thread_id",
    "root_tweet_id",
    "sample_category",
    "representative_tweet_id",
    *LABEL_FIELDS,
]


def _read_existing_labels(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        return {
            (row["brand"], row["thread_id"]): {field: row.get(field, "") for field in LABEL_FIELDS}
            for row in csv.DictReader(stream)
        }


def _manual_value(rows: list[dict[str, str]], brand: str) -> tuple[float, int]:
    scale = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.0}
    values = [
        scale[row["historical_reply_value"]]
        for row in rows
        if row["brand"] == brand and row["historical_reply_value"] in scale
    ]
    return (sum(values) / len(values) if values else 0.5, len(values))


def _write_review_pack(index: ThreadIndex, samples: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Local-only Phase 1.5 review pack", ""]
    for sample in samples:
        lines.extend(
            [
                f"## {sample['brand']} | {sample['sample_category']} | {sample['thread_id']}",
                "",
            ]
        )
        messages = index.connection.execute(
            """
            SELECT author_id, inbound, created_at, text
            FROM messages JOIN root_cache ON root_cache.tweet_id = messages.tweet_id
            WHERE root_cache.root_id = ? ORDER BY messages.created_epoch, messages.tweet_id
            """,
            (sample["root_tweet_id"],),
        ).fetchall()
        for message in messages:
            direction = "CUSTOMER" if message["inbound"] == 1 else "BRAND"
            lines.append(f"- [{direction}] @{message['author_id']}: {message['text']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--profiling-config", required=True, type=Path)
    parser.add_argument("--audit-config", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--review-pack", required=True, type=Path)
    arguments = parser.parse_args()

    audit_config = json.loads(arguments.audit_config.read_text(encoding="utf-8"))
    initial_brand = audit_config["initial_phase_1_brand"]
    final_brand = audit_config["final_post_audit_brand"]
    profile_payload = json.loads(arguments.profile.read_text(encoding="utf-8"))
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    profile_config = load_config(arguments.profiling_config)
    requested = list(audit_config["candidates"])
    profiles = {
        item["brand"]: BrandProfile(**item)
        for item in profile_payload["profiles"]
        if item["brand"] in requested
    }
    if set(profiles) != set(requested):
        raise ValueError("One or more audit candidates are missing from Phase 1 profiles.")
    if initial_brand not in profiles or final_brand not in profiles:
        raise ValueError("Configured initial and final brands must be among audit candidates.")
    existing_labels = _read_existing_labels(arguments.annotations)
    loader = TwcsCsvLoader(arguments.input)
    loader.validate()
    with tempfile.TemporaryDirectory(prefix="twcs-brand-audit-") as temporary_directory:
        with ThreadIndex(Path(temporary_directory) / "twcs.sqlite3") as index:
            for message in loader.rows():
                index.add(message)
            index.finalize_ingestion()
            index.reconstruct_threads()
            rows: list[dict[str, str]] = []
            for brand in audit_config["manual_audit_brands"]:
                categories = audit_message_categories(index, brand, profile_config)
                used: set[str] = set()
                for category, candidates in categories.items():
                    selected = []
                    for root_id in sorted(
                        candidates,
                        key=lambda root: deterministic_rank(
                            audit_config["sample_seed"], brand, category, root
                        ),
                    ):
                        if root_id not in used:
                            selected.append((root_id, candidates[root_id]))
                            used.add(root_id)
                        if len(selected) == audit_config["sample_size_per_stratum"]:
                            break
                    if len(selected) != audit_config["sample_size_per_stratum"]:
                        raise ValueError(
                            f"Insufficient unique {category} audit threads for {brand}."
                        )
                    for root_id, tweet_id in selected:
                        thread_id = index.thread_id_for(tweet_id)
                        label_values = existing_labels.get((brand, thread_id or ""), {})
                        rows.append(
                            {
                                "brand": brand,
                                "thread_id": thread_id or "",
                                "root_tweet_id": root_id,
                                "sample_category": category,
                                "representative_tweet_id": tweet_id,
                                **{field: label_values.get(field, "") for field in LABEL_FIELDS},
                            }
                        )
            _write_review_pack(index, rows, arguments.review_pack)
            candidate_signals = {}
            for brand, profile in profiles.items():
                inbound = linked_inbound_rows(index, brand)
                topic_entropy, escalation_proxy = derive_text_signals(
                    inbound, audit_config["risk_terms"]
                )
                manual_value, labeled_count = _manual_value(rows, brand)
                candidate_signals[brand] = {
                    "topic_entropy_proxy": topic_entropy,
                    "escalation_learning_proxy": escalation_proxy,
                    "manual_reply_value_proxy": round(manual_value, 8),
                    "manual_labels_present": labeled_count,
                }

    arguments.annotations.parent.mkdir(parents=True, exist_ok=True)
    with arguments.annotations.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    signals = [
        profile_to_signals(
            profiles[brand],
            candidate_signals[brand]["topic_entropy_proxy"],
            candidate_signals[brand]["escalation_learning_proxy"],
            candidate_signals[brand]["manual_reply_value_proxy"],
            audit_config["saturation_target_multiturn_threads"],
        )
        for brand in requested
    ]
    sensitivity = {}
    for name, weights in audit_config["weight_sets"].items():
        winner, scores = select_weighted(signals, weights)
        sensitivity[name] = {"winner": winner, "scores": scores, "weights": weights}
    output = {
        "phase": "1.5",
        "input_sha256": manifest["sha256"],
        "initial_phase_1_brand": initial_brand,
        "final_post_audit_brand": final_brand,
        "candidates": requested,
        "saturation_target_multiturn_threads": audit_config["saturation_target_multiturn_threads"],
        "manual_audit": {
            "brands": audit_config["manual_audit_brands"],
            "sample_size_per_stratum": audit_config["sample_size_per_stratum"],
            "strata": [
                "multi_turn",
                "high_public_containment",
                "generic_redirect",
                "repeated_template",
            ],
            "sample_rows": len(rows),
            "raw_text_committed": False,
        },
        "candidate_signals": candidate_signals,
        "raw_profiles": {brand: profiles[brand].as_dict() for brand in requested},
        "sensitivity_analysis": sensitivity,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Audit samples: {len(rows)}")
    print(f"Local-only review pack: {arguments.review_pack}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
