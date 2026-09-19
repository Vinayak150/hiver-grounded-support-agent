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


_CONTENT_STOPWORDS = {
    "a",
    "about",
    "and",
    "are",
    "at",
    "be",
    "can",
    "do",
    "for",
    "from",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "let",
    "me",
    "more",
    "my",
    "of",
    "on",
    "or",
    "please",
    "spotify",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "us",
    "what",
    "when",
    "which",
    "with",
    "you",
    "your",
}


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z']+", text.casefold())
        if token not in _CONTENT_STOPWORDS and len(token) > 2
    }


def _generic_question(text: str) -> bool:
    normalized = text.casefold()
    return any(
        marker in normalized
        for marker in (
            "what's happening",
            "what is happening",
            "tell us more",
            "give us more detail",
            "give us more info",
            "what you need",
            "how we can assist",
            "what you're looking for",
            "what issues are you having",
            "spotify misbehaving",
        )
    )


def _asks_for_known_context(question: str, customer: str) -> bool:
    question = question.casefold()
    customer = customer.casefold()
    checks = (
        (
            ("device", "phone", "model"),
            ("iphone", "ipad", "android", "samsung", "windows", "mac", "ps4", "playstation", "bmw"),
        ),
        (
            ("operating system", " os", "ios", "android version"),
            ("ios", "android", "windows", "macos"),
        ),
        (
            ("spotify version", "app version", "version are you", "version you're"),
            ("version", "latest", "8."),
        ),
        (("error message", "error messages"), ("error", "no error")),
        (("playlists",), ("playlist", "playlists")),
    )
    return any(
        any(prompt in question for prompt in prompts)
        and any(answer in customer for answer in answers)
        for prompts, answers in checks
    )


def answer_coverage_failure(reply: str, customer: str) -> bool:
    """Detect a generic or redundant question presented as a complete answer."""
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", reply) if item.strip()]
    if not sentences or not all(item.endswith("?") for item in sentences):
        return False
    if any(_asks_for_known_context(item, customer) for item in sentences):
        return True
    customer_specific = len(_content_tokens(customer)) >= 4
    return customer_specific and all(_generic_question(item) for item in sentences)


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

    def _original_compose(self, cases: list[RetrievedCase]) -> str:
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

    def _candidate_sentences(
        self, cases: list[RetrievedCase], customer: str
    ) -> list[tuple[tuple[float, ...], str, str]]:
        candidates: list[tuple[tuple[float, ...], str, str]] = []
        customer_tokens = _content_tokens(customer)
        evidence_limit = int(self.config.get("evidence_case_limit", 2))
        for case_rank, case in enumerate(cases[:evidence_limit]):
            source = sanitize_reply(case.historical_reply)
            for sentence_rank, sentence in enumerate(re.split(r"(?<=[.!?])\s+", source)):
                cleaned = _without_greeting(sentence.strip())
                normalized = cleaned.casefold()
                word_count = len(re.findall(r"[A-Za-z][A-Za-z']+", cleaned))
                if (
                    word_count < 4
                    or not cleaned.isascii()
                    or not re.search(r"[.?!]$", cleaned)
                    or any(marker in normalized for marker in self.blocked)
                    or cleaned.endswith(":")
                    or re.match(r"^(?:and|also|from there|this|that|it)\b", cleaned, re.I)
                ):
                    continue
                is_question = cleaned.endswith("?")
                is_action = any(marker in normalized for marker in self.allowed)
                if not (is_question or is_action):
                    continue
                if is_question and (
                    _asks_for_known_context(cleaned, customer)
                    or (_generic_question(cleaned) and len(customer_tokens) >= 4)
                ):
                    continue
                overlap = len(_content_tokens(cleaned) & customer_tokens)
                # Concrete steps outrank questions; lexical overlap and evidence rank break ties.
                kind = 2.0 if is_action else 1.0
                score = (kind, float(overlap), -float(case_rank), -float(sentence_rank))
                candidates.append((score, cleaned, case.thread_id))
        return sorted(candidates, key=lambda item: item[0], reverse=True)

    def compose_with_evidence(
        self, cases: list[RetrievedCase], customer: str = ""
    ) -> tuple[str, tuple[str, ...]]:
        if self.config.get("mode") != "deterministic_extractive_v41":
            draft = self._original_compose(cases)
            return draft, (cases[0].thread_id,) if draft and cases else ()
        candidates = self._candidate_sentences(cases, customer)
        selected: list[str] = []
        evidence_ids: list[str] = []
        for _, sentence, evidence_id in candidates:
            if sentence in selected:
                continue
            if selected and sentence.endswith("?") == selected[0].endswith("?"):
                continue
            selected.append(sentence)
            evidence_ids.append(evidence_id)
            if len(selected) >= int(self.config["maximum_sentences"]):
                break
        draft = " ".join(selected).strip()
        draft = draft[: int(self.config["maximum_characters"])].rstrip()
        if answer_coverage_failure(draft, customer):
            return "", ()
        return draft, tuple(dict.fromkeys(evidence_ids))

    def compose(self, cases: list[RetrievedCase], customer: str = "") -> str:
        return self.compose_with_evidence(cases, customer)[0]

    @property
    def escalation_reply(self) -> str:
        return str(self.config["safe_escalation_reply"])
