"""Frozen-evaluation ID guards for all training and tuning workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def load_frozen_thread_ids(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    thread_ids = payload.get("thread_ids")
    if not isinstance(thread_ids, list) or not all(isinstance(value, str) for value in thread_ids):
        raise ValueError("Frozen evaluation manifest must contain a thread_ids list.")
    if len(thread_ids) != len(set(thread_ids)):
        raise ValueError("Frozen evaluation manifest contains duplicate thread IDs.")
    return set(thread_ids)


def assert_no_frozen_thread_ids(
    thread_ids: Iterable[str],
    manifest_path: Path,
    workflow_name: str,
) -> None:
    overlap = set(thread_ids) & load_frozen_thread_ids(manifest_path)
    if overlap:
        examples = ", ".join(sorted(overlap)[:5])
        raise ValueError(
            f"{workflow_name} attempted to use {len(overlap)} frozen evaluation "
            f"thread(s): {examples}"
        )
