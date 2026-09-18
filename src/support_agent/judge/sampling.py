"""Stable stratified DEVELOPMENT sampling for judge diagnostics."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from support_agent.data.spotify import SupportThread


def stable_rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def challenge_flags(text: str) -> tuple[str, ...]:
    normalized = text.casefold()
    tokens = re.findall(r"[a-z][a-z']+", normalized)
    flags = []
    if len(tokens) <= 5:
        flags.append("VERY_SHORT")
    if len(tokens) >= 60:
        flags.append("UNUSUALLY_LONG")
    if normalized.count("?") >= 2 or sum(normalized.count(x) for x in (" and ", " but ")) >= 2:
        flags.append("MULTI_CLAUSE")
    if any(term in normalized for term in ("hacked", "password", "charged", "refund", "payment")):
        flags.append("RISK_TERMS")
    if sum(term in normalized for term in ("iphone", "android", "windows", "mac", "speaker")) >= 2:
        flags.append("MULTI_DEVICE")
    return tuple(flags)


def build_development_sample(
    proposed: list[dict[str, object]],
    thread_map: dict[str, SupportThread],
    *,
    sample_size: int,
    seed: str,
) -> list[dict[str, object]]:
    if sample_size > len(proposed):
        raise ValueError("Judge sample cannot exceed DEVELOPMENT predictions.")
    automatic = [item for item in proposed if item["action"] == "AUTO_HANDLE"]
    if len(automatic) > sample_size:
        raise ValueError("Sample is too small to include all proposed AUTO_HANDLE cases.")
    selected = sorted(automatic, key=lambda item: stable_rank(seed, str(item["case_id"])))
    used = {str(item["case_id"]) for item in selected}
    strata: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in proposed:
        case_id = str(item["case_id"])
        if case_id in used:
            continue
        flags = challenge_flags(thread_map[case_id].customer_text())
        key = "|".join(
            (
                str(item["intent"]),
                f"evidence={bool(item['evidence_sufficient'])}",
                f"risk={bool(item['risk_tags'])}",
                f"challenge={','.join(flags) if flags else 'NONE'}",
            )
        )
        strata[key].append(item)
    for key, values in strata.items():
        values.sort(key=lambda item: stable_rank(f"{seed}:{key}", str(item["case_id"])))
    while len(selected) < sample_size:
        added = False
        for key in sorted(strata):
            if strata[key] and len(selected) < sample_size:
                selected.append(strata[key].pop(0))
                added = True
        if not added:
            raise ValueError("Could not fill requested DEVELOPMENT judge sample.")
    records = []
    for item in sorted(selected, key=lambda value: str(value["case_id"])):
        case_id = str(item["case_id"])
        flags = challenge_flags(thread_map[case_id].customer_text())
        records.append(
            {
                "case_id": case_id,
                "proposed_action": item["action"],
                "proposed_intent": item["intent"],
                "evidence_sufficient": item["evidence_sufficient"],
                "has_risk_tags": bool(item["risk_tags"]),
                "challenge_flags": list(flags),
                "sampling_rank": stable_rank(seed, case_id),
            }
        )
    return records
