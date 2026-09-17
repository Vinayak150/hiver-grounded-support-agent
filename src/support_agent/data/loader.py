"""Streaming TWCS CSV validation and row parsing."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .schema import (
    ParsedIds,
    ResolvedSchema,
    SchemaValidationError,
    normalized_reply,
    parse_id_list,
    parse_inbound,
    parse_parent_id,
    require_mapping,
    resolve_schema,
    word_count,
)


@dataclass(frozen=True)
class ParsedMessage:
    """A parsed row retained long enough to populate the temporary SQLite index."""

    tweet_id: str | None
    author_id: str
    inbound: bool | None
    created_at: str
    text: str
    parent_id: str | None
    child_ids: tuple[str, ...]
    malformed_id_count: int
    malformed_lineage_count: int
    invalid_inbound: bool
    normalized_text: str
    words: int


class TwcsCsvLoader:
    """Read a UTF-8 TWCS CSV once without loading all rows into memory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.schema: ResolvedSchema | None = None
        self.encoding: str | None = None

    def validate(self) -> ResolvedSchema:
        if not self.path.is_file():
            raise FileNotFoundError(f"TWCS input not found: {self.path}")
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames is None:
                    raise SchemaValidationError("CSV has no header row.")
                self.schema = resolve_schema(reader.fieldnames)
        except UnicodeDecodeError as error:
            raise SchemaValidationError(
                "TWCS input is not valid UTF-8/UTF-8-with-BOM; "
                "re-export it with a supported encoding."
            ) from error
        self.encoding = "utf-8-sig" if self.path.read_bytes()[:3] == b"\xef\xbb\xbf" else "utf-8"
        return self.schema

    def rows(self) -> Iterator[ParsedMessage]:
        schema = self.schema or self.validate()
        with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                yield self._parse_row(row, schema)

    @staticmethod
    def _parse_row(row: dict[str, str | None], schema: ResolvedSchema) -> ParsedMessage:
        tweet = parse_id_list(require_mapping(row, schema, "tweet_id"))
        tweet_id = tweet.values[0] if len(tweet.values) == 1 and not tweet.malformed else None
        parent = (
            parse_parent_id(require_mapping(row, schema, "in_response_to_tweet_id"))
            if schema.parent_column
            else ParsedIds((), ())
        )
        children = (
            parse_id_list(require_mapping(row, schema, "response_tweet_id"))
            if schema.child_column
            else ParsedIds((), ())
        )
        raw_inbound = require_mapping(row, schema, "inbound")
        inbound = parse_inbound(raw_inbound)
        text = require_mapping(row, schema, "text")
        return ParsedMessage(
            tweet_id=tweet_id,
            author_id=require_mapping(row, schema, "author_id").strip(),
            inbound=inbound,
            created_at=require_mapping(row, schema, "created_at").strip()
            if "created_at" in schema.columns
            else "",
            text=text,
            parent_id=parent.values[0] if len(parent.values) == 1 else None,
            child_ids=children.values,
            malformed_id_count=len(tweet.malformed) + max(0, len(tweet.values) - 1),
            malformed_lineage_count=len(parent.malformed) + len(children.malformed),
            invalid_inbound=bool(raw_inbound.strip()) and inbound is None,
            normalized_text=normalized_reply(text),
            words=word_count(text),
        )
