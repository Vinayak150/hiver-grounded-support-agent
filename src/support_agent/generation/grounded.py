"""Deterministic, extractive, evidence-preserving reply composition."""

from __future__ import annotations

import html
import re

from support_agent.retrieval.hybrid import RetrievedCase


def sanitize_reply(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"https?://\S+|www\.\S+|<(?:url|email|mention|number)>", " ", text)
    text = re.sub(r"@[A-Za-z0-9_]+", " ", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", " ", text)
    text = re.sub(r"\b\d{7,}\b", " ", text)
    text = re.sub(r"(?:^|\s)/[A-Z]{1,3}(?=\s|$|[.!?])", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    text = re.sub(r"^(Hey|Hi|Hello)\s+[A-Z][a-z]{1,24}([!.])", r"\1\2", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" -")


def _without_greeting(sentence: str) -> str:
    return re.sub(r"^(?:hey|hi|hello)(?: there)?[,.!]*\s*", "", sentence, flags=re.I).strip()


class GroundedComposer:
    def __init__(self, config: dict[str, object], verifier_config: dict[str, object]) -> None:
        self.config = config
        self.blocked = tuple(
            str(value).casefold()
            for key in (
                "unsupported_action_markers",
                "private_inspection_markers",
                "payment_promise_markers",
                "policy_claim_markers",
            )
            for value in verifier_config[key]
        ) + tuple(str(value).casefold() for value in config["blocked_noisy_markers"])
        self.allowed = tuple(str(value).casefold() for value in config["allowed_response_markers"])

    def compose(self, cases: list[RetrievedCase]) -> str:
        if not cases:
            return ""
        source = sanitize_reply(cases[0].historical_reply)
        sentences = re.split(r"(?<=[.!?])\s+", source)
        usable = []
        for sentence in sentences:
            cleaned = _without_greeting(sentence.strip())
            if (
                len(re.findall(r"[A-Za-z][A-Za-z']+", cleaned)) >= 4
                and not any(marker in cleaned.casefold() for marker in self.blocked)
                and not cleaned.endswith(":")
                and not (" at " in cleaned.casefold() and not cleaned.endswith("?"))
                and (
                    cleaned.endswith("?")
                    or any(marker in cleaned.casefold() for marker in self.allowed)
                )
            ):
                usable.append(cleaned)
        draft = " ".join(usable[: int(self.config["maximum_sentences"])]).strip()
        return draft[: int(self.config["maximum_characters"])].rstrip()

    @property
    def escalation_reply(self) -> str:
        return str(self.config["safe_escalation_reply"])
