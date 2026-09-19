#!/usr/bin/env python3
"""Run blinded, resumable human review for the Phase 5A V2 agreement sample."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_judge_agreement import FIELDS as HUMAN_RATING_FIELDS  # noqa: E402
from scripts.run_judge_v2 import clipped, evidence_for, read_jsonl  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file  # noqa: E402
from support_agent.judge.rubric import DIMENSIONS, RUBRIC_VERSION  # noqa: E402

SAMPLE_PROTOCOL = "human-judge-agreement-sample-v1"
SAMPLE_SEED = "phase6b-human-judge-agreement-20260919"
SAMPLE_SIZE = 40
SYSTEM_TARGETS = {"proposed": 14, "lexical": 13, "fixed": 13}
NOTES_FIELDS = ("case_id", "system", "critical_failure", "note")
RUBRIC_PATH = Path("docs/LLM_JUDGE_RUBRIC.md")


@dataclass(frozen=True)
class HumanJudgeRating:
    case_id: str
    system: str
    groundedness: str
    relevance: str
    helpfulness: str
    safety: str
    brand_context: str
    overall_pass: str
    annotation_source: str = "human"
    status: str = "FINALIZED"


@dataclass(frozen=True)
class HumanJudgeNote:
    case_id: str
    system: str
    critical_failure: str
    note: str


@dataclass(frozen=True)
class HumanReviewItem:
    case_id: str
    system: str
    customer: str
    additional_context: str
    action: str
    reply: str
    evidence: tuple[tuple[str, str], ...]


def _stable_hash(seed: str, case_id: str, system: str) -> str:
    return hashlib.sha256(f"{seed}:{case_id}:{system}".encode()).hexdigest()


def _unique_primary_metadata(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """Keep only stable primary-row metadata; judgment values are never consulted."""

    metadata: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if str(row.get("run_id", "primary")) != "primary":
            continue
        key = (str(row.get("case_id", "")), str(row.get("system", "")))
        if not all(key) or key[1] not in SYSTEM_TARGETS:
            raise ValueError("Primary V2 cohort contains invalid case/system metadata.")
        if key in seen:
            raise ValueError("Primary V2 cohort contains duplicate case/system keys.")
        seen.add(key)
        metadata.append({"case_id": key[0], "system": key[1]})
    return metadata


def deterministic_sample(primary_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    metadata = _unique_primary_metadata(primary_rows)
    grouped = {
        system: [row for row in metadata if row["system"] == system]
        for system in SYSTEM_TARGETS
    }
    selected: list[dict[str, str]] = []
    for system, target in SYSTEM_TARGETS.items():
        ranked = sorted(
            grouped[system],
            key=lambda row: _stable_hash(SAMPLE_SEED, row["case_id"], row["system"]),
        )
        if len(ranked) < target:
            raise ValueError(f"Insufficient primary V2 rows for system: {system}")
        selected.extend(ranked[:target])
    return sorted(
        selected,
        key=lambda row: _stable_hash(
            f"{SAMPLE_SEED}:review-order", row["case_id"], row["system"]
        ),
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _validate_sample_manifest(manifest: dict[str, object]) -> list[dict[str, str]]:
    if (
        manifest.get("protocol") != SAMPLE_PROTOCOL
        or manifest.get("rubric_version") != RUBRIC_VERSION
        or manifest.get("sample_size") != SAMPLE_SIZE
        or manifest.get("status") != "FROZEN_BEFORE_HUMAN_RATINGS"
    ):
        raise ValueError("Human judge sample manifest contract is invalid.")
    raw_keys = manifest.get("selected_keys")
    if not isinstance(raw_keys, list):
        raise ValueError("Human judge sample manifest has no selected keys.")
    rows = [dict(row) for row in raw_keys if isinstance(row, dict)]
    if len(rows) != SAMPLE_SIZE or any(set(row) != {"case_id", "system"} for row in rows):
        raise ValueError("Human judge sample manifest selected keys are invalid.")
    metadata = _unique_primary_metadata(rows)
    keys = [(row["case_id"], row["system"]) for row in metadata]
    if len(keys) != SAMPLE_SIZE or len(set(keys)) != SAMPLE_SIZE:
        raise ValueError("Human judge sample manifest contains duplicate keys.")
    if Counter(row["system"] for row in metadata) != Counter(SYSTEM_TARGETS):
        raise ValueError("Human judge sample manifest is not balanced as declared.")
    return metadata


def load_or_create_sample_manifest(
    manifest_path: Path,
    source_manifest_path: Path,
    primary_rows: list[dict[str, object]],
    cohort_results_path: Path,
) -> dict[str, object]:
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_sample_manifest(manifest)
        return manifest

    selected = deterministic_sample(primary_rows)
    primary_metadata = _unique_primary_metadata(primary_rows)
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    manifest = {
        "protocol": SAMPLE_PROTOCOL,
        "rubric_version": RUBRIC_VERSION,
        "sample_size": SAMPLE_SIZE,
        "selection_algorithm": (
            "For each system, sort primary case/system keys by SHA-256 of "
            "'<seed>:<case_id>:<system>', take 14 proposed, 13 lexical, and 13 fixed, "
            "then sort selected keys by a separately namespaced SHA-256 review-order hash."
        ),
        "seed_hash_rule": (
            f"seed={SAMPLE_SEED}; SHA-256 UTF-8 '<seed>:<case_id>:<system>'"
        ),
        "system_counts": dict(sorted(Counter(row["system"] for row in selected).items())),
        "selected_keys": selected,
        "source_cohort": {
            "phase": "5A",
            "protocol": source_manifest.get("protocol"),
            "split": source_manifest.get("split"),
            "run_id": "primary",
            "case_count": source_manifest.get("case_count"),
            "systems": list(SYSTEM_TARGETS),
            "case_system_row_count": len(primary_metadata),
            "primary_results": str(cohort_results_path),
            "primary_results_sha256": sha256_file(cohort_results_path),
            "sample_manifest": str(source_manifest_path),
            "sample_manifest_sha256": sha256_file(source_manifest_path),
        },
        "score_independence": (
            "Selection used only case_id and system metadata. It did not use judge scores, "
            "overall pass/fail, rationale, failure codes, or critical-failure information."
        ),
        "status": "FROZEN_BEFORE_HUMAN_RATINGS",
    }
    _atomic_json(manifest_path, manifest)
    return manifest


def overall_pass_from_scores(scores: dict[str, int], critical_failure: bool) -> bool:
    if set(scores) != set(DIMENSIONS):
        raise ValueError("Human score dimensions do not match the authoritative rubric.")
    if any(type(value) is not int or not 1 <= value <= 5 for value in scores.values()):
        raise ValueError("Human judge scores must be integers from one through five.")
    return (
        all(scores[dimension] >= 3 for dimension in DIMENSIONS)
        and scores["groundedness"] >= 4
        and scores["safety"] >= 4
        and not critical_failure
    )


class HumanJudgeStore:
    def __init__(self, ratings_path: Path, notes_path: Path) -> None:
        self.ratings_path = ratings_path
        self.notes_path = notes_path

    @staticmethod
    def _key(row: HumanJudgeRating | HumanJudgeNote) -> tuple[str, str]:
        return row.case_id, row.system

    def load_ratings(self) -> dict[tuple[str, str], HumanJudgeRating]:
        if not self.ratings_path.exists() or self.ratings_path.stat().st_size == 0:
            return {}
        with self.ratings_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != HUMAN_RATING_FIELDS:
                raise ValueError("Human judge ratings schema is invalid.")
            rows = [HumanJudgeRating(**row) for row in reader]
        keys = [self._key(row) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("Human judge ratings contain duplicate case/system rows.")
        for row in rows:
            scores = {dimension: int(getattr(row, dimension)) for dimension in DIMENSIONS}
            if any(not 1 <= score <= 5 for score in scores.values()):
                raise ValueError("Human judge scores must be integers from one through five.")
            if row.overall_pass not in {"true", "false"}:
                raise ValueError("Human overall_pass must be exactly true or false.")
            if row.annotation_source != "human" or row.status != "FINALIZED":
                raise ValueError("Human judge rows must be finalized explicit human ratings.")
        return {self._key(row): row for row in rows}

    def load_notes(self) -> dict[tuple[str, str], HumanJudgeNote]:
        if not self.notes_path.exists() or self.notes_path.stat().st_size == 0:
            return {}
        with self.notes_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != NOTES_FIELDS:
                raise ValueError("Human judge notes schema is invalid.")
            rows = [HumanJudgeNote(**row) for row in reader]
        keys = [self._key(row) for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("Human judge notes contain duplicate case/system rows.")
        if any(row.critical_failure not in {"true", "false"} for row in rows):
            raise ValueError("Human critical_failure must be exactly true or false.")
        return {self._key(row): row for row in rows}

    def load(self) -> tuple[
        dict[tuple[str, str], HumanJudgeRating], dict[tuple[str, str], HumanJudgeNote]
    ]:
        ratings, notes = self.load_ratings(), self.load_notes()
        if set(ratings) != set(notes):
            raise ValueError("Human judge ratings and audit notes do not reconcile.")
        for key, rating in ratings.items():
            scores = {dimension: int(getattr(rating, dimension)) for dimension in DIMENSIONS}
            critical = notes[key].critical_failure == "true"
            expected = overall_pass_from_scores(scores, critical)
            if (rating.overall_pass == "true") != expected:
                raise ValueError("Human overall_pass is inconsistent with the rubric.")
        return ratings, notes

    def initialize(self) -> None:
        ratings_exist = self.ratings_path.exists() and self.ratings_path.stat().st_size > 0
        notes_exist = self.notes_path.exists() and self.notes_path.stat().st_size > 0
        if ratings_exist or notes_exist:
            self.load()
            return
        self._write_pair([], [])

    def save(
        self,
        rating: HumanJudgeRating,
        note: HumanJudgeNote,
        allowed_keys: set[tuple[str, str]],
    ) -> None:
        ratings, notes = self.load()
        key = self._key(rating)
        if key != self._key(note) or key not in allowed_keys:
            raise ValueError("Only a key in the frozen human agreement sample can be saved.")
        if key in ratings:
            raise ValueError("Human judge rating is already finalized.")
        self._validate_pair(rating, note)
        ratings[key], notes[key] = rating, note
        self._write_pair(
            [ratings[value] for value in sorted(ratings)],
            [notes[value] for value in sorted(notes)],
        )

    def replace(
        self,
        rating: HumanJudgeRating,
        note: HumanJudgeNote,
        allowed_keys: set[tuple[str, str]],
    ) -> None:
        ratings, notes = self.load()
        key = self._key(rating)
        if key != self._key(note) or key not in allowed_keys or key not in ratings:
            raise ValueError("Only an existing sampled rating can be explicitly revised.")
        self._validate_pair(rating, note)
        ratings[key], notes[key] = rating, note
        self._write_pair(
            [ratings[value] for value in sorted(ratings)],
            [notes[value] for value in sorted(notes)],
        )

    @staticmethod
    def _validate_pair(rating: HumanJudgeRating, note: HumanJudgeNote) -> None:
        scores = {dimension: int(getattr(rating, dimension)) for dimension in DIMENSIONS}
        expected = overall_pass_from_scores(scores, note.critical_failure == "true")
        if rating.annotation_source != "human" or rating.status != "FINALIZED":
            raise ValueError("Human judge rows must be finalized explicit human ratings.")
        if rating.overall_pass != str(expected).lower():
            raise ValueError("Human overall_pass is inconsistent with the rubric.")

    def _write_pair(
        self, ratings: list[HumanJudgeRating], notes: list[HumanJudgeNote]
    ) -> None:
        self.ratings_path.parent.mkdir(parents=True, exist_ok=True)
        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_paths: list[str] = []
        try:
            for path, fields, rows in (
                (self.notes_path, NOTES_FIELDS, notes),
                (self.ratings_path, HUMAN_RATING_FIELDS, ratings),
            ):
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{path.name}.", dir=path.parent, text=True
                )
                temporary_paths.append(temporary_name)
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(row.__dict__ for row in rows)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.replace(temporary_paths[0], self.notes_path)
            os.replace(temporary_paths[1], self.ratings_path)
        finally:
            for temporary_name in temporary_paths:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)


def _primary_cohort_from_source_manifest(path: Path) -> list[dict[str, object]]:
    source = json.loads(path.read_text(encoding="utf-8"))
    cases = source.get("cases")
    if source.get("case_count") != 80 or not isinstance(cases, list) or len(cases) != 80:
        raise ValueError("Phase 5A V2 sample manifest is invalid.")
    case_ids = [str(case["case_id"]) for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Phase 5A V2 sample manifest contains duplicate case IDs.")
    return [
        {"case_id": case_id, "system": system, "run_id": "primary"}
        for system in SYSTEM_TARGETS
        for case_id in case_ids
    ]


def _indexed(rows: list[dict[str, object]], label: str) -> dict[str, dict[str, object]]:
    output: dict[str, dict[str, object]] = {}
    for row in rows:
        case_id = str(row.get("case_id", ""))
        if not case_id or case_id in output:
            raise ValueError(f"{label} contains a missing or duplicate case ID.")
        output[case_id] = row
    return output


def _split_customer_context(exact_customer: str, first_customer_text: str) -> tuple[str, str]:
    first = clipped(first_customer_text, len(exact_customer))
    if first and exact_customer.startswith(first):
        return first, exact_customer[len(first) :].strip() or "(none)"
    return exact_customer, "(none)"


def load_review_items(
    selected_keys: list[dict[str, str]],
    *,
    config_path: Path = Path("configs/judge_v2.yaml"),
    split_path: Path = Path("data/manifests/split_manifest.json"),
    corpus_path: Path = Path("data/processed/spotify_threads.jsonl"),
) -> list[HumanReviewItem]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("rubric_version") != RUBRIC_VERSION:
        raise ValueError("V2 configuration does not use the authoritative rubric version.")
    split = json.loads(split_path.read_text(encoding="utf-8"))
    development_ids = set(split["thread_ids"]["DEVELOPMENT"])
    train_ids = set(split["thread_ids"]["TRAIN"])
    needed_ids = development_ids | train_ids
    thread_map = {
        thread.thread_id: thread
        for thread in read_threads(corpus_path)
        if thread.thread_id in needed_ids
    }
    if set(thread_map) != needed_ids:
        raise ValueError("Phase 5A V2 inputs do not reconcile with the processed corpus.")
    source_paths = {
        "proposed": Path("results/dev_proposed_agent.jsonl"),
        "lexical": Path("results/dev_baseline_lexical.jsonl"),
        "fixed": Path("results/dev_baseline_fixed.jsonl"),
    }
    sources = {
        system: _indexed(read_jsonl(path), f"{system} source")
        for system, path in source_paths.items()
    }
    train_map = {case_id: thread_map[case_id] for case_id in train_ids}
    customer_limit = int(config["customer_context_characters"])
    reply_limit = int(config["reply_characters"])
    evidence_count = int(config["maximum_evidence_excerpts"])
    items: list[HumanReviewItem] = []
    for selected in selected_keys:
        case_id, system = selected["case_id"], selected["system"]
        if case_id not in development_ids or system not in sources:
            raise ValueError("Human agreement sample contains an invalid Phase 5A V2 key.")
        source = sources[system].get(case_id)
        if source is None:
            raise ValueError("A sampled key is missing its exact Phase 5A system output.")
        thread = thread_map[case_id]
        exact_customer = clipped(thread.customer_text(), customer_limit)
        first_turn = next(turn.text for turn in thread.turns if turn.author_role == "CUSTOMER")
        customer, additional = _split_customer_context(exact_customer, first_turn)
        excerpts = evidence_for(system, source, train_map, config)
        if system == "proposed":
            evidence_ids = [
                str(row["thread_id"])
                for row in list(source.get("retrieved_cases", []))[:evidence_count]
            ]
        else:
            evidence_ids = [
                str(value)
                for value in list(source.get("retrieved_thread_ids", []))[:evidence_count]
            ]
        if len(evidence_ids) != len(excerpts):
            raise ValueError("Phase 5A V2 evidence IDs and excerpts do not reconcile.")
        items.append(
            HumanReviewItem(
                case_id=case_id,
                system=system,
                customer=customer,
                additional_context=additional,
                action=str(source["action"]),
                reply=clipped(str(source["reply"]), reply_limit),
                evidence=tuple(zip(evidence_ids, excerpts, strict=True)),
            )
        )
    return items


def print_rubric(rubric_path: Path = RUBRIC_PATH) -> None:
    text = rubric_path.read_text(encoding="utf-8").strip()
    if f"Rubric version: `{RUBRIC_VERSION}`" not in text:
        raise ValueError("Authoritative rubric document version does not match code.")
    print("\nRUBRIC CHEAT SHEET")
    print("1 severe failure | 2 major weakness | 3 mixed/limited | 4 strong | 5 excellent")
    print("\nAUTHORITATIVE RUBRIC")
    print(text)


def _display_item(item: HumanReviewItem, position: int, total: int) -> None:
    print("\n" + "=" * 78)
    print(f"PROGRESS {position}/{total}")
    print(f"CASE ID: {item.case_id}")
    print("\nCUSTOMER")
    print(item.customer)
    print("\nADDITIONAL CUSTOMER CONTEXT")
    print(item.additional_context)
    print("\nCANDIDATE ACTION")
    print(item.action)
    print("\nCANDIDATE REPLY")
    print(item.reply)
    print("\nSUPPORTING HISTORICAL EVIDENCE")
    if not item.evidence:
        print("(none)")
    for number, (evidence_id, excerpt) in enumerate(item.evidence, start=1):
        print(f"  {number}. evidence_id={evidence_id}")
        print(f"     {excerpt}")


def _prompt_score(label: str) -> int | None:
    while True:
        value = input(f"{label} [1-5, r rubric, q quit]> ").strip().casefold()
        if value == "q":
            return None
        if value == "r":
            print_rubric()
            continue
        if value in {"1", "2", "3", "4", "5"}:
            return int(value)
        print("Enter an integer from 1 to 5, r, or q.")


def _prompt_critical_failure() -> bool | None:
    while True:
        value = input("Critical failure? [y/n, r rubric, q quit]> ").strip().casefold()
        if value == "q":
            return None
        if value == "r":
            print_rubric()
            continue
        if value in {"y", "n"}:
            return value == "y"
        print("Enter y, n, r, or q.")


def collect_rating(item: HumanReviewItem) -> tuple[HumanJudgeRating, HumanJudgeNote] | None:
    labels = {
        "groundedness": "Groundedness",
        "relevance": "Relevance",
        "helpfulness": "Helpfulness",
        "safety": "Safety",
        "brand_context": "Brand/context",
    }
    scores: dict[str, int] = {}
    for dimension in DIMENSIONS:
        value = _prompt_score(labels[dimension])
        if value is None:
            return None
        scores[dimension] = value
    critical_failure = _prompt_critical_failure()
    if critical_failure is None:
        return None
    note_text = input("Optional short note> ").strip()
    overall_pass = overall_pass_from_scores(scores, critical_failure)
    rating = HumanJudgeRating(
        case_id=item.case_id,
        system=item.system,
        groundedness=str(scores["groundedness"]),
        relevance=str(scores["relevance"]),
        helpfulness=str(scores["helpfulness"]),
        safety=str(scores["safety"]),
        brand_context=str(scores["brand_context"]),
        overall_pass=str(overall_pass).lower(),
    )
    note = HumanJudgeNote(
        case_id=item.case_id,
        system=item.system,
        critical_failure=str(critical_failure).lower(),
        note=note_text,
    )
    return rating, note


def _print_status(store: HumanJudgeStore, allowed_keys: set[tuple[str, str]]) -> None:
    ratings, _ = store.load()
    reviewed = len(set(ratings) & allowed_keys)
    remaining = len(allowed_keys) - reviewed
    print(f"HUMAN_JUDGE_REVIEWED={reviewed}")
    print(f"HUMAN_JUDGE_REQUIRED={len(allowed_keys)}")
    print(f"REMAINING={remaining}")
    print(f"HUMAN_JUDGE_REVIEW_STATUS={'READY' if remaining == 0 else 'INCOMPLETE'}")


def run_review(
    items: list[HumanReviewItem], store: HumanJudgeStore, revise_index: int | None = None
) -> None:
    if len(items) != SAMPLE_SIZE:
        raise ValueError(f"Human agreement review requires exactly {SAMPLE_SIZE} frozen items.")
    keys = [(item.case_id, item.system) for item in items]
    if len(keys) != len(set(keys)):
        raise ValueError("Human agreement review items contain duplicate keys.")
    allowed_keys = set(keys)
    store.initialize()
    ratings, _ = store.load()
    if not set(ratings) <= allowed_keys:
        raise ValueError("Human judge CSV contains a row outside the frozen 40-key sample.")
    print_rubric()

    if revise_index is not None:
        if not 1 <= revise_index <= len(items):
            raise ValueError("Revision index is outside the frozen review order.")
        item = items[revise_index - 1]
        if (item.case_id, item.system) not in ratings:
            raise ValueError("Only an existing finalized rating can be revised.")
        _display_item(item, revise_index, len(items))
        result = collect_rating(item)
        if result is not None:
            store.replace(*result, allowed_keys)
            print("Revised human rating saved atomically.")
        _print_status(store, allowed_keys)
        return

    for position, item in enumerate(items, start=1):
        if (item.case_id, item.system) in ratings:
            continue
        _display_item(item, position, len(items))
        result = collect_rating(item)
        if result is None:
            break
        store.save(*result, allowed_keys)
        ratings[(item.case_id, item.system)] = result[0]
        print("Human rating saved atomically.")
    _print_status(store, allowed_keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-source",
        type=Path,
        default=Path("results/dev_judge_v2_sample_manifest.json"),
    )
    parser.add_argument(
        "--sample-manifest",
        type=Path,
        default=Path("data/manifests/human_judge_agreement_sample.json"),
    )
    parser.add_argument(
        "--cohort-results",
        type=Path,
        default=Path("results/dev_judge_v2_results.jsonl"),
    )
    parser.add_argument(
        "--ratings",
        type=Path,
        default=Path("data/annotations/human_judge_ratings.csv"),
    )
    parser.add_argument(
        "--notes",
        type=Path,
        default=Path("data/annotations/human_judge_rating_notes.csv"),
    )
    parser.add_argument("--revise", type=int, metavar="REVIEW_INDEX")
    arguments = parser.parse_args()

    primary_rows = (
        [] if arguments.sample_manifest.exists() else read_jsonl(arguments.cohort_results)
    )
    manifest = load_or_create_sample_manifest(
        arguments.sample_manifest,
        arguments.sample_source,
        primary_rows,
        arguments.cohort_results,
    )
    selected = _validate_sample_manifest(manifest)
    items = load_review_items(selected)
    run_review(items, HumanJudgeStore(arguments.ratings, arguments.notes), arguments.revise)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
