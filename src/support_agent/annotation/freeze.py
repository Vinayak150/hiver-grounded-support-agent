"""Deterministic, diversity-aware freezing of final evaluation candidates."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass

from support_agent.data.leakage import character_ngrams, jaccard, normalize_for_leakage, token_set
from support_agent.data.spotify import SupportThread
from support_agent.taxonomy.discovery import provisional_intent
from support_agent.taxonomy.schema import Taxonomy

from .queue import deterministic_rank, sanitize_public_text
from .schema import CandidateCase, FrozenCandidate


@dataclass(frozen=True)
class SelectionItem:
    case: CandidateCase
    thread: SupportThread
    topic: str
    time_bin: int
    proxies: tuple[str, ...]
    documents: tuple[str, ...]
    token_documents: tuple[frozenset[str], ...]
    character_documents: tuple[frozenset[str], ...]


def _time_bins(
    cases: list[CandidateCase], threads: dict[str, SupportThread], count: int
) -> dict[str, int]:
    ordered = sorted(cases, key=lambda case: (threads[case.thread_id].start_time, case.thread_id))
    return {
        case.case_id: min(index * count // len(ordered), count - 1)
        for index, case in enumerate(ordered)
    }


def _items(
    cases: list[CandidateCase],
    threads: dict[str, SupportThread],
    taxonomy: Taxonomy,
    time_bin_count: int,
) -> list[SelectionItem]:
    bins = _time_bins(cases, threads, time_bin_count)
    result = []
    for case in cases:
        thread = threads[case.thread_id]
        documents = (
            normalize_for_leakage(case.customer_message),
            normalize_for_leakage(thread.customer_text()),
        )
        result.append(
            SelectionItem(
                case=case,
                thread=thread,
                topic=provisional_intent(thread.customer_text(), taxonomy),
                time_bin=bins[case.case_id],
                proxies=tuple(value for value in case.challenge_proxies.split("|") if value),
                documents=documents,
                token_documents=tuple(token_set(value) for value in documents),
                character_documents=tuple(character_ngrams(value) for value in documents),
            )
        )
    return result


def _duplicates(
    left: SelectionItem,
    right: SelectionItem,
    token_threshold: float,
    character_threshold: float,
) -> bool:
    for index in range(len(left.documents)):
        if left.documents[index] and left.documents[index] == right.documents[index]:
            return True
        if jaccard(left.token_documents[index], right.token_documents[index]) >= token_threshold:
            return True
        if (
            jaccard(left.character_documents[index], right.character_documents[index])
            >= character_threshold
        ):
            return True
    return False


def _topic_quotas(items: list[SelectionItem], target: int, taxonomy: Taxonomy) -> dict[str, int]:
    available = Counter(item.topic for item in items)
    active = [intent_id for intent_id in taxonomy.intent_ids if available[intent_id]]
    if target < len(active):
        raise ValueError("Target is too small to preserve topic coverage.")
    quotas = {intent_id: 1 for intent_id in active}
    remaining = target - len(active)
    total_available = sum(available[intent_id] - 1 for intent_id in active)
    fractional = []
    for position, intent_id in enumerate(active):
        capacity = available[intent_id] - 1
        exact = remaining * capacity / total_available if total_available else 0.0
        addition = min(capacity, int(exact))
        quotas[intent_id] += addition
        fractional.append((exact - addition, -position, intent_id))
    unallocated = target - sum(quotas.values())
    for _, _, intent_id in sorted(fractional, reverse=True):
        if not unallocated:
            break
        if quotas[intent_id] < available[intent_id]:
            quotas[intent_id] += 1
            unallocated -= 1
    if unallocated:
        for intent_id in active:
            while unallocated and quotas[intent_id] < available[intent_id]:
                quotas[intent_id] += 1
                unallocated -= 1
    if unallocated:
        raise ValueError("Unable to allocate requested topic quotas.")
    return quotas


def _lexical_distance(item: SelectionItem, selected: list[SelectionItem]) -> float:
    if not selected:
        return 1.0
    return min(
        1.0 - jaccard(item.token_documents[1], other.token_documents[1]) for other in selected
    )


def _select_bucket(
    items: list[SelectionItem],
    target: int,
    taxonomy: Taxonomy,
    seed: str,
    already_selected: list[SelectionItem],
    token_threshold: float,
    character_threshold: float,
) -> list[SelectionItem]:
    quotas = _topic_quotas(items, target, taxonomy)
    by_topic: dict[str, list[SelectionItem]] = defaultdict(list)
    for item in items:
        by_topic[item.topic].append(item)
    selected: list[SelectionItem] = []
    covered_bins: dict[str, set[int]] = defaultdict(set)
    covered_proxies: set[str] = set()
    for topic in taxonomy.intent_ids:
        while len([item for item in selected if item.topic == topic]) < quotas.get(topic, 0):
            eligible = [
                item
                for item in by_topic[topic]
                if item not in selected
                and not any(
                    _duplicates(item, other, token_threshold, character_threshold)
                    for other in already_selected + selected
                )
            ]
            if not eligible:
                raise ValueError(f"Duplicate filtering exhausted topic quota: {topic}")
            ranked = sorted(
                eligible,
                key=lambda item: (
                    -len(set(item.proxies) - covered_proxies),
                    -(item.time_bin not in covered_bins[topic]),
                    -round(_lexical_distance(item, already_selected + selected), 8),
                    deterministic_rank(f"{seed}:{topic}", item.case.case_id),
                ),
            )
            chosen = ranked[0]
            selected.append(chosen)
            covered_bins[topic].add(chosen.time_bin)
            covered_proxies.update(chosen.proxies)
    if len(selected) != target:
        raise ValueError("Frozen selection did not meet the requested bucket count.")
    return selected


def freeze_candidates(
    candidates: list[CandidateCase],
    threads: list[SupportThread],
    taxonomy: Taxonomy,
    config: dict[str, object],
) -> tuple[list[FrozenCandidate], dict[str, object]]:
    """Freeze a diverse 160/40 subset without labels or future model results."""

    if len({case.case_id for case in candidates}) != len(candidates):
        raise ValueError("Source candidate case IDs must be unique.")
    if len({case.thread_id for case in candidates}) != len(candidates):
        raise ValueError("Source candidate thread IDs must be unique.")
    thread_map = {thread.thread_id: thread for thread in threads}
    if any(case.thread_id not in thread_map for case in candidates):
        raise ValueError("Source candidates do not reconcile with the Spotify corpus.")
    representative = [case for case in candidates if case.sampling_bucket == "REPRESENTATIVE"]
    challenge = [case for case in candidates if case.sampling_bucket == "CHALLENGE"]
    time_bins = int(config["time_bins"])
    duplicate_config = config["internal_duplicate_policy"]
    token_threshold = float(duplicate_config["token_jaccard_threshold"])
    character_threshold = float(duplicate_config["character_5gram_jaccard_threshold"])
    representative_items = _items(representative, thread_map, taxonomy, time_bins)
    challenge_items = _items(challenge, thread_map, taxonomy, time_bins)
    selected_representative = _select_bucket(
        representative_items,
        int(config["representative_count"]),
        taxonomy,
        f"{config['seed']}:representative",
        [],
        token_threshold,
        character_threshold,
    )
    selected_challenge = _select_bucket(
        challenge_items,
        int(config["challenge_count"]),
        taxonomy,
        f"{config['seed']}:challenge",
        selected_representative,
        token_threshold,
        character_threshold,
    )
    selected = selected_representative + selected_challenge
    expected = int(config["candidate_count"])
    if len(selected) != expected or len({item.thread.thread_id for item in selected}) != expected:
        raise ValueError("Frozen evaluation selection must contain exactly 200 unique threads.")
    frozen = [
        FrozenCandidate(
            case_id=item.case.case_id,
            thread_id=item.case.thread_id,
            customer_message=sanitize_public_text(item.case.customer_message),
            conversation_context=sanitize_public_text(item.case.conversation_context),
            candidate_type=item.case.sampling_bucket,
            timestamp=item.thread.start_time,
            taxonomy_version=item.case.taxonomy_version,
            split_version=item.case.split_version,
            sampling_version=item.case.sampling_version,
        )
        for item in selected
    ]
    evidence = {
        "selection_method": (
            "Topic-stratified deterministic greedy selection balancing time bins, lexical "
            "distance, and challenge-proxy coverage without model results or labels."
        ),
        "topic_distribution": dict(sorted(Counter(item.topic for item in selected).items())),
        "candidate_type_distribution": dict(
            sorted(Counter(item.case.sampling_bucket for item in selected).items())
        ),
        "time_bin_distribution": dict(
            sorted(Counter(str(item.time_bin) for item in selected).items())
        ),
        "challenge_proxy_distribution": dict(
            sorted(Counter(proxy for item in selected_challenge for proxy in item.proxies).items())
        ),
        "internal_exact_duplicates": 0,
        "internal_near_duplicates": 0,
        "thread_ids_sha256": hashlib.sha256(
            "\n".join(sorted(item.thread.thread_id for item in selected)).encode()
        ).hexdigest(),
    }
    return frozen, evidence
