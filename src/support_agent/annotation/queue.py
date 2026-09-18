"""Deterministic representative/challenge sampling from the protected pool."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

from support_agent.data.spotify import SupportThread
from support_agent.taxonomy.discovery import provisional_intent
from support_agent.taxonomy.schema import Taxonomy

from .schema import CandidateCase


def deterministic_rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def sanitize_public_text(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", "<url>", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<email>", text)
    text = re.sub(r"@[A-Za-z0-9_]+", "<mention>", text)
    text = re.sub(r"\b\d{7,}\b", "<number>", text)
    return re.sub(r"\s+", " ", text).strip()


def challenge_proxies(thread: SupportThread, train_token_counts: Counter[str]) -> tuple[str, ...]:
    text = thread.customer_text()
    normalized = text.casefold()
    tokens = re.findall(r"[a-z][a-z']+", normalized)
    proxies = []
    if len(tokens) <= 5:
        proxies.append("VERY_SHORT")
    if len(tokens) >= 60:
        proxies.append("UNUSUALLY_LONG")
    if (
        normalized.count("?") >= 2
        or sum(normalized.count(term) for term in (" and ", " but ")) >= 2
    ):
        proxies.append("MULTI_CLAUSE")
    if any(term in normalized for term in ("hacked", "password", "charged", "refund", "payment")):
        proxies.append("RISK_TERMS")
    if sum(term in normalized for term in ("iphone", "android", "windows", "mac", "speaker")) >= 2:
        proxies.append("MULTI_DEVICE")
    known = sum(train_token_counts[token] for token in set(tokens))
    if tokens and known / len(set(tokens)) < 3:
        proxies.append("RARE_LEXICON")
    return tuple(proxies)


def sample_candidates(
    golden_threads: list[SupportThread],
    train_threads: list[SupportThread],
    taxonomy: Taxonomy,
    config: dict[str, object],
) -> list[CandidateCase]:
    target = int(config["candidate_count"])
    representative_target = int(config["representative_count"])
    challenge_target = int(config["challenge_count"])
    if representative_target + challenge_target != target:
        raise ValueError("Representative and challenge counts must equal candidate_count.")
    if len(golden_threads) < target:
        raise ValueError("Golden-candidate split is too small for the requested queue.")
    seed = str(config["seed"])
    train_counts: Counter[str] = Counter()
    for thread in train_threads:
        train_counts.update(re.findall(r"[a-z][a-z']+", thread.customer_text().casefold()))
    groups: dict[str, list[SupportThread]] = defaultdict(list)
    for thread in golden_threads:
        groups[provisional_intent(thread.customer_text(), taxonomy)].append(thread)
    for group in groups.values():
        group.sort(key=lambda item: deterministic_rank(seed, item.thread_id))
    representative: list[SupportThread] = []
    while len(representative) < representative_target:
        added = False
        for intent_id in taxonomy.intent_ids:
            if groups[intent_id] and len(representative) < representative_target:
                representative.append(groups[intent_id].pop(0))
                added = True
        if not added:
            raise ValueError("Insufficient threads for representative sampling.")
    used = {thread.thread_id for thread in representative}
    challenge_ranked = sorted(
        (thread for thread in golden_threads if thread.thread_id not in used),
        key=lambda item: (
            -len(challenge_proxies(item, train_counts)),
            deterministic_rank(f"{seed}:challenge", item.thread_id),
        ),
    )
    challenge = challenge_ranked[:challenge_target]
    if len(challenge) != challenge_target:
        raise ValueError("Insufficient threads for challenge sampling.")
    selected = [(thread, "REPRESENTATIVE") for thread in representative] + [
        (thread, "CHALLENGE") for thread in challenge
    ]
    rows = []
    for position, (thread, bucket) in enumerate(selected, start=1):
        customer_turns = [turn for turn in thread.turns if turn.author_role == "CUSTOMER"]
        context_turns = thread.turns[-6:]
        rows.append(
            CandidateCase(
                case_id=f"spotify-gold-candidate-{position:03d}",
                thread_id=thread.thread_id,
                taxonomy_version=str(config["taxonomy_version"]),
                sampling_version=str(config["sampling_version"]),
                split_version=str(config["split_version"]),
                sampling_bucket=bucket,
                customer_message=sanitize_public_text(customer_turns[0].text),
                conversation_context=" || ".join(
                    f"{turn.author_role}: {sanitize_public_text(turn.text)}"
                    for turn in context_turns
                ),
                challenge_proxies="|".join(challenge_proxies(thread, train_counts))
                if bucket == "CHALLENGE"
                else "",
            )
        )
    return rows
