"""Load versioned agent configuration with a small explicit override layer."""

from __future__ import annotations

import json
from pathlib import Path


def load_agent_config(path: Path) -> dict[str, object]:
    config = json.loads(path.read_text(encoding="utf-8"))
    extends = config.pop("extends", None)
    if extends is None:
        return config
    base_path = Path(str(extends))
    if not base_path.is_absolute():
        base_path = Path.cwd() / base_path
    base = load_agent_config(base_path)
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base
