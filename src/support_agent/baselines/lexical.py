"""Interpretable TRAIN-only word/character TF-IDF neighbor baseline."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.preprocessing import normalize

from support_agent.annotation.queue import sanitize_public_text
from support_agent.data.schema import normalized_reply, word_count
from support_agent.data.spotify import SupportThread
from support_agent.evaluation.schemas import Prediction
from support_agent.taxonomy.discovery import clean_exploration_text, provisional_intent
from support_agent.taxonomy.schema import Taxonomy


@dataclass(frozen=True)
class RetrievalRecord:
    thread_id: str
    customer_text: str
    reply: str
    weak_intent: str


@dataclass(frozen=True)
class Neighbor:
    record: RetrievalRecord
    score: float


@dataclass(frozen=True)
class CalibrationResult:
    threshold: float
    requested_quantile: float
    raw_quantile: float
    minimum: float
    maximum: float
    development_count: int


def first_spotify_reply(thread: SupportThread) -> str:
    return next((turn.text for turn in thread.turns if turn.author_role == "SPOTIFY"), "")


def usable_public_reply(reply: str, config: dict[str, object]) -> bool:
    normalized = normalized_reply(reply)
    if word_count(normalized) < int(config["minimum_reply_words"]):
        return False
    return not any(marker in normalized for marker in config["private_reply_markers"])


def query_has_risk(text: str, config: dict[str, object]) -> bool:
    normalized = normalized_reply(text)
    return any(marker in normalized for marker in config["query_risk_markers"])


def build_retrieval_records(
    threads: list[SupportThread], taxonomy: Taxonomy, config: dict[str, object]
) -> tuple[list[RetrievalRecord], dict[str, int]]:
    """Filter unusable replies and cap exact normalized reply templates."""

    template_counts: Counter[str] = Counter()
    records = []
    unusable = 0
    template_excess = 0
    maximum = int(config["maximum_exact_reply_template_occurrences"])
    for thread in sorted(threads, key=lambda item: item.thread_id):
        reply = first_spotify_reply(thread)
        if not usable_public_reply(reply, config):
            unusable += 1
            continue
        template = normalized_reply(reply)
        if template_counts[template] >= maximum:
            template_excess += 1
            continue
        template_counts[template] += 1
        records.append(
            RetrievalRecord(
                thread_id=thread.thread_id,
                customer_text=clean_exploration_text(thread.customer_text()),
                reply=sanitize_public_text(reply),
                weak_intent=provisional_intent(thread.customer_text(), taxonomy),
            )
        )
    if not records:
        raise ValueError("TRAIN retrieval corpus is empty after public-reply filtering.")
    return records, {
        "input_train_threads": len(threads),
        "excluded_unusable_public_reply": unusable,
        "excluded_template_cap_excess": template_excess,
        "retrieval_corpus_threads": len(records),
        "unique_normalized_reply_templates": len(template_counts),
    }


def calibrate_similarity_threshold(
    top_scores: list[float], config: dict[str, object]
) -> CalibrationResult:
    if not top_scores:
        raise ValueError("Development similarities are required for heuristic calibration.")
    quantile = float(config["development_similarity_quantile"])
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("Development similarity quantile must be between zero and one.")
    minimum = float(config["similarity_threshold_floor"])
    maximum = float(config["similarity_threshold_ceiling"])
    if not 0.0 <= minimum <= maximum <= 1.0:
        raise ValueError("Similarity threshold bounds must be ordered within [0, 1].")
    raw = float(np.quantile(np.asarray(top_scores, dtype=float), quantile))
    threshold = round(min(max(raw, minimum), maximum), 6)
    return CalibrationResult(
        threshold=threshold,
        requested_quantile=quantile,
        raw_quantile=round(raw, 6),
        minimum=minimum,
        maximum=maximum,
        development_count=len(top_scores),
    )


class LexicalBaseline:
    def __init__(
        self,
        records: list[RetrievalRecord],
        features: FeatureUnion,
        matrix: object,
        config: dict[str, object],
        corpus_stats: dict[str, int],
    ) -> None:
        self.records = records
        self.features = features
        self.matrix = matrix
        self.config = config
        self.corpus_stats = corpus_stats

    @classmethod
    def fit(
        cls,
        train_threads: list[SupportThread],
        taxonomy: Taxonomy,
        config: dict[str, object],
    ) -> "LexicalBaseline":
        records, corpus_stats = build_retrieval_records(train_threads, taxonomy, config)
        features = FeatureUnion(
            [
                (
                    "word",
                    TfidfVectorizer(
                        lowercase=True,
                        strip_accents="unicode",
                        ngram_range=tuple(config["word_ngram_range"]),
                        min_df=int(config["minimum_document_frequency"]),
                        max_features=int(config["word_max_features"]),
                        sublinear_tf=True,
                    ),
                ),
                (
                    "character",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        lowercase=True,
                        ngram_range=tuple(config["character_ngram_range"]),
                        min_df=int(config["minimum_document_frequency"]),
                        max_features=int(config["character_max_features"]),
                        sublinear_tf=True,
                    ),
                ),
            ],
            transformer_weights={
                "word": float(config["word_weight"]),
                "character": float(config["character_weight"]),
            },
        )
        matrix = features.fit_transform([record.customer_text for record in records]).tocsr()
        normalize(matrix, norm="l2", copy=False)
        return cls(records, features, matrix, config, corpus_stats)

    def retrieve_many(
        self, threads: list[SupportThread], batch_size: int = 128
    ) -> list[list[Neighbor]]:
        texts = [clean_exploration_text(thread.customer_text()) for thread in threads]
        query_matrix = self.features.transform(texts).tocsr()
        normalize(query_matrix, norm="l2", copy=False)
        top_k = int(self.config["top_k"])
        results: list[list[Neighbor]] = []
        for start in range(0, len(threads), batch_size):
            similarities = (query_matrix[start : start + batch_size] @ self.matrix.T).tocsr()
            for row_index in range(similarities.shape[0]):
                row = similarities.getrow(row_index)
                nonzero = list(zip(row.indices.tolist(), row.data.tolist(), strict=True))
                ranked = sorted(
                    nonzero,
                    key=lambda item: (-float(item[1]), self.records[int(item[0])].thread_id),
                )
                used = {int(index) for index, _ in ranked[:top_k]}
                if len(ranked) < top_k:
                    for index in range(len(self.records)):
                        if index not in used:
                            ranked.append((index, 0.0))
                            used.add(index)
                        if len(ranked) >= top_k:
                            break
                results.append(
                    [
                        Neighbor(self.records[int(index)], round(float(score), 8))
                        for index, score in ranked[:top_k]
                    ]
                )
        return results

    def predict(
        self,
        thread: SupportThread,
        neighbors: list[Neighbor],
        calibration: CalibrationResult,
    ) -> Prediction:
        if not neighbors:
            raise ValueError("Lexical baseline requires at least one retrieved neighbor.")
        nearest = neighbors[0]
        risky = query_has_risk(thread.customer_text(), self.config)
        auto_handle = nearest.score >= calibration.threshold and not risky
        action = "AUTO_HANDLE" if auto_handle else "ESCALATE"
        reason = (
            "Development-calibrated similarity met the threshold and the query passed "
            "the conservative public-handling risk screen."
            if auto_handle
            else "Similarity was below the heuristic threshold or the request triggered "
            "a conservative private/sensitive risk marker."
        )
        reply = (
            nearest.record.reply
            if auto_handle
            else str(self.config["safe_escalation_reply"])
        )
        return Prediction(
            case_id=thread.thread_id,
            system_name=str(self.config["system_name"]),
            intent=nearest.record.weak_intent,
            intent_confidence=nearest.score,
            action=action,
            action_reason=reason,
            reply=reply,
            retrieved_thread_ids=tuple(neighbor.record.thread_id for neighbor in neighbors),
            retrieval_scores=tuple(neighbor.score for neighbor in neighbors),
            evidence_ids=(nearest.record.thread_id,) if auto_handle else (),
            metadata={
                "intent_source": "TRAIN-side provisional taxonomy group of top neighbor",
                "human_label_source": False,
                "similarity_threshold": calibration.threshold,
                "risk_screen_triggered": risky,
            },
        )
