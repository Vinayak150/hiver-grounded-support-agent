from __future__ import annotations

from pathlib import Path

import pytest

from support_agent.agent.evidence import (
    EvidenceThresholds,
    assess_evidence,
    calibrate_thresholds,
)
from support_agent.agent.orchestrator import GroundedSupportAgent
from support_agent.agent.risk import RiskAssessment, assess_risk
from support_agent.agent.schemas import AgentOutput
from support_agent.classification.classifier import IntentClassifier, IntentPrediction
from support_agent.data.protection import assert_no_frozen_thread_ids
from support_agent.data.spotify import SupportThread, Turn
from support_agent.generation.grounded import GroundedComposer, sanitize_reply
from support_agent.generation.verifier import GroundingVerifier
from support_agent.retrieval.hybrid import HybridRetriever, RetrievedCase
from support_agent.taxonomy.schema import load_taxonomy


def thread(identifier: str, customer: str, reply: str = "Please restart the app and try again."):
    return SupportThread(
        thread_id=identifier,
        root_tweet_id=identifier,
        message_count=2,
        customer_message_count=1,
        spotify_message_count=1,
        start_time="2020-01-01T00:00:00+00:00",
        end_time="2020-01-01T00:01:00+00:00",
        participant_count=2,
        turns=(
            Turn("1", "CUSTOMER", customer, "2020-01-01T00:00:00+00:00", None),
            Turn("2", "SPOTIFY", reply, "2020-01-01T00:01:00+00:00", "1"),
        ),
    )


@pytest.fixture
def taxonomy():
    return load_taxonomy(Path("configs/taxonomy.yaml"))


@pytest.fixture
def config():
    import json

    return json.loads(Path("configs/agent.yaml").read_text(encoding="utf-8"))


def classifier_fixture(taxonomy, config):
    samples = []
    texts = (
        "the app keeps crashing during playback every time",
        "offline device connection speaker does not work",
        "my account was hacked and password was changed",
        "premium family subscription plan needs help today",
        "payment charged credit card billing question today",
        "playlist library saved song disappeared from collection",
        "this artist album track metadata is unavailable today",
        "please add a new feature and product improvement",
        "hello there I have a general question about music",
    )
    for repeat in range(2):
        samples.extend(thread(f"train-{repeat}-{index}", text) for index, text in enumerate(texts))
    classifier_config = {**config["classifier"], "minimum_document_frequency": 1}
    return IntentClassifier.fit(samples, taxonomy, classifier_config)


def safe_case(identifier: str = "train-evidence", intent: str = "playback_or_app_behavior"):
    return RetrievedCase(
        thread_id=identifier,
        similarity=0.9,
        historical_reply=(
            f"Please restart the app and try playing the song again. Evidence {identifier}."
        ),
        intent=intent,
        component_scores={"word_similarity": 0.9, "template_penalty": 0.0},
        evidence_score=0.9,
        template_frequency=1,
    )


def thresholds():
    return EvidenceThresholds(0.5, 0.1, 0.5, 0.4, 0.6, 0.6)


def test_classifier_trains_predicts_and_normalizes_probabilities(taxonomy, config):
    classifier = classifier_fixture(taxonomy, config)
    query = thread("query", "the music app crashes whenever I play a song")
    prediction = classifier.predict(query)
    assert prediction.intent in taxonomy.intent_ids
    assert 0 <= prediction.confidence <= 1
    assert classifier.probability_sum(query) == pytest.approx(1.0)
    assert prediction.margin >= 0


def test_retriever_uses_supplied_train_only_and_applies_intent_and_template_signals(
    taxonomy, config
):
    train = [
        thread(
            "train-1", "app crashes while playing", "Restart the app and try playing again please."
        ),
        thread(
            "train-2", "app crashes while playing", "Restart the app and try playing again please."
        ),
        thread(
            "train-3",
            "payment credit card issue",
            "Review the payment method settings and try again.",
        ),
    ]
    retrieval_config = {
        **config["retrieval"],
        "minimum_document_frequency": 1,
        "minimum_reply_words": 3,
    }
    retriever = HybridRetriever.fit(train, taxonomy, retrieval_config)
    results = retriever.retrieve(
        thread("dev", "app crashes while playing now"), "playback_or_app_behavior"
    )
    assert all(case.thread_id.startswith("train-") for case in results)
    assert results[0].component_scores["intent_compatibility"] == 1.0
    assert any(case.component_scores["template_penalty"] > 0 for case in results)
    assert retriever.corpus_stats["excluded_template_cap_excess"] == 0


