"""Schema validation and narrowly scoped parsing for TWCS-style CSV files."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


class SchemaValidationError(ValueError):
    """Raised when a CSV cannot supply the information Phase 1 requires."""


_ALIASES: dict[str, tuple[str, ...]] = {
    "tweet_id": ("tweet_id", "message_id", "id"),
    "author_id": ("author_id", "author", "account_id", "user_id"),
    "inbound": ("inbound", "is_inbound", "is_customer"),
    "created_at": ("created_at", "timestamp", "created"),
    "text": ("text", "message", "tweet_text"),
    "in_response_to_tweet_id": (
        "in_response_to_tweet_id",
        "in_response_to_id",
        "parent_tweet_id",
        "parent_id",
    ),
    "response_tweet_id": ("response_tweet_id", "response_tweet_ids", "child_tweet_id"),
}
_REQUIRED = ("tweet_id", "author_id", "inbound", "text")
_ID_RE = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class ResolvedSchema:
    """Actual header names selected for each logical TWCS field."""

    columns: dict[str, str]
    input_columns: tuple[str, ...]

    @property
    def parent_column(self) -> str | None:
        return self.columns.get("in_response_to_tweet_id")

    @property
    def child_column(self) -> str | None:
        return self.columns.get("response_tweet_id")


@dataclass(frozen=True)
class ParsedIds:
    """Valid numeric identifiers plus malformed non-empty tokens."""

    values: tuple[str, ...]
    malformed: tuple[str, ...]


def resolve_schema(header: Iterable[str | None]) -> ResolvedSchema:
    """Resolve a TWCS-style header and require at least one lineage direction."""

    input_columns = tuple(column.strip() for column in header if column is not None)
    normalized = {column.casefold(): column for column in input_columns}
    resolved: dict[str, str] = {}
    for logical_name, aliases in _ALIASES.items():
        match = next((normalized[alias] for alias in aliases if alias in normalized), None)
        if match is not None:
            resolved[logical_name] = match

    missing = [field for field in _REQUIRED if field not in resolved]
    if missing:
        raise SchemaValidationError(
            "Missing required TWCS concepts: "
            + ", ".join(missing)
            + ". Found columns: "
            + ", ".join(input_columns)
        )
    if not {"in_response_to_tweet_id", "response_tweet_id"}.intersection(resolved):
        raise SchemaValidationError(
            "Missing reply lineage. Expected an in_response_to_tweet_id-style parent column "
            "or a response_tweet_id-style child column."
        )
    return ResolvedSchema(columns=resolved, input_columns=input_columns)


def parse_inbound(value: object) -> bool | None:
    """Parse common boolean encodings; blank values are missing, not false."""

    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if normalized == "":
        return None
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    return None


def parse_id_list(value: object) -> ParsedIds:
    """Parse scalar, comma-separated, or JSON-list tweet identifiers deterministically."""

    if value is None:
        return ParsedIds((), ())
    raw = str(value).strip()
    if not raw or raw.casefold() in {"nan", "none", "null"}:
        return ParsedIds((), ())

    tokens: list[str]
    if raw.startswith("[") and raw.endswith("]"):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            tokens = [part.strip() for part in raw[1:-1].split(",")]
        else:
            tokens = [str(item).strip() for item in decoded] if isinstance(decoded, list) else [raw]
    else:
        tokens = [part.strip() for part in raw.split(",")]

    values: list[str] = []
    malformed: list[str] = []
    for token in tokens:
        unquoted = token.strip().strip("\"'")
        if not unquoted:
            continue
        if _ID_RE.fullmatch(unquoted):
            values.append(unquoted)
        else:
            malformed.append(unquoted)
    return ParsedIds(tuple(values), tuple(malformed))


def parse_parent_id(value: object) -> ParsedIds:
    """Parse the canonical parent relation, rejecting plural parent specifications."""

    parsed = parse_id_list(value)
    if len(parsed.values) <= 1:
        return parsed
    return ParsedIds((), parsed.malformed + ("multiple_parent_ids",))


def normalized_reply(text: str) -> str:
    """Normalize templates without deleting meaningful troubleshooting language."""

    normalized = re.sub(r"https?://\S+|www\.\S+", "<url>", text.casefold())
    normalized = re.sub(r"@[a-z0-9_]+", "<mention>", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def word_count(text: str) -> int:
    """Count word-like tokens consistently for transparent length proxies."""

    return len(re.findall(r"\b[\w']+\b", text))


def require_mapping(row: Mapping[str, object], schema: ResolvedSchema, field: str) -> str:
    """Fetch a resolved field while preserving empty strings for anomaly accounting."""

    column = schema.columns[field]
    value = row.get(column)
    return "" if value is None else str(value)
