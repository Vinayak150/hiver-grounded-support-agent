"""Interpretable word/character TF-IDF intent classifier."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion

from support_agent.data.spotify import SupportThread
from support_agent.taxonomy.discovery import clean_exploration_text, provisional_intent
from support_agent.taxonomy.schema import Taxonomy


@dataclass(frozen=True)
class IntentPrediction:
    intent: str
    confidence: float
    alternatives: tuple[tuple[str, float], ...]
    margin: float


class IntentClassifier:
    """Linear classifier trained only on TRAIN-side exploratory weak labels."""

    def __init__(self, features: FeatureUnion, model: LogisticRegression) -> None:
        self.features = features
        self.model = model

    @classmethod
    def fit(
        cls,
        threads: list[SupportThread],
        taxonomy: Taxonomy,
        config: dict[str, object],
    ) -> "IntentClassifier":
        if not threads:
            raise ValueError("Intent classifier requires TRAIN examples.")
        texts = [clean_exploration_text(thread.customer_text()) for thread in threads]
        labels = [provisional_intent(thread.customer_text(), taxonomy) for thread in threads]
        if len(set(labels)) < 2:
            raise ValueError("Intent classifier requires at least two weak-label classes.")
        features = FeatureUnion(
            [
                (
                    "word",
                    TfidfVectorizer(
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
        matrix = features.fit_transform(texts)
        model = LogisticRegression(
            C=float(config["regularization_c"]),
            class_weight=str(config["class_weight"]),
            max_iter=int(config["maximum_iterations"]),
            random_state=int(config["random_state"]),
        )
        model.fit(matrix, labels)
        return cls(features, model)

    def predict_many(self, threads: list[SupportThread]) -> list[IntentPrediction]:
        texts = [clean_exploration_text(thread.customer_text()) for thread in threads]
        probabilities = self.model.predict_proba(self.features.transform(texts))
        classes = [str(value) for value in self.model.classes_]
        output = []
        for row in probabilities:
            ranked = sorted(
                zip(classes, row.tolist(), strict=True), key=lambda item: (-item[1], item[0])
            )
            margin = ranked[0][1] - ranked[1][1] if len(ranked) > 1 else ranked[0][1]
            output.append(
                IntentPrediction(
                    intent=ranked[0][0],
                    confidence=round(float(ranked[0][1]), 8),
                    alternatives=tuple(
                        (name, round(float(score), 8)) for name, score in ranked[:3]
                    ),
                    margin=round(float(margin), 8),
                )
            )
        return output

    def predict(self, thread: SupportThread) -> IntentPrediction:
        return self.predict_many([thread])[0]

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.model.classes_)

    def probability_sum(self, thread: SupportThread) -> float:
        matrix = self.features.transform([clean_exploration_text(thread.customer_text())])
        return float(np.sum(self.model.predict_proba(matrix)[0]))