def test_frozen_ids_are_rejected(tmp_path):
    manifest = tmp_path / "frozen.json"
    manifest.write_text('{"thread_ids": ["frozen-1"]}', encoding="utf-8")
    with pytest.raises(ValueError, match="frozen evaluation"):
        assert_no_frozen_thread_ids({"train-1", "frozen-1"}, manifest, "retrieval")


def test_development_distribution_calibration_and_evidence_gate(config):
    predictions = [
        IntentPrediction(
            "playback_or_app_behavior", 0.6, (("playback_or_app_behavior", 0.6),), 0.2
        ),
        IntentPrediction(
            "playback_or_app_behavior", 0.8, (("playback_or_app_behavior", 0.8),), 0.4
        ),
    ]
    retrievals = [[safe_case("a")], [safe_case("b")]]
    calibrated = calibrate_thresholds(predictions, retrievals, config["calibration"])
    assert 0.35 <= calibrated.intent_confidence <= 0.85
    assessment = assess_evidence(
        predictions[1],
        [safe_case(f"evidence-{index}") for index in range(5)],
        RiskAssessment((), ()),
        thresholds(),
    )
    assert assessment.sufficient


def test_risk_rules_cover_sensitive_low_context_and_ambiguity(config):
    result = assess_risk("My account was hacked and charged a refund", 0.01, config["risk"])
    assert {"SECURITY", "PAYMENT", "REFUND", "ACCOUNT_SPECIFIC", "MULTI_INTENT"} <= set(result.tags)
    assert result.high_risk
    assert "SECURITY_RISK" in result.reason_codes
    inferred = assess_risk(
        "Please explain what happened with this", 0.9, config["risk"], "billing_or_payment"
    )
    assert "PAYMENT_ACTION_REQUIRED" in inferred.reason_codes


def test_sanitizer_composer_and_verifier_are_deterministic(config):
    raw = "Hey Natasha! @person Please restart. See https://example.com; email a@b.com /KT"
    assert "@" not in sanitize_reply(raw)
    assert "http" not in sanitize_reply(raw)
    assert "Natasha" not in sanitize_reply(raw)
    assert "/KT" not in sanitize_reply(raw)
    composer = GroundedComposer(config["generation"], config["verifier"])
    cases = [safe_case()]
    assert composer.compose(cases) == composer.compose(cases)
    broken_link = safe_case("broken")
    broken_link = RetrievedCase(
        **{
            **broken_link.__dict__,
            "historical_reply": "You can try manual verification at <url> Let us know.",
        }
    )
    assert composer.compose([broken_link]) == ""
    verifier = GroundingVerifier(config["verifier"])
    unsafe = verifier.verify(
        "We have refunded @person via https://example.com", cases, (cases[0].thread_id,)
    )
    assert not unsafe.passed
    assert "PII_LEAK" in unsafe.reason_codes
    assert "UNSUPPORTED_ACTION_CLAIM" in unsafe.reason_codes


def test_safe_auto_handle_and_structured_output(config):
    class StubClassifier:
        def predict(self, _thread):
            return IntentPrediction(
                "playback_or_app_behavior",
                0.9,
                (("playback_or_app_behavior", 0.9), ("other_or_unclear", 0.1)),
                0.8,
            )

    class StubRetriever:
        def retrieve(self, _thread, _intent):
            return [safe_case(str(index)) for index in range(5)]

    agent = GroundedSupportAgent(StubClassifier(), StubRetriever(), thresholds(), config)
    query = thread("dev-safe", "the app stops playing music whenever I press the play button")
    first = agent.run_one(query)
    second = agent.run_one(query)
    assert first.action == "AUTO_HANDLE"
    assert first.as_dict() == second.as_dict()
    first.to_prediction().validate()


def test_low_confidence_insufficient_evidence_and_high_risk_escalate(config):
    prediction = IntentPrediction(
        "playback_or_app_behavior", 0.2, (("playback_or_app_behavior", 0.2),), 0.01
    )
    risk = assess_risk(
        "My account was hacked and I need help now", prediction.margin, config["risk"]
    )
    evidence = assess_evidence(prediction, [safe_case()] * 5, risk, thresholds())
    assert not evidence.sufficient
    assert {"LOW_INTENT_CONFIDENCE", "SECURITY_RISK", "AMBIGUOUS_INTENT"} <= set(
        evidence.reason_codes
    )


def test_agent_output_rejects_unsafe_auto_handle():
    output = AgentOutput(
        "case",
        "intent",
        0.8,
        (("intent", 0.8),),
        (),
        "reply",
        "AUTO_HANDLE",
        "reason",
        (),
        (),
        False,
        True,
        None,
        "v1",
    )
    with pytest.raises(ValueError, match="AUTO_HANDLE"):
        output.validate()
