"""Phase 1.5 saturated, audit-focused brand-selection utilities."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

from .profiling import BrandProfile, ProfilingConfig, reply_proxy_flags
from .threads import ThreadIndex


def saturated_corpus_score(multi_turn_threads: int, target: int) -> float:
    """Cap corpus value after a documented sufficient multi-turn threshold."""

    if target <= 0:
        raise ValueError("Saturation target must be positive.")
    return min(1.0, multi_turn_threads / target)


def normalized_entropy(counter: Counter[str]) -> float:
    """Return Shannon entropy normalized to [0, 1], or zero for degenerate text."""

    total = sum(counter.values())
    if total == 0 or len(counter) <= 1:
        return 0.0
    entropy = -sum((count / total) * math.log(count / total) for count in counter.values())
    return entropy / math.log(len(counter))


def deterministic_rank(seed: str, brand: str, category: str, root_id: str) -> str:
    """Stable pseudo-random ordering for audit samples without storing text."""

    return hashlib.sha256(f"{seed}:{brand}:{category}:{root_id}".encode()).hexdigest()


@dataclass(frozen=True)
class AuditSignals:
    brand: str
    corpus_sufficiency: float
    grounding_proxy: float
    low_generic_proxy: float
    anti_template_proxy: float
    topic_entropy_proxy: float
    reconstruction_quality: float
    escalation_learning_proxy: float
    manual_reply_value: float

    def dimensions(self) -> dict[str, float]:
        return {
            "corpus": self.corpus_sufficiency,
            "grounding": self.grounding_proxy,
            "low_generic": self.low_generic_proxy,
            "anti_template": self.anti_template_proxy,
            "topic_diversity": self.topic_entropy_proxy,
            "reconstruction": self.reconstruction_quality,
            "escalation_value": self.escalation_learning_proxy,
            "manual_value": self.manual_reply_value,
        }


def weighted_score(signals: AuditSignals, weights: dict[str, float]) -> float:
    """Compute a declared weighted score and reject incomplete or invalid weights."""

    dimensions = signals.dimensions()
    if set(weights) != set(dimensions):
        raise ValueError("Weight keys must exactly match audit dimensions.")
    if any(value < 0 for value in weights.values()):
        raise ValueError("Audit weights cannot be negative.")
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("Audit weights must sum to 1.0.")
    return sum(dimensions[name] * weights[name] for name in dimensions)


def select_weighted(
    signals: list[AuditSignals], weights: dict[str, float]
) -> tuple[str, dict[str, float]]:
    """Score all candidates and deterministically break exact ties by account name."""

    scores = {item.brand: round(weighted_score(item, weights), 8) for item in signals}
    winner = min(scores, key=lambda brand: (-scores[brand], brand.casefold()))
    return winner, scores


def linked_inbound_rows(index: ThreadIndex, brand: str) -> list[tuple[str, str]]:
    """Return IDs/text for inbound messages directly connected to a brand reply."""

    rows = index.connection.execute(
        """
        WITH linked_inbound AS (
            SELECT customer.tweet_id AS customer_id
            FROM messages AS brand
            JOIN messages AS customer ON customer.parent_id = brand.tweet_id
            WHERE brand.author_id = ? AND brand.inbound = 0 AND customer.inbound = 1
            UNION
            SELECT customer.tweet_id AS customer_id
            FROM messages AS brand
            JOIN messages AS customer ON brand.parent_id = customer.tweet_id
            WHERE brand.author_id = ? AND brand.inbound = 0 AND customer.inbound = 1
        )
        SELECT message.tweet_id, message.normalized_text
        FROM linked_inbound
        JOIN messages AS message ON message.tweet_id = linked_inbound.customer_id
        """,
        (brand, brand),
    ).fetchall()
    return [(str(row["tweet_id"]), str(row["normalized_text"])) for row in rows]


def derive_text_signals(
    rows: list[tuple[str, str]], risk_terms: dict[str, list[str]]
) -> tuple[float, float]:
    """Derive lexical-entropy and risk-surface proxies from linked inbound text."""

    words: Counter[str] = Counter()
    risk_count = 0
    all_terms = tuple(term.casefold() for values in risk_terms.values() for term in values)
    for _, text in rows:
        words.update(re.findall(r"\b[a-z][a-z']{1,}\b", text.casefold()))
        risk_count += any(term in text.casefold() for term in all_terms)
    return round(normalized_entropy(words), 8), round(risk_count / len(rows), 8) if rows else 0.0


def profile_to_signals(
    profile: BrandProfile,
    topic_entropy: float,
    escalation_proxy: float,
    manual_reply_value: float,
    saturation_target: int,
) -> AuditSignals:
    """Map raw Phase 1 values into documented, bounded audit dimensions."""

    return AuditSignals(
        brand=profile.brand,
        corpus_sufficiency=saturated_corpus_score(
            profile.reconstructible_multi_turn_threads, saturation_target
        ),
        grounding_proxy=profile.public_containment_proxy_fraction or 0.0,
        low_generic_proxy=1.0 - (profile.generic_or_redirect_reply_proxy_fraction or 0.0),
        anti_template_proxy=profile.unique_normalized_reply_ratio or 0.0,
        topic_entropy_proxy=topic_entropy,
        reconstruction_quality=profile.outbound_parent_link_completeness or 0.0,
        escalation_learning_proxy=escalation_proxy,
        manual_reply_value=manual_reply_value,
    )


def audit_message_categories(
    index: ThreadIndex, brand: str, config: ProfilingConfig
) -> dict[str, dict[str, str]]:
    """Map candidate roots to a representative brand reply for each audit stratum."""

    multi_turn_roots = {
        str(row["root_id"]): str(row["tweet_id"])
        for row in index.connection.execute(
            """
            WITH sizes AS (SELECT root_id, COUNT(*) AS size FROM root_cache GROUP BY root_id)
            SELECT cache.root_id, MIN(message.tweet_id) AS tweet_id
            FROM messages AS message
            JOIN root_cache AS cache ON cache.tweet_id = message.tweet_id
            JOIN sizes ON sizes.root_id = cache.root_id
            WHERE message.author_id = ? AND message.inbound = 0 AND sizes.size >= 3
            GROUP BY cache.root_id
            """,
            (brand,),
        )
    }
    public_roots: dict[str, str] = {}
    generic_roots: dict[str, str] = {}
    templates: Counter[str] = Counter()
    outbound: list[tuple[str, str, str, int]] = []
    for row in index.connection.execute(
        """
        SELECT message.tweet_id, message.normalized_text, message.word_count, cache.root_id
        FROM messages AS message JOIN root_cache AS cache ON cache.tweet_id = message.tweet_id
        WHERE message.author_id = ? AND message.inbound = 0
        """,
        (brand,),
    ):
        tweet_id, text, words, root_id = (
            str(row["tweet_id"]),
            str(row["normalized_text"]),
            int(row["word_count"]),
            str(row["root_id"]),
        )
        outbound.append((tweet_id, text, root_id, words))
        templates[text] += 1
        _, _, generic, public = reply_proxy_flags(text, words, config)
        if public:
            public_roots.setdefault(root_id, tweet_id)
        if generic:
            generic_roots.setdefault(root_id, tweet_id)
    top_template = min(templates, key=lambda text: (-templates[text], text))
    repeated_roots = {
        root_id: tweet_id for tweet_id, text, root_id, _ in outbound if text == top_template
    }
    return {
        "multi_turn": multi_turn_roots,
        "high_public_containment": public_roots,
        "generic_redirect": generic_roots,
        "repeated_template": repeated_roots,
    }
