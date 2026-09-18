"""Thread-level temporal splitting with deterministic leakage remediation."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Iterable

from .leakage import exact_keys, near_duplicate_pairs
from .spotify import SupportThread

SPLITS = ("TRAIN", "DEVELOPMENT", "GOLDEN_CANDIDATE")
SPLIT_RANK = {name: index for index, name in enumerate(SPLITS)}


def validate_ratios(ratios: dict[str, float]) -> None:
    if set(ratios) != set(SPLITS):
        raise ValueError("Split ratios must define TRAIN, DEVELOPMENT, and GOLDEN_CANDIDATE.")
    if any(value <= 0 for value in ratios.values()) or abs(sum(ratios.values()) - 1.0) > 1e-9:
        raise ValueError("Split ratios must be positive and sum to 1.0.")


def temporal_assignments(
    threads: Iterable[SupportThread], ratios: dict[str, float]
) -> dict[str, str]:
    validate_ratios(ratios)
    ordered = sorted(threads, key=lambda item: (item.start_time, item.thread_id))
    train_end = int(len(ordered) * ratios["TRAIN"])
    development_end = train_end + int(len(ordered) * ratios["DEVELOPMENT"])
    return {
        item.thread_id: (
            "TRAIN"
            if index < train_end
            else "DEVELOPMENT"
            if index < development_end
            else "GOLDEN_CANDIDATE"
        )
        for index, item in enumerate(ordered)
    }


def random_assignments(
    threads: Iterable[SupportThread], ratios: dict[str, float], seed: str
) -> dict[str, str]:
    validate_ratios(ratios)
    train_cutoff = ratios["TRAIN"]
    development_cutoff = train_cutoff + ratios["DEVELOPMENT"]
    assignments = {}
    for thread in threads:
        digest = hashlib.sha256(f"{seed}:{thread.thread_id}".encode()).digest()
        value = int.from_bytes(digest[:8], "big") / 2**64
        assignments[thread.thread_id] = (
            "TRAIN"
            if value < train_cutoff
            else "DEVELOPMENT"
            if value < development_cutoff
            else "GOLDEN_CANDIDATE"
        )
    return assignments


def _later_thread(left: str, right: str, assignments: dict[str, str]) -> str:
    left_rank = SPLIT_RANK[assignments[left]]
    right_rank = SPLIT_RANK[assignments[right]]
    if left_rank == right_rank:
        raise ValueError("Expected a cross-split pair.")
    return left if left_rank > right_rank else right


def decontaminate_assignments(
    threads: list[SupportThread], assignments: dict[str, str], config: dict[str, object]
) -> tuple[dict[str, str], dict[str, object]]:
    exact_config = config["exact_collision_policy"]
    near_config = config["near_duplicate_policy"]
    customer_min = int(exact_config["customer_min_words"])
    brand_min = int(exact_config["brand_min_words"])
    ordered = sorted(
        threads,
        key=lambda item: (SPLIT_RANK[assignments[item.thread_id]], item.start_time, item.thread_id),
    )
    owners: dict[tuple[str, str], tuple[str, str]] = {}
    removed_exact: dict[str, dict[str, object]] = {}
    kept: dict[str, str] = {}
    for thread in ordered:
        split = assignments[thread.thread_id]
        conflict = None
        thread_exact_keys = sorted(exact_keys(thread, customer_min, brand_min))
        for key in thread_exact_keys:
            owner = owners.get(key)
            if owner is not None and owner[1] != split:
                conflict = (key[0], owner[0], owner[1])
                break
        if conflict is not None:
            removed_exact[thread.thread_id] = {
                "removed_from": split,
                "conflicts_with_thread": conflict[1],
                "conflicts_with_split": conflict[2],
                "kind": conflict[0],
            }
            continue
        kept[thread.thread_id] = split
        for key in thread_exact_keys:
            owners.setdefault(key, (thread.thread_id, split))

    removed_near: dict[str, dict[str, object]] = {}
    discovered_pairs = 0
    while True:
        kept_threads = [thread for thread in threads if thread.thread_id in kept]
        pairs = near_duplicate_pairs(
            kept_threads,
            kept,
            float(near_config["token_jaccard_threshold"]),
            float(near_config["character_5gram_jaccard_threshold"]),
            int(near_config["minimum_tokens"]),
            int(near_config["bottom_k_signature_size"]),
        )
        discovered_pairs += len(pairs)
        removed_this_pass = 0
        for pair in sorted(
            pairs,
            key=lambda item: (
                -max(float(item["token_jaccard"]), float(item["character_5gram_jaccard"])),
                str(item["left_thread_id"]),
                str(item["right_thread_id"]),
            ),
        ):
            left = str(pair["left_thread_id"])
            right = str(pair["right_thread_id"])
            if left not in kept or right not in kept or kept[left] == kept[right]:
                continue
            removed = _later_thread(left, right, kept)
            retained = right if removed == left else left
            removed_near[removed] = {
                "removed_from": kept[removed],
                "conflicts_with_thread": retained,
                "conflicts_with_split": kept[retained],
                "document_kind": pair["document_kind"],
                "token_jaccard": pair["token_jaccard"],
                "character_5gram_jaccard": pair["character_5gram_jaccard"],
            }
            del kept[removed]
            removed_this_pass += 1
        if removed_this_pass == 0:
            break

    audit = {
        "exact_collisions_discovered": len(removed_exact),
        "near_duplicates_discovered": discovered_pairs,
        "exact_removed": removed_exact,
        "near_removed": removed_near,
        "final_counts": dict(sorted(Counter(kept.values()).items())),
    }
    return kept, audit


def assert_no_overlap(assignments: dict[str, str]) -> None:
    seen: set[str] = set()
    for split in SPLITS:
        current = {thread_id for thread_id, name in assignments.items() if name == split}
        if seen & current:
            raise ValueError("Thread overlap detected between split partitions.")
        seen.update(current)


def assert_partition_lists_no_overlap(partitions: dict[str, list[str]]) -> None:
    if set(partitions) != set(SPLITS):
        raise ValueError("Split manifest must contain all protected partitions.")
    seen: set[str] = set()
    for split in SPLITS:
        current = set(partitions[split])
        if len(current) != len(partitions[split]) or seen & current:
            raise ValueError("Thread overlap or duplicate detected in split manifest.")
        seen.update(current)
