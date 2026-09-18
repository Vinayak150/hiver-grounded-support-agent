"""Deliberately trivial fixed-intent, always-escalate baseline."""

from __future__ import annotations

from support_agent.data.spotify import SupportThread
from support_agent.evaluation.schemas import Prediction


class FixedBaseline:
    def __init__(self, config: dict[str, object]) -> None:
        self.system_name = str(config["system_name"])
        self.intent = str(config["intent"])
        self.intent_source = str(config["intent_source"])
        self.reply = str(config["reply"])

    def predict(self, thread: SupportThread) -> Prediction:
        return Prediction(
            case_id=thread.thread_id,
            system_name=self.system_name,
            intent=self.intent,
            intent_confidence=None,
            action="ESCALATE",
            action_reason=(
                "Fixed safe baseline always escalates; it does not claim to resolve the request."
            ),
            reply=self.reply,
            metadata={
                "baseline_kind": "FIXED_INTENT",
                "intent_source": self.intent_source,
                "human_label_source": False,
            },
        )
