"""Transparent hybrid retrieval over TRAIN historical support exchanges."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from support_agent.annotation.queue import sanitize_public_text
from support_agent.baselines.lexical import first_spotify_reply, usable_public_reply
from support_agent.data.schema import normalized_reply, word_count
from support_agent.data.spotify import SupportThread
from support_agent.taxonomy.discovery import clean_exploration_text, provisional_intent
from support_agent.taxonomy.schema import Taxonomy


@dataclass(frozen=True)
class RetrievalDocument:
    thread_id: str
    customer_text: str
    reply: str
    intent: str
    reply_quality: float
    context_compatibility: float
    template_frequency: int


@dataclass(frozen=True)
class RetrievedCase:
    thread_id: str
    similarity: float
    historical_reply: str
    intent: str
    component_scores: dict[str, float]
    evidence_score: float
    template_frequency: int

    def as_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "similarity": self.similarity,
            "historical_reply": self.historical_reply,
            "intent": self.intent,
            "component_scores": self.component_scores,
            "evidence_score": self.evidence_score,
        }


def _reply_quality(reply: str) -> float:
    words = word_count(reply)
    length_score = min(words / 24.0, 1.0)
    noise_penalty = 0.25 if re.search(r"<(?:url|email|mention|number)>", reply) else 0.0
    return max(0.0, min(1.0, length_score - noise_penalty))


class HybridRetriever:
    def __init__(
        self, documents, word_vectorizer, char_vectorizer, word_matrix, char_matrix, config, stats
    ):
        self.documents = documents
        self.word_vectorizer = word_vectorizer
        self.char_vectorizer = char_vectorizer
        self.word_matrix = word_matrix
        self.char_matrix = char_matrix
        self.config = config
        self.corpus_stats = stats

    @classmethod
    def fit(cls, threads: list[SupportThread], taxonomy: Taxonomy, config: dict[str, object]):
        raw = []
        template_counts: Counter[str] = Counter()
        unusable = 0
        for thread in sorted(threads, key=lambda item: item.thread_id):
            reply = first_spotify_reply(thread)
            if not usable_public_reply(reply, config):
                unusable += 1
                continue
            cleaned = sanitize_public_text(reply)
            template = normalized_reply(cleaned)
            template_counts[template] += 1
            raw.append((thread, cleaned, template))
        cap = int(config["maximum_exact_reply_template_occurrences"])
        kept_counts: Counter[str] = Counter()
        documents = []
        template_excess = 0
        for thread, reply, template in raw:
            if kept_counts[template] >= cap:
                template_excess += 1
                continue
            kept_counts[template] += 1
            documents.append(
                RetrievalDocument(
                    thread_id=thread.thread_id,
                    customer_text=clean_exploration_text(thread.customer_text()),
                    reply=reply,
                    intent=provisional_intent(thread.customer_text(), taxonomy),
                    reply_quality=_reply_quality(reply),
                    context_compatibility=min(thread.message_count / 4.0, 1.0),
                    template_frequency=template_counts[template],
                )
            )
        if not documents:
            raise ValueError("TRAIN retrieval corpus is empty after filtering.")
        kwargs = {
            "strip_accents": "unicode",
            "min_df": int(config["minimum_document_frequency"]),
            "sublinear_tf": True,
        }
        word = TfidfVectorizer(
            ngram_range=tuple(config["word_ngram_range"]),
            max_features=int(config["word_max_features"]),
            **kwargs,
        )
        char = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=tuple(config["character_ngram_range"]),
            max_features=int(config["character_max_features"]),
            **kwargs,
        )
        texts = [item.customer_text for item in documents]
        word_matrix = normalize(word.fit_transform(texts).tocsr(), copy=False)
        char_matrix = normalize(char.fit_transform(texts).tocsr(), copy=False)
        stats = {
            "input_train_threads": len(threads),
            "excluded_unusable_public_reply": unusable,
            "excluded_template_cap_excess": template_excess,
            "retrieval_corpus_threads": len(documents),
            "unique_normalized_reply_templates": len(template_counts),
        }
        return cls(documents, word, char, word_matrix, char_matrix, config, stats)

    def retrieve_many(
        self, threads: list[SupportThread], intents: list[str]
    ) -> list[list[RetrievedCase]]:
        if len(threads) != len(intents):
            raise ValueError("Every retrieval query requires a predicted intent.")
        texts = [clean_exploration_text(thread.customer_text()) for thread in threads]
        word_queries = normalize(self.word_vectorizer.transform(texts).tocsr(), copy=False)
        char_queries = normalize(self.char_vectorizer.transform(texts).tocsr(), copy=False)
        output = []
        for query_index, (thread, predicted_intent) in enumerate(
            zip(threads, intents, strict=True)
        ):
            word_scores = (word_queries[query_index] @ self.word_matrix.T).toarray()[0]
            char_scores = (char_queries[query_index] @ self.char_matrix.T).toarray()[0]
            pool_size = min(int(self.config["candidate_pool"]), len(self.documents))
            combined = word_scores + char_scores
            pool = np.argpartition(combined, -pool_size)[-pool_size:]
            weights = self.config["weights"]
            query_context = min(thread.message_count / 4.0, 1.0)
            ranked = []
            for index in pool.tolist():
                document = self.documents[index]
                intent_score = 1.0 if document.intent == predicted_intent else 0.0
                context_score = 1.0 - abs(query_context - document.context_compatibility)
                frequency_penalty = min((document.template_frequency - 1) / 9.0, 1.0)
                components = {
                    "word_similarity": float(word_scores[index]),
                    "character_similarity": float(char_scores[index]),
                    "intent_compatibility": intent_score,
                    "reply_quality": document.reply_quality,
                    "context_compatibility": context_score,
                    "template_penalty": frequency_penalty,
                }
                score = (
                    sum(
                        float(weights[name]) * value
                        for name, value in components.items()
                        if name != "template_penalty"
                    )
                    - float(weights["template_penalty"]) * frequency_penalty
                )
                ranked.append((max(0.0, min(score, 1.0)), index, components))
            ranked.sort(key=lambda item: (-item[0], self.documents[item[1]].thread_id))
            cases = []
            for score, index, components in ranked[: int(self.config["top_k"])]:
                document = self.documents[index]
                cases.append(
                    RetrievedCase(
                        thread_id=document.thread_id,
                        similarity=round(
                            (components["word_similarity"] + components["character_similarity"])
                            / 2,
                            8,
                        ),
                        historical_reply=document.reply,
                        intent=document.intent,
                        component_scores={
                            key: round(value, 8) for key, value in components.items()
                        },
                        evidence_score=round(score, 8),
                        template_frequency=document.template_frequency,
                    )
                )
            output.append(cases)
        return output

    def retrieve(self, thread: SupportThread, intent: str) -> list[RetrievedCase]:
        return self.retrieve_many([thread], [intent])[0]
