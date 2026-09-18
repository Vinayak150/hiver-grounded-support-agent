"""Exact and high-similarity cross-split leakage detection."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .schema import normalized_reply, word_count
from .spotify import SupportThread

TOKEN_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class LeakageDocument:
    thread_id: str
    split: str
    kind: str
    normalized: str
    tokens: frozenset[str]
    character_grams: frozenset[str]


def normalize_for_leakage(text: str) -> str:
    normalized = normalized_reply(text)
    normalized = re.sub(r"\b\d{5,}\b", "<number>", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def token_set(text: str) -> frozenset[str]:
    return frozenset(TOKEN_RE.findall(text.casefold()))


def character_ngrams(text: str, size: int = 5) -> frozenset[str]:
    compact = re.sub(r"\s+", " ", text.casefold()).strip()
    if len(compact) < size:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + size] for index in range(len(compact) - size + 1))


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def exact_keys(
    thread: SupportThread, customer_min_words: int = 1, brand_min_words: int = 8
) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for turn in thread.turns:
        normalized = normalize_for_leakage(turn.text)
        minimum = customer_min_words if turn.author_role == "CUSTOMER" else brand_min_words
        if turn.author_role in {"CUSTOMER", "SPOTIFY"} and word_count(normalized) >= minimum:
            keys.add((turn.author_role, normalized))
    customer_prefix = " ".join(
        normalize_for_leakage(turn.text) for turn in thread.turns if turn.author_role == "CUSTOMER"
    )[:240]
    if customer_prefix:
        keys.add(("CUSTOMER_PREFIX", customer_prefix))
    return keys


def leakage_documents(
    threads: Iterable[SupportThread], assignments: dict[str, str], minimum_tokens: int = 4
) -> list[LeakageDocument]:
    documents = []
    for thread in threads:
        split = assignments.get(thread.thread_id)
        if split is None:
            continue
        for kind, text in (
            ("CUSTOMER", thread.customer_text()),
            ("SPOTIFY", thread.spotify_text()),
        ):
            normalized = normalize_for_leakage(text)
            tokens = token_set(normalized)
            if len(tokens) < minimum_tokens:
                continue
            documents.append(
                LeakageDocument(
                    thread_id=thread.thread_id,
                    split=split,
                    kind=kind,
                    normalized=normalized,
                    tokens=tokens,
                    character_grams=character_ngrams(normalized),
                )
            )
    return documents


def _bottom_k_signature(values: frozenset[str], size: int) -> tuple[int, ...]:
    hashes = sorted(
        int.from_bytes(hashlib.blake2b(value.encode(), digest_size=8).digest(), "big")
        for value in values
    )
    return tuple(hashes[:size])


def near_duplicate_pairs(
    threads: Iterable[SupportThread],
    assignments: dict[str, str],
    token_threshold: float,
    character_threshold: float,
    minimum_tokens: int,
    signature_size: int,
) -> list[dict[str, object]]:
    """Find cross-split near duplicates with bottom-k blocking then exact similarity."""

    documents = leakage_documents(threads, assignments, minimum_tokens)
    buckets: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, document in enumerate(documents):
        for value in _bottom_k_signature(document.character_grams, signature_size):
            buckets[(document.kind, value)].append(index)
    candidates: set[tuple[int, int]] = set()
    for bucket in buckets.values():
        if len(bucket) > 250:
            continue
        for left_position, left in enumerate(bucket):
            for right in bucket[left_position + 1 :]:
                if documents[left].split != documents[right].split:
                    candidates.add((min(left, right), max(left, right)))
    pairs = []
    seen_threads: set[tuple[str, str, str]] = set()
    for left_index, right_index in sorted(candidates):
        left = documents[left_index]
        right = documents[right_index]
        if left.kind != right.kind or left.thread_id == right.thread_id:
            continue
        token_score = jaccard(left.tokens, right.tokens)
        character_score = jaccard(left.character_grams, right.character_grams)
        if token_score < token_threshold and character_score < character_threshold:
            continue
        key = tuple(sorted((left.thread_id, right.thread_id))) + (left.kind,)
        if key in seen_threads:
            continue
        seen_threads.add(key)
        pairs.append(
            {
                "left_thread_id": left.thread_id,
                "left_split": left.split,
                "right_thread_id": right.thread_id,
                "right_split": right.split,
                "document_kind": left.kind,
                "token_jaccard": round(token_score, 6),
                "character_5gram_jaccard": round(character_score, 6),
            }
        )
    return pairs


def exact_cross_split_collisions(
    threads: Iterable[SupportThread],
    assignments: dict[str, str],
    customer_min_words: int = 1,
    brand_min_words: int = 8,
) -> list[dict[str, object]]:
    owners: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for thread in threads:
        if thread.thread_id not in assignments:
            continue
        for key in exact_keys(thread, customer_min_words, brand_min_words):
            owners[key].append((thread.thread_id, assignments[thread.thread_id]))
    collisions = []
    for (kind, normalized), members in owners.items():
        if len({split for _, split in members}) > 1:
            collisions.append(
                {
                    "kind": kind,
                    "normalized_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
                    "thread_ids": sorted(thread_id for thread_id, _ in members),
                    "splits": sorted({split for _, split in members}),
                }
            )
    return sorted(collisions, key=lambda item: (item["kind"], item["normalized_sha256"]))
