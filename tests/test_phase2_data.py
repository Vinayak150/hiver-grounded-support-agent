from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from support_agent.data.leakage import (
    exact_cross_split_collisions,
    near_duplicate_pairs,
)
from support_agent.data.splits import (
    assert_partition_lists_no_overlap,
    decontaminate_assignments,
    temporal_assignments,
)
from support_agent.data.spotify import SupportThread, Turn, extract_spotify_corpus, read_threads
from support_agent.taxonomy.schema import validate_taxonomy


def _thread(
    thread_id: str,
    start: str,
    customer: str,
    spotify: str = "Please restart the app and let us know.",
) -> SupportThread:
    turns = (
        Turn(f"{thread_id}-1", "CUSTOMER", customer, start, None),
        Turn(f"{thread_id}-2", "SPOTIFY", spotify, start, f"{thread_id}-1"),
    )
    return SupportThread(thread_id, f"root-{thread_id}", 2, 1, 1, start, start, 2, turns)


def _taxonomy_payload() -> dict[str, object]:
    return {
        "version": "v1",
        "brand": "SpotifyCares",
        "source_split": "TRAIN",
        "default_intent": "other",
        "intents": [
            {
                "id": "playback",
                "display_name": "Playback",
                "definition": "Playback problems",
                "include_when": "Playback is central",
                "exclude_when": "Account access is central",
                "boundary_notes": "Prefer account when access is central",
                "common_signals": ["play"],
            },
            {
                "id": "other",
                "display_name": "Other",
                "definition": "Unclear",
                "include_when": "No intent is clear",
                "exclude_when": "A specific intent is clear",
                "boundary_notes": "Preserve abstention",
                "common_signals": [],
            },
        ],
    }


def test_spotify_thread_extraction_requires_brand_and_customer(tmp_path: Path) -> None:
    source = tmp_path / "twcs.csv"
    source.write_text(
        "tweet_id,author_id,inbound,created_at,text,response_tweet_id,in_response_to_tweet_id\n"
        '1,user,true,2017-01-01T00:00:00Z,"Cannot play songs",2,\n'
        '2,SpotifyCares,false,2017-01-01T00:01:00Z,"Please restart",,1\n'
        '3,SpotifyCares,false,2017-01-02T00:00:00Z,"Broadcast only",,\n'
        '4,user,true,2017-01-03T00:00:00Z,"Other brand",5,\n'
        '5,OtherBrand,false,2017-01-03T00:01:00Z,"Reply",,4\n',
        encoding="utf-8",
    )
    output = tmp_path / "spotify.jsonl"
    manifest = tmp_path / "manifest.json"
    result = extract_spotify_corpus(source, output, manifest)
    rows = list(read_threads(output))
    assert result["total_brand_threads"] == 2
    assert result["total_relevant_threads"] == 1
    assert len(rows) == 1
    assert rows[0].customer_message_count == 1


def test_temporal_split_is_deterministic_and_manifest_stable() -> None:
    threads = [
        _thread(str(index), f"2017-01-{index + 1:02d}T00:00:00Z", f"question {index}")
        for index in range(10)
    ]
    ratios = {"TRAIN": 0.7, "DEVELOPMENT": 0.2, "GOLDEN_CANDIDATE": 0.1}
    first = temporal_assignments(threads, ratios)
    second = temporal_assignments(list(reversed(threads)), ratios)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_partition_overlap_is_rejected() -> None:
    with pytest.raises(ValueError):
        assert_partition_lists_no_overlap(
            {"TRAIN": ["a"], "DEVELOPMENT": ["b", "a"], "GOLDEN_CANDIDATE": ["c"]}
        )


def test_exact_message_leakage_is_detected_and_removed_from_later_split() -> None:
    threads = [
        _thread("train", "2017-01-01T00:00:00Z", "same customer message"),
        _thread("gold", "2017-02-01T00:00:00Z", "same customer message"),
    ]
    assignments = {"train": "TRAIN", "gold": "GOLDEN_CANDIDATE"}
    assert exact_cross_split_collisions(threads, assignments)
    config = {
        "exact_collision_policy": {"customer_min_words": 1, "brand_min_words": 8},
        "near_duplicate_policy": {
            "token_jaccard_threshold": 0.9,
            "character_5gram_jaccard_threshold": 0.92,
            "minimum_tokens": 4,
            "bottom_k_signature_size": 12,
        },
    }
    clean, audit = decontaminate_assignments(threads, assignments, config)
    assert "gold" not in clean
    assert audit["exact_collisions_discovered"] == 1


def test_decontamination_manifest_is_hash_seed_independent() -> None:
    source = """
import json
from support_agent.data.spotify import SupportThread, Turn
from support_agent.data.splits import decontaminate_assignments

def thread(thread_id, customer, spotify):
    timestamp = "2017-01-01T00:00:00+00:00"
    turns = (
        Turn(thread_id + "-1", "CUSTOMER", customer, timestamp, None),
        Turn(thread_id + "-2", "SPOTIFY", spotify, timestamp, thread_id + "-1"),
    )
    return SupportThread(thread_id, thread_id, 2, 1, 1, timestamp, timestamp, 2, turns)

threads = [
    thread("train-a", "same customer", "first brand response"),
    thread("train-b", "other customer", "same spotify response"),
    thread("gold", "same customer", "same spotify response"),
]
config = {
    "exact_collision_policy": {"customer_min_words": 1, "brand_min_words": 1},
    "near_duplicate_policy": {
        "token_jaccard_threshold": 1.0,
        "character_5gram_jaccard_threshold": 1.0,
        "minimum_tokens": 100,
        "bottom_k_signature_size": 4,
    },
}
assignments = {"train-a": "TRAIN", "train-b": "TRAIN", "gold": "GOLDEN_CANDIDATE"}
clean, audit = decontaminate_assignments(threads, assignments, config)
print(json.dumps({"clean": clean, "audit": audit}, sort_keys=True))
"""
    outputs = []
    project_src = str(Path(__file__).resolve().parents[1] / "src")
    for seed in ("1", "2", "3"):
        environment = os.environ.copy()
        environment.update({"PYTHONHASHSEED": seed, "PYTHONPATH": project_src})
        result = subprocess.run(
            [sys.executable, "-c", source],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(result.stdout)
    assert len(set(outputs)) == 1


def test_near_duplicate_fixture_is_detected() -> None:
    threads = [
        _thread("train", "2017-01-01T00:00:00Z", "spotify will not play any songs today"),
        _thread("gold", "2017-02-01T00:00:00Z", "spotify will not play songs today"),
    ]
    pairs = near_duplicate_pairs(
        threads,
        {"train": "TRAIN", "gold": "GOLDEN_CANDIDATE"},
        token_threshold=0.8,
        character_threshold=0.8,
        minimum_tokens=4,
        signature_size=20,
    )
    assert pairs
    assert pairs[0]["document_kind"] == "CUSTOMER"


def test_taxonomy_schema_and_unique_intent_ids() -> None:
    taxonomy = validate_taxonomy(_taxonomy_payload())
    assert taxonomy.intent_ids == ("playback", "other")
    invalid = _taxonomy_payload()
    invalid["intents"] = [invalid["intents"][0], invalid["intents"][0]]
    with pytest.raises(ValueError, match="unique"):
        validate_taxonomy(invalid)
