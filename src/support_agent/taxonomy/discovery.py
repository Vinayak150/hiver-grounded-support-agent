"""Train-only deterministic TF-IDF exploration for Spotify intent design."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Iterable

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from support_agent.data.spotify import SupportThread

from .schema import Taxonomy


def provisional_intent(text: str, taxonomy: Taxonomy) -> str:
    """Assign an exploratory signal group; this is never a human/gold label."""

    normalized = re.sub(r"\s+", " ", text.casefold())
    scored = []
    for position, intent in enumerate(taxonomy.intents):
        if intent.id == taxonomy.default_intent:
            continue
        score = sum(signal in normalized for signal in intent.common_signals)
        if score:
            scored.append((-score, position, intent.id))
    return min(scored)[2] if scored else taxonomy.default_intent


def _stable_examples(thread_ids: Iterable[str], seed: str, count: int = 5) -> list[str]:
    return sorted(
        thread_ids, key=lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()
    )[:count]


def clean_exploration_text(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", " ", text.casefold())
    text = re.sub(r"@[a-z0-9_]+", " ", text)
    text = re.sub(r"\b\d+\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def explore_taxonomy(
    train_threads: list[SupportThread], taxonomy: Taxonomy, cluster_count: int = 12
) -> dict[str, object]:
    if not train_threads:
        raise ValueError("Taxonomy discovery requires non-empty TRAIN threads.")
    texts = [clean_exploration_text(thread.customer_text()) for thread in train_threads]
    thread_ids = [thread.thread_id for thread in train_threads]
    word_vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        stop_words="english",
        ngram_range=(1, 2),
        min_df=3,
        max_df=0.95,
        max_features=6000,
        sublinear_tf=True,
    )
    matrix = word_vectorizer.fit_transform(texts)
    model = KMeans(
        n_clusters=cluster_count,
        random_state=20260918,
        n_init=10,
        max_iter=100,
    )
    labels = model.fit_predict(matrix)
    distances = model.transform(matrix)
    terms = word_vectorizer.get_feature_names_out()
    clusters = []
    representative_ids = []
    for cluster_id in range(cluster_count):
        members = np.flatnonzero(labels == cluster_id)
        top_term_indexes = model.cluster_centers_[cluster_id].argsort()[::-1][:15]
        representatives = sorted(
            members,
            key=lambda index: (distances[index, cluster_id], thread_ids[index]),
        )[:5]
        ids = [thread_ids[index] for index in representatives]
        representative_ids.extend(ids)
        clusters.append(
            {
                "cluster_id": cluster_id,
                "train_thread_count": int(len(members)),
                "top_terms": [str(terms[index]) for index in top_term_indexes],
                "representative_thread_ids": ids,
            }
        )

    grouped: dict[str, list[str]] = defaultdict(list)
    token_counts: dict[str, Counter[str]] = defaultdict(Counter)
    token_pattern = re.compile(r"[a-z][a-z']+")
    ignored_tokens = set(ENGLISH_STOP_WORDS) | {"spotify", "spotifycares", "https", "co"}
    for thread, text in zip(train_threads, texts, strict=True):
        intent_id = provisional_intent(text, taxonomy)
        grouped[intent_id].append(thread.thread_id)
        token_counts[intent_id].update(
            token for token in token_pattern.findall(text.casefold()) if token not in ignored_tokens
        )
    intent_evidence = []
    for intent in taxonomy.intents:
        top_tokens = [token for token, _ in token_counts[intent.id].most_common(20)]
        intent_evidence.append(
            {
                "id": intent.id,
                "display_name": intent.display_name,
                "train_side_support_count": len(grouped[intent.id]),
                "top_train_tokens": top_tokens,
                "training_example_ids": _stable_examples(
                    grouped[intent.id], f"{taxonomy.version}:{intent.id}"
                ),
            }
        )
    confusion = []
    for left_index, left in enumerate(intent_evidence):
        left_tokens = set(left["top_train_tokens"])
        for right in intent_evidence[left_index + 1 :]:
            right_tokens = set(right["top_train_tokens"])
            union = left_tokens | right_tokens
            confusion.append(
                {
                    "left": left["id"],
                    "right": right["id"],
                    "top_token_jaccard": round(len(left_tokens & right_tokens) / len(union), 6)
                    if union
                    else 0.0,
                }
            )
    return {
        "method": {
            "word_features": "TF-IDF word unigrams+bigrams",
            "clustering": "KMeans",
            "cluster_count": cluster_count,
            "random_state": 20260918,
            "feature_count": int(matrix.shape[1]),
            "rows": int(matrix.shape[0]),
            "interpretation": "aggregate clusters plus deterministic lexical signal groups",
        },
        "clusters": clusters,
        "intent_evidence": intent_evidence,
        "lexical_boundary_overlap": sorted(
            confusion, key=lambda item: (-item["top_token_jaccard"], item["left"], item["right"])
        ),
        "assistance": {
            "used": True,
            "model": "OpenAI Codex GPT-5",
            "role": (
                "Interpreted aggregate train-side cluster terms and drafted provisional "
                "boundaries; did not label examples."
            ),
            "prompt_summary": (
                "Create a compact operational taxonomy from TRAIN-only aggregate TF-IDF "
                "clusters and ID-only representatives."
            ),
            "representative_thread_ids": sorted(set(representative_ids)),
        },
    }
