"""Validation for the versioned Spotify intent taxonomy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

INTENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class IntentDefinition:
    id: str
    display_name: str
    definition: str
    include_when: str
    exclude_when: str
    boundary_notes: str
    common_signals: tuple[str, ...]


@dataclass(frozen=True)
class Taxonomy:
    version: str
    brand: str
    source_split: str
    default_intent: str
    intents: tuple[IntentDefinition, ...]

    @property
    def intent_ids(self) -> tuple[str, ...]:
        return tuple(intent.id for intent in self.intents)


def validate_taxonomy(payload: dict[str, object]) -> Taxonomy:
    for field in ("version", "brand", "source_split", "default_intent", "intents"):
        if not payload.get(field):
            raise ValueError(f"Taxonomy field is required: {field}")
    raw_intents = payload["intents"]
    if not isinstance(raw_intents, list) or not raw_intents:
        raise ValueError("Taxonomy intents must be a non-empty list.")
    intents = []
    for raw in raw_intents:
        if not isinstance(raw, dict):
            raise ValueError("Each taxonomy intent must be a mapping.")
        for field in (
            "id",
            "display_name",
            "definition",
            "include_when",
            "exclude_when",
            "boundary_notes",
            "common_signals",
        ):
            if field not in raw:
                raise ValueError(f"Intent field is required: {field}")
        intent_id = str(raw["id"])
        if not INTENT_ID_RE.fullmatch(intent_id):
            raise ValueError(f"Invalid intent ID: {intent_id}")
        signals = raw["common_signals"]
        if not isinstance(signals, list):
            raise ValueError(f"common_signals must be a list for {intent_id}")
        intents.append(
            IntentDefinition(
                id=intent_id,
                display_name=str(raw["display_name"]),
                definition=str(raw["definition"]),
                include_when=str(raw["include_when"]),
                exclude_when=str(raw["exclude_when"]),
                boundary_notes=str(raw["boundary_notes"]),
                common_signals=tuple(str(signal).casefold() for signal in signals),
            )
        )
    ids = [intent.id for intent in intents]
    if len(ids) != len(set(ids)):
        raise ValueError("Taxonomy intent IDs must be unique.")
    default = str(payload["default_intent"])
    if default not in ids:
        raise ValueError("Taxonomy default_intent must name a declared intent.")
    if str(payload["source_split"]) != "TRAIN":
        raise ValueError("Phase 2 taxonomy must be derived from TRAIN only.")
    return Taxonomy(
        version=str(payload["version"]),
        brand=str(payload["brand"]),
        source_split=str(payload["source_split"]),
        default_intent=default,
        intents=tuple(intents),
    )


def load_taxonomy(path: Path) -> Taxonomy:
    return validate_taxonomy(json.loads(path.read_text(encoding="utf-8")))
