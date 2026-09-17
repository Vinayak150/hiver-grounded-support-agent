#!/usr/bin/env python3
"""Create deterministic, ID-only Phase 1 heuristic-validation samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from support_agent.data.loader import ParsedMessage, TwcsCsvLoader  # noqa: E402
from support_agent.data.profiling import load_config, reply_proxy_flags  # noqa: E402


@dataclass(frozen=True)
class Sample:
    category: str
    brand: str
    candidate_count: int
    tweet_ids: list[str]
    messages: list[ParsedMessage]


def _rank(seed: str, category: str, tweet_id: str) -> str:
    return hashlib.sha256(f"{seed}:{category}:{tweet_id}".encode()).hexdigest()


def _sample(
    seed: str, category: str, brand: str, messages: list[ParsedMessage], size: int
) -> Sample:
    selected = sorted(messages, key=lambda message: _rank(seed, category, message.tweet_id or ""))[
        :size
    ]
    return Sample(
        category, brand, len(messages), [message.tweet_id or "" for message in selected], selected
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    config = load_config(arguments.config)
    raw_config = json.loads(arguments.config.read_text(encoding="utf-8"))
    validation = raw_config["heuristic_validation"]
    seed = str(validation["seed"])
    sample_size = int(validation["sample_size"])
    volume_floor = int(validation["template_comparison_minimum_outbound_messages"])
    profile = json.loads(arguments.profile.read_text(encoding="utf-8"))
    selected_brand = profile["selection_method"]["selected_brand"]
    if not selected_brand:
        raise ValueError("No selected brand is available for heuristic validation.")
    large_accounts = [
        item for item in profile["profiles"] if item["brand_authored_messages"] >= volume_floor
    ]
    high_template_brand = max(
        large_accounts, key=lambda item: item["exact_normalized_duplicate_reply_rate"]
    )["brand"]
    low_template_brand = min(
        large_accounts, key=lambda item: item["exact_normalized_duplicate_reply_rate"]
    )["brand"]
    candidates: dict[str, list[ParsedMessage]] = {
        "generic_or_redirect": [],
        "substantive_actionable": [],
        "high_template_collapse": [],
        "low_template_collapse": [],
    }
    template_messages: dict[str, list[ParsedMessage]] = {
        high_template_brand: [],
        low_template_brand: [],
    }
    loader = TwcsCsvLoader(arguments.input)
    loader.validate()
    for message in loader.rows():
        if message.inbound is not False:
            continue
        if message.author_id == selected_brand:
            substantive, actionable, generic, _ = reply_proxy_flags(
                message.normalized_text, message.words, config
            )
            if generic:
                candidates["generic_or_redirect"].append(message)
            if substantive and actionable:
                candidates["substantive_actionable"].append(message)
        if message.author_id in template_messages:
            template_messages[message.author_id].append(message)

    for category, brand in (
        ("high_template_collapse", high_template_brand),
        ("low_template_collapse", low_template_brand),
    ):
        messages = template_messages[brand]
        counts = Counter(message.normalized_text for message in messages)
        top_template = min(counts, key=lambda text: (-counts[text], text))
        candidates[category] = [
            message for message in messages if message.normalized_text == top_template
        ]

    samples = [
        _sample(
            seed,
            "generic_or_redirect",
            selected_brand,
            candidates["generic_or_redirect"],
            sample_size,
        ),
        _sample(
            seed,
            "substantive_actionable",
            selected_brand,
            candidates["substantive_actionable"],
            sample_size,
        ),
        _sample(
            seed,
            "high_template_collapse",
            high_template_brand,
            candidates["high_template_collapse"],
            sample_size,
        ),
        _sample(
            seed,
            "low_template_collapse",
            low_template_brand,
            candidates["low_template_collapse"],
            sample_size,
        ),
    ]
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    payload = {
        "input_sha256": manifest["sha256"],
        "seed": seed,
        "sample_size": sample_size,
        "selected_brand": selected_brand,
        "template_comparison_minimum_outbound_messages": volume_floor,
        "samples": [
            {
                "category": sample.category,
                "brand": sample.brand,
                "candidate_count": sample.candidate_count,
                "tweet_ids": sample.tweet_ids,
            }
            for sample in samples
        ],
        "privacy_note": (
            "Raw tweet text was displayed only for local manual review and is not stored here."
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for sample in samples:
        print(f"\n## {sample.category} ({sample.brand}; population={sample.candidate_count})")
        for message in sample.messages:
            print(f"{message.tweet_id}: {message.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
