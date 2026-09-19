#!/usr/bin/env python3
"""Collect explicit human response-quality judgments for frozen AUTO_HANDLE replies."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_final_evaluation import (  # noqa: E402
    generate_final_proposed_predictions,
    load_frozen_partitions,
)
from support_agent.annotation.schema import FrozenCandidate, HumanAnnotation  # noqa: E402
from support_agent.annotation.store import AnnotationStore  # noqa: E402
from support_agent.evaluation.gold import validate_human_gold  # noqa: E402


@dataclass(frozen=True)
class ResponseQualityAnnotation:
    case_id: str
    response_quality_approved: str
    reason: str
    annotation_source: str = "human"
    status: str = "FINALIZED"


RESPONSE_QUALITY_FIELDS = tuple(ResponseQualityAnnotation.__dataclass_fields__)


@dataclass(frozen=True)
class ReviewItem:
    candidate: FrozenCandidate
    prediction: dict[str, object]
    detail: dict[str, object]


class ResponseQualityStore:
    """Strict, duplicate-safe, atomic storage for explicit human decisions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, ResponseQualityAnnotation]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        with self.path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != RESPONSE_QUALITY_FIELDS:
                raise ValueError(
                    "Response-quality CSV schema does not match the required contract."
                )
            raw_rows = list(reader)
        case_ids = [row["case_id"] for row in raw_rows]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Response-quality CSV contains duplicate case IDs.")
        rows = [ResponseQualityAnnotation(**row) for row in raw_rows]
        for row in rows:
            if not row.case_id.strip():
                raise ValueError("Response-quality rows require a case ID.")
            if row.response_quality_approved not in {"true", "false"}:
                raise ValueError("Response-quality approval must be exactly true or false.")
            if not row.reason.strip():
                raise ValueError("Response-quality rows require a non-empty human reason.")
            if row.annotation_source != "human" or row.status != "FINALIZED":
                raise ValueError("Response-quality rows must be finalized explicit human review.")
        return {row.case_id: row for row in rows}

    def initialize(self) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            self.load()
            return
        self._write([])

    def save(self, annotation: ResponseQualityAnnotation) -> None:
        rows = self.load()
        if annotation.case_id in rows:
            raise ValueError(f"Case already has a finalized judgment: {annotation.case_id}")
        rows[annotation.case_id] = annotation
        self._write([rows[case_id] for case_id in sorted(rows)])

    def replace(self, annotation: ResponseQualityAnnotation) -> None:
        rows = self.load()
        if annotation.case_id not in rows:
            raise ValueError(f"Cannot revise an unfinished case: {annotation.case_id}")
        rows[annotation.case_id] = annotation
        self._write([rows[case_id] for case_id in sorted(rows)])

    def _write(self, rows: list[ResponseQualityAnnotation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=RESPONSE_QUALITY_FIELDS, lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(row.__dict__ for row in rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def normalize_decision(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized == "y":
        return True
    if normalized == "n":
        return False
    raise ValueError("Decision must be y or n.")


def _unique_by_case_id(
    rows: list[dict[str, object]], label: str
) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for row in rows:
        case_id = str(row.get("case_id", ""))
        if not case_id:
            raise ValueError(f"{label} contains a row without a case ID.")
        if case_id in output:
            raise ValueError(f"{label} contains duplicate case IDs.")
        output[case_id] = row
    return output


def build_review_plan(
    candidates: list[FrozenCandidate],
    gold: dict[str, HumanAnnotation],
    proposed_rows: list[dict[str, object]],
    review_rows: list[dict[str, object]],
) -> list[ReviewItem]:
    """Apply the final evaluator's ordering and AUTO_HANDLE-selection logic exactly."""

    candidate_ids = [candidate.case_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Frozen candidates contain duplicate case IDs.")
    proposed_by_id = _unique_by_case_id(proposed_rows, "Final proposed predictions")
    detail_by_id = _unique_by_case_id(review_rows, "Final proposed review details")
    if set(proposed_by_id) != set(candidate_ids) or set(detail_by_id) != set(candidate_ids):
        raise ValueError("Final proposed outputs do not reconcile with the frozen candidates.")
    unknown_gold = set(gold) - set(candidate_ids)
    if unknown_gold:
        raise ValueError("Human gold contains cases outside the frozen candidate set.")

    candidate_by_id = {candidate.case_id: candidate for candidate in candidates}
    ordered_case_ids = [case_id for case_id in candidate_ids if case_id in gold]
    required_case_ids = [
        case_id
        for case_id in ordered_case_ids
        if proposed_by_id[case_id].get("action") == "AUTO_HANDLE"
    ]
    for case_id in required_case_ids:
        if detail_by_id[case_id].get("action") != "AUTO_HANDLE":
            raise ValueError("Prediction and review detail actions do not match.")
    return [
        ReviewItem(candidate_by_id[case_id], proposed_by_id[case_id], detail_by_id[case_id])
        for case_id in required_case_ids
    ]


def _customer_context(candidate: FrozenCandidate) -> str:
    messages: list[str] = []
    for part in candidate.conversation_context.split(" || "):
        role, separator, text = part.partition(":")
        normalized = text.strip()
        if (
            separator
            and role.strip() == "CUSTOMER"
            and normalized
            and normalized != candidate.customer_message
            and normalized not in messages
        ):
            messages.append(normalized)
    return "\n".join(f"- {message}" for message in messages) or "(none)"


def _display_item(item: ReviewItem, position: int, total: int) -> None:
    prediction = item.prediction
    detail = item.detail
    print("\n" + "=" * 78)
    print(f"PROGRESS: {position}/{total}")
    print(f"CASE ID: {item.candidate.case_id}")
    print("\nCUSTOMER")
    print(item.candidate.customer_message)
    print("\nADDITIONAL CUSTOMER CONTEXT")
    print(_customer_context(item.candidate))
    print("\nPREDICTED INTENT")
    print(prediction["intent"])
    print("\nPREDICTED ACTION")
    print(prediction["action"])
    print("\nPROPOSED REPLY")
    print(prediction["reply"])
    print("\nRETRIEVED / SUPPORTING EVIDENCE USED BY THE REPLY")
    retrieved = {
        str(case.get("thread_id")): case
        for case in detail.get("retrieved_cases", [])
        if isinstance(case, dict)
    }
    evidence_ids = [str(value) for value in prediction.get("evidence_ids", [])]
    if not evidence_ids:
        print("(none)")
    for number, evidence_id in enumerate(evidence_ids, start=1):
        evidence = retrieved.get(evidence_id, {})
        print(f"  {number}. evidence_id={evidence_id}")
        print(f"     intent={evidence.get('intent', '(unavailable)')}")
        print(f"     historical_reply={evidence.get('historical_reply', '(unavailable)')}")
    print("\nGROUNDING / RISK / VERIFIER INFORMATION")
    print(f"  evidence_sufficient={detail.get('evidence_sufficient', '(unavailable)')}")
    print(f"  grounding_passed={detail.get('grounding_passed', '(unavailable)')}")
    print(f"  risk_tags={detail.get('risk_tags', [])}")
    print(f"  reason_codes={detail.get('reason_codes', [])}")
    print(f"  action_reason={prediction.get('action_reason', '(unavailable)')}")


def _collect_human_judgment(item: ReviewItem) -> ResponseQualityAnnotation | None:
    while True:
        raw = input("Response acceptable for automatic sending? [y/n, q quit] ").strip()
        if raw.casefold() == "q":
            return None
        try:
            approved = normalize_decision(raw)
        except ValueError:
            print("Enter y, n, or q.")
            continue
        reason = ""
        while not reason:
            reason = input("Short reason> ").strip()
            if not reason:
                print("A short human-written reason is required.")
        return ResponseQualityAnnotation(
            case_id=item.candidate.case_id,
            response_quality_approved="true" if approved else "false",
            reason=reason,
        )


def _print_status(store: ResponseQualityStore, required_case_ids: set[str]) -> None:
    reviewed = len(set(store.load()) & required_case_ids)
    remaining = len(required_case_ids) - reviewed
    print(f"RESPONSE_QUALITY_REVIEWED={reviewed}")
    print(f"REQUIRED_AUTO_HANDLE={len(required_case_ids)}")
    print(f"REMAINING={remaining}")
    print(f"RESPONSE_QUALITY_STATUS={'READY' if remaining == 0 else 'INCOMPLETE'}")


def run_review(
    plan: list[ReviewItem], store: ResponseQualityStore, revise_case_id: str | None = None
) -> None:
    required_case_ids = {item.candidate.case_id for item in plan}
    store.initialize()
    existing = store.load()
    unexpected = set(existing) - required_case_ids
    if unexpected:
        raise ValueError("Response-quality CSV contains a non-AUTO_HANDLE case.")

    if revise_case_id is not None:
        if revise_case_id not in required_case_ids:
            raise ValueError("Only a required final AUTO_HANDLE case can be revised.")
        if revise_case_id not in existing:
            raise ValueError("Only an existing finalized judgment can be revised.")
        position = next(
            index
            for index, item in enumerate(plan, start=1)
            if item.candidate.case_id == revise_case_id
        )
        item = plan[position - 1]
        _display_item(item, position, len(plan))
        annotation = _collect_human_judgment(item)
        if annotation is not None:
            store.replace(annotation)
            print("Revised human judgment saved atomically.")
        _print_status(store, required_case_ids)
        return

    for position, item in enumerate(plan, start=1):
        if item.candidate.case_id in existing:
            continue
        _display_item(item, position, len(plan))
        annotation = _collect_human_judgment(item)
        if annotation is None:
            break
        store.save(annotation)
        print("Human judgment saved atomically.")
        existing[item.candidate.case_id] = annotation
    _print_status(store, required_case_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/spotify_threads.jsonl"))
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path("data/annotations/final_golden_candidates.csv"),
    )
    parser.add_argument(
        "--gold", type=Path, default=Path("data/annotations/golden_annotations.csv")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/annotations/human_response_quality.csv"),
    )
    parser.add_argument("--revise", metavar="CASE_ID")
    arguments = parser.parse_args()

    paths = {
        "candidates": arguments.candidates,
        "frozen_manifest": Path("data/manifests/final_golden_candidate_manifest.json"),
        "splits": Path("data/manifests/split_manifest.json"),
        "taxonomy": Path("configs/taxonomy.yaml"),
        "annotation": Path("configs/annotation.yaml"),
    }
    gate = validate_human_gold(
        gold_path=arguments.gold,
        candidates_path=paths["candidates"],
        frozen_manifest_path=paths["frozen_manifest"],
        split_manifest_path=paths["splits"],
        taxonomy_path=paths["taxonomy"],
        annotation_config_path=paths["annotation"],
    )
    if not gate.final_evaluation_ready:
        print("RESPONSE_QUALITY_STATUS=INCOMPLETE")
        print("RESPONSE_QUALITY_BLOCKED=" + json.dumps(list(gate.errors)))
        return 2
    if not arguments.corpus.exists():
        print("RESPONSE_QUALITY_STATUS=INCOMPLETE")
        print(f"RESPONSE_QUALITY_BLOCKED=processed corpus missing: {arguments.corpus}")
        return 2

    (
        taxonomy,
        candidates,
        thread_to_case,
        train,
        development,
        final,
        final_system,
    ) = load_frozen_partitions(arguments.corpus, paths)
    proposed_rows, review_rows = generate_final_proposed_predictions(
        train,
        development,
        final,
        taxonomy,
        final_system,
        thread_to_case,
    )
    gold = AnnotationStore(arguments.gold).load()
    plan = build_review_plan(candidates, gold, proposed_rows, review_rows)
    run_review(plan, ResponseQualityStore(arguments.output), arguments.revise)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
