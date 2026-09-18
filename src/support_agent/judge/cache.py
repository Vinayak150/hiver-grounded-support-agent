"""Content-addressed persistent judge cache without secrets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class JudgeCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, object] | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Judge cache entry must be a JSON object.")
        return payload

    def put(self, key: str, payload: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
