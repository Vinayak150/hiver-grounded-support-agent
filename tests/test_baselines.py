from __future__ import annotations

import json
from pathlib import Path

import pytest

from support_agent.baselines.fixed import FixedBaseline
from support_agent.baselines.lexical import (
    LexicalBaseline,
    build_retrieval_records,
    calibrate_similarity_threshold,
)
from support_agent.data.spotify import SupportThread, Turn
from support_agent.evaluation.schemas import Prediction
from support_agent.taxonomy.schema import validate_taxonomy

ROOT = Path(__file__).resolve().parents[1]


def _thread(thread_id: str, customer: str, reply: str) -> SupportThread:
    timestamp = "2017-01-01T00:00:00+00:00"
    turns = (
        Turn(f"{thread_id}-1", "CUSTOMER", customer, timestamp, None),
        Turn(f"{thread_id}-2", "SPOTIFY", reply, timestamp, f"{thread_id}-1"),
    )
    return SupportThread(thread_id, thread_id, 2, 1, 1, timestamp, timestamp, 2, turns)


def _taxonomy():
    return validate_taxonomy(
        {
            "version": "test-v1",
            "brand": "SpotifyCares",
            "source_split": "TRAIN",
            "default_intent": "other",
            "intents": [
                {
                    "id": "playback",
                    "display_name": "Playback",
                    "definition": "Playback failures",
                    "include_when": "Playback is central",
                    "exclude_when": "Account access is central",
                    "boundary_notes": "Prefer account for access",
                    "common_signals": ["play", "song"],
                },
                {
                    "id": "account",
                    "display_name": "Account",
                    "definition": "Account access",
                    "include_when": "Login is central",
                    "exclude_when": "Playback is central",
                    "boundary_notes": "Prefer playback for playback",
                    "common_signals": ["login", "password"],
                },
                {
                    "id": "other",
                    "display_name": "Other",
                    "definition": "Unclear",
                    "include_when": "Nothing is clear",
                    "exclude_when": "A specific intent is clear",
                    "boundary_notes": "Preserve abstention",
                    "common_signals": [],
                },
            ],
        }
    )


def _lexical_config() -> dict[str, object]:
    return {
        "system_name": "test-lexical",
        "word_ngram_range": [1, 2],
        "character_ngram_range": [3, 5],
        "word_weight": 0.6,
        "character_weight": 0.4,
        "word_max_features": 1000,
        "character_max_features": 1000,
        "minimum_document_frequency": 1,
        "top_k": 2,
        "minimum_reply_words": 3,
        "maximum_exact_reply_template_occurrences": 1,
        "development_similarity_quantile": 0.75,
        "similarity_threshold_floor": 0.0,
        "similarity_threshold_ceiling": 1.0,
        "private_reply_markers": ["dm us"],
        "query_risk_markers": ["password", "charged"],
        "safe_escalation_reply": "A specialist should review this request.",
    }


def test_fixed_baseline_is_transparent_and_always_escalates() -> None:
    baseline = FixedBaseline(
        {
            "system_name": "fixed",
            "intent": "playback",
            "intent_source": "TRAIN weak group",
            "reply": "A specialist should review this request.",
        }
    )
    prediction = baseline.predict(_thread("dev", "help", "public response words here"))
    assert prediction.intent == "playback"
    assert prediction.action == "ESCALATE"
    assert prediction.retrieved_thread_ids == ()
    assert prediction.metadata["human_label_source"] is False


def test_retrieval_corpus_filters_private_replies_and_caps_templates() -> None:
    repeated = "Please restart the app and try playing the song again now."
    threads = [
        _thread("a", "song cannot play", repeated),
        _thread("b", "track cannot play", repeated),
        _thread("c", "cannot login", "Please DM us your username so we can check."),
    ]
    records, stats = build_retrieval_records(threads, _taxonomy(), _lexical_config())
    assert [record.thread_id for record in records] == ["a"]
    assert stats["excluded_template_cap_excess"] == 1
    assert stats["excluded_unusable_public_reply"] == 1


def test_lexical_neighbor_and_risk_screen_are_deterministic() -> None:
    train = [
        _thread("a", "song cannot play", "Please restart the app and try the song again."),
        _thread("b", "cannot login password", "Try resetting the app before signing in again."),
        _thread("c", "playlist song missing", "Please refresh the playlist and check it again."),
    ]
    config = _lexical_config()
    baseline = LexicalBaseline.fit(train, _taxonomy(), config)
    safe_query = _thread("dev-a", "song will not play", "unused reply words here")
    risky_query = _thread("dev-b", "password login problem", "unused reply words here")
    first = baseline.retrieve_many([safe_query, risky_query])
    second = baseline.retrieve_many([safe_query, risky_query])
    assert first == second
    assert first[0][0].record.thread_id == "a"
    calibration = calibrate_similarity_threshold([0.1, 0.2, 0.3, 0.4], config)
    assert calibration.threshold == 0.325
    safe_prediction = baseline.predict(safe_query, first[0], calibration)
    assert safe_prediction.action == "AUTO_HANDLE"
    risky_prediction = baseline.predict(risky_query, first[1], calibration)
    assert risky_prediction.action == "ESCALATE"


def test_prediction_schema_rejects_misaligned_retrieval_fields() -> None:
    prediction = Prediction(
        case_id="case",
        system_name="system",
        intent="playback",
        action="ESCALATE",
        action_reason="Safety handoff",
        reply="A specialist should review this request.",
        retrieved_thread_ids=("a",),
        retrieval_scores=(),
    )
    with pytest.raises(ValueError, match="matching lengths"):
        prediction.validate()


def test_committed_development_artifacts_never_target_frozen_cases() -> None:
    manifest_path = ROOT / "results/dev_baseline_manifest.json"
    if not manifest_path.exists():
        pytest.skip("Development artifacts are generated after unit implementation.")
    manifest = json.loads(manifest_path.read_text())
    frozen = json.loads(
        (ROOT / "data/manifests/final_golden_candidate_manifest.json").read_text()
    )
    splits = json.loads((ROOT / "data/manifests/split_manifest.json").read_text())["thread_ids"]
    frozen_ids = set(frozen["thread_ids"])
    train_ids = set(splits["TRAIN"])
    development_ids = set(splits["DEVELOPMENT"])
    for name in ("dev_baseline_fixed.jsonl", "dev_baseline_lexical.jsonl"):
        rows = [json.loads(line) for line in (ROOT / "results" / name).read_text().splitlines()]
        assert len(rows) == 2594
        assert {row["case_id"] for row in rows} == development_ids
        assert not {row["case_id"] for row in rows} & frozen_ids
        assert all(
            set(row["retrieved_thread_ids"]) <= train_ids
            for row in rows
        )
    assert manifest["prediction_split"] == "DEVELOPMENT"
    assert manifest["frozen_evaluation_predictions_generated"] is False
    assert manifest["human_gold_labels_used"] == 0
    assert manifest["ai_provisional_labels_used_as_gold"] is False
