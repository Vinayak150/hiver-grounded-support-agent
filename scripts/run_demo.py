#!/usr/bin/env python3
"""Run a credential-free structural demo on synthetic sanitized fixtures."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from support_agent.agent.risk import assess_risk  # noqa: E402
from support_agent.data.spotify import write_json  # noqa: E402
from support_agent.taxonomy.discovery import provisional_intent  # noqa: E402
from support_agent.taxonomy.schema import load_taxonomy  # noqa: E402


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", value.casefold()))


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return 0.0 if not a | b else len(a & b) / len(a | b)


def run_demo(fixture: dict[str, object], risk_config: dict[str, object]) -> dict[str, object]:
    taxonomy = load_taxonomy(Path("configs/taxonomy.yaml"))
    outputs = []
    for case in fixture["cases"]:
        message = str(case["customer_message"])
        intent = provisional_intent(message, taxonomy)
        ranked = sorted(
            case["evidence"],
            key=lambda item: (
                -_similarity(message, str(item["customer_pattern"])),
                str(item["evidence_id"]),
            ),
        )
        best = ranked[0]
        score = _similarity(message, str(best["customer_pattern"]))
        risk = assess_risk(message, 1.0, risk_config, intent)
        intent_matches = str(best["intent"]) == intent
        auto_handle = not risk.high_risk and intent_matches and score >= 0.25
        reason_codes = []
        if risk.high_risk:
            reason_codes.extend(risk.reason_codes)
        if not intent_matches or score < 0.25:
            reason_codes.append("INSUFFICIENT_EVIDENCE")
        outputs.append(
            {
                "case_id": case["case_id"],
                "customer_message": message,
                "intent": intent,
                "retrieved_evidence_ids": [str(item["evidence_id"]) for item in ranked],
                "top_demo_similarity": round(score, 6),
                "reply": (
                    str(best["historical_reply"])
                    if auto_handle
                    else str(risk_config["demo_safe_escalation_reply"])
                ),
                "action": "AUTO_HANDLE" if auto_handle else "ESCALATE",
                "reason_codes": list(dict.fromkeys(reason_codes)),
            }
        )
    return {
        "fixture_type": fixture["fixture_type"],
        "warning": "Structural demo only; not benchmark evaluation or final-system scoring.",
        "outputs": outputs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("data/demo/demo_fixture.json"))
    parser.add_argument("--output", type=Path, default=Path("results/demo_output.json"))
    arguments = parser.parse_args()
    fixture = json.loads(arguments.fixture.read_text(encoding="utf-8"))
    agent_config = json.loads(Path("configs/agent.yaml").read_text(encoding="utf-8"))
    risk_config = dict(agent_config["risk"])
    risk_config["demo_safe_escalation_reply"] = agent_config["generation"][
        "safe_escalation_reply"
    ]
    result = run_demo(fixture, risk_config)
    write_json(arguments.output, result)
    for output in result["outputs"]:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    print("DEMO_DATA=SYNTHETIC_SANITIZED_NOT_BENCHMARK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
