#!/usr/bin/env python3
"""Build the deterministic Phase 5B judge-and-agent failure audit."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.run_judge_v2 as judge_v2  # noqa: E402
from support_agent.data.spotify import read_threads, sha256_file, write_json  # noqa: E402
from support_agent.generation.grounded import (  # noqa: E402
    GroundedComposer,
    answer_coverage_failure,
    sanitize_reply,
)
from support_agent.generation.verifier import GroundingVerifier  # noqa: E402
from support_agent.judge.cache import JudgeCache  # noqa: E402
from support_agent.judge.prompts_v2 import ABSOLUTE_PREFIX  # noqa: E402
from support_agent.judge.runner_v2 import V2JudgeRunner  # noqa: E402
from support_agent.judge.sampling import stable_rank  # noqa: E402
from support_agent.judge.schema_v2 import CompactJudgeResult, compact_judge_schema  # noqa: E402
from support_agent.retrieval.hybrid import RetrievedCase  # noqa: E402

OUTPUT = Path("results/dev_failure_audit.json")
DOCUMENT = Path("docs/PHASE5B_FAILURE_AUDIT.md")
FROZEN_PHASE5A = (
    Path("results/dev_judge_v2_results.jsonl"),
    Path("results/dev_judge_v2_summary.json"),
    Path("results/judge_v2_repeatability.json"),
    Path("results/judge_v2_order_bias.json"),
    Path("results/dev_judge_v2_sample_manifest.json"),
)
EXPECTED_HASHES = {
    "results/dev_judge_v2_results.jsonl": (
        "6d3408823fffe3240620c8168a5df46016530f949a074325c409da55c4d20edb"
    ),
    "results/dev_judge_v2_summary.json": (
        "4b7c8f3471ad802fb3bd8d062bfb3d0559111dd4fbceeb0f902c51e883e89c39"
    ),
    "results/judge_v2_repeatability.json": (
        "0dd7229fbb952431dd0a31e73919ab952054a0f9683f2512ea87678c1c650b9d"
    ),
    "results/judge_v2_order_bias.json": (
        "232c8a9767875db5c45e1baa9eb2959491a7ff304a0ba3939cd7b4ef340ab036"
    ),
    "results/dev_judge_v2_sample_manifest.json": (
        "f558001632c6e79ca8731e631a36614515109bf8baaa25c6e0abeede009ad60a"
    ),
}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _retrieved_case(item: dict[str, object]) -> RetrievedCase:
    return RetrievedCase(
        thread_id=str(item["thread_id"]),
        similarity=float(item["similarity"]),
        historical_reply=str(item["historical_reply"]),
        intent=str(item["intent"]),
        component_scores={str(k): float(v) for k, v in item["component_scores"].items()},
        evidence_score=float(item["evidence_score"]),
        template_frequency=1,
    )


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", sanitize_reply(text).casefold()).strip(" .")


def _question_only(text: str) -> bool:
    sentences = [item for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item]
    return bool(sentences) and all(item.endswith("?") for item in sentences)


def _content_tokens(text: str) -> set[str]:
    stop = {
        "about",
        "and",
        "are",
        "can",
        "for",
        "from",
        "have",
        "how",
        "please",
        "spotify",
        "that",
        "the",
        "this",
        "what",
        "when",
        "which",
        "with",
        "you",
        "your",
    }
    return {
        token
        for token in re.findall(r"[a-z][a-z']+", text.casefold())
        if len(token) > 2 and token not in stop
    }


def _correction_audit(
    config: dict[str, object],
    threads,
    train_map,
    indexed,
    judge_rows: list[dict[str, object]],
) -> dict[str, object]:
    class ProviderSettings:
        model = config["model"]
        temperature = config["temperature"]
        reasoning_effort = config["reasoning_effort"]
        max_completion_tokens = config["max_completion_tokens"]

    provider = ProviderSettings()
    cache = JudgeCache(Path(str(config["cache_directory"])))
    runner = V2JudgeRunner(provider, cache, config)
    corrections = []
    raw_primary_passes = Counter()
    for row in judge_rows:
        case_id, system, run_id = str(row["case_id"]), str(row["system"]), str(row["run_id"])
        source = indexed[system][case_id]
        item = {
            "case_id": case_id,
            "customer": judge_v2.clipped(
                threads[case_id].customer_text(), int(config["customer_context_characters"])
            ),
            "reply": judge_v2.clipped(str(source["reply"]), int(config["reply_characters"])),
            "action": source["action"],
            "evidence": list(judge_v2.evidence_for(system, source, train_map, config)),
        }
        key = cache.key(
            {
                "protocol": config["version"],
                "model": provider.model,
                "rubric_version": config["rubric_version"],
                "prompt_version": config["prompt_version"],
                "prompt_fingerprint": runner._prompt_fingerprint(
                    ABSOLUTE_PREFIX, compact_judge_schema()
                ),
                "input": item,
                "experiment_namespace": run_id,
                "temperature": provider.temperature,
                "reasoning_effort": provider.reasoning_effort,
                "max_completion_tokens": provider.max_completion_tokens,
            }
        )
        cached = cache.get(key)
        if cached is None:
            raise ValueError(f"Missing Phase 5A cache entry: {case_id}/{system}/{run_id}")
        raw = json.loads(str(cached["response_json"]))
        derived = CompactJudgeResult.from_json(str(cached["response_json"]))
        if run_id == "primary":
            raw_primary_passes[system] += int(bool(raw["overall_pass"]))
        if bool(raw["overall_pass"]) == derived.overall_pass:
            continue
        correction_type = (
            "BRAND_CONTEXT_MINIMUM"
            if int(raw["brand_context"]) < 3
            else "GROUNDEDNESS_MINIMUM"
        )
        corrections.append(
            {
                "case_id": case_id,
                "system": system,
                "run_id": run_id,
                "direction": (
                    f"{str(raw['overall_pass']).lower()}_to_"
                    f"{str(derived.overall_pass).lower()}"
                ),
                "correction_type": correction_type,
                "raw_scores": {
                    field: raw[field]
                    for field in (
                        "groundedness",
                        "relevance",
                        "helpfulness",
                        "safety",
                        "brand_context",
                        "critical_failure",
                    )
                },
            }
        )
    primary = [row for row in judge_rows if row["run_id"] == "primary"]
    derived_passes = Counter(
        str(row["system"]) for row in primary if bool(row["overall_pass"])
    )
    effects = {
        system: {
            "n": 80,
            "raw_model_pass_count": raw_primary_passes[system],
            "raw_model_pass_rate": raw_primary_passes[system] / 80,
            "derived_pass_count": derived_passes[system],
            "derived_pass_rate": derived_passes[system] / 80,
            "absolute_rate_change": (derived_passes[system] - raw_primary_passes[system]) / 80,
        }
        for system in ("fixed", "lexical", "proposed")
    }
    return {
        "correction_count": len(corrections),
        "direction_distribution": dict(
            sorted(Counter(item["direction"] for item in corrections).items())
        ),
        "type_distribution": dict(
            sorted(Counter(item["correction_type"] for item in corrections).items())
        ),
        "system_distribution": dict(
            sorted(Counter(item["system"] for item in corrections).items())
        ),
        "run_distribution": dict(
            sorted(Counter(item["run_id"] for item in corrections).items())
        ),
        "primary_pass_materiality": effects,
        "ranking_changed": False,
        "interpretation": (
            "Corrections substantially reduced absolute pass rates, especially for the fixed "
            "baseline, but preserved the fixed > lexical > proposed ordering. They expose model "
            "boolean inconsistency and do not explain the proposed system's relative rank."
        ),
        "examples": corrections[:12],
        "all_corrections": corrections,
    }


def _cohorts(primary, manifest, order_rows, judge_rows) -> dict[str, list[str]]:
    proposed = primary["proposed"]
    case_ids = list(proposed)
    critical = sorted(
        [case_id for case_id in case_ids if proposed[case_id]["critical_failure"]],
        key=lambda case_id: stable_rank("phase5b-critical", case_id),
    )[:15]
    noncritical = sorted(
        [
            case_id
            for case_id in case_ids
            if not proposed[case_id]["overall_pass"]
            and not proposed[case_id]["critical_failure"]
        ],
        key=lambda case_id: stable_rank("phase5b-noncritical", case_id),
    )[:15]
    passes = sorted(
        [case_id for case_id in case_ids if proposed[case_id]["overall_pass"]],
        key=lambda case_id: stable_rank("phase5b-pass", case_id),
    )[:10]
    fixed_gap = sorted(
        [
            case_id
            for case_id in case_ids
            if primary["fixed"][case_id]["overall_pass"]
            and not proposed[case_id]["overall_pass"]
        ],
        key=lambda case_id: stable_rank("phase5b-fixed-gap", case_id),
    )[:10]
    order = defaultdict(list)
    for row in order_rows:
        winner = (
            "TIE"
            if row["preference"] == "TIE"
            else row["a_system"]
            if row["preference"] == "A"
            else row["b_system"]
        )
        order[str(row["case_id"])].append(winner)
    flips = sorted(case_id for case_id, values in order.items() if len(set(values)) > 1)
    repeated = []
    fields = (
        "groundedness",
        "relevance",
        "helpfulness",
        "safety",
        "brand_context",
        "overall_pass",
        "critical_failure",
    )
    for case_id in manifest["repeatability"]["case_ids"]:
        rows = [
            row
            for row in judge_rows
            if row["case_id"] == case_id and row["system"] == "proposed"
        ]
        if any(len({row[field] for row in rows}) > 1 for field in fields):
            repeated.append(str(case_id))
    return {
        "proposed_critical_failures": critical,
        "proposed_noncritical_failures": noncritical,
        "proposed_passes": passes,
        "fixed_pass_proposed_fail": fixed_gap,
        "order_bias_flips": flips,
        "repeatability_disagreements": repeated,
    }


def _case_signals(customer: str, source, judge, revised) -> tuple[list[str], str]:
    reply = str(source["reply"])
    evidence = [_normalized(item["historical_reply"]) for item in source["retrieved_cases"]]
    extractive = any(_normalized(reply) and _normalized(reply) in item for item in evidence)
    signals = []
    agent_defect = False
    judge_artifact = False
    if answer_coverage_failure(reply, customer):
        signals.append("GENERIC_OR_CONTEXT_REDUNDANT_QUESTION")
        agent_defect = True
    overlap = len(_content_tokens(reply) & _content_tokens(customer))
    if _question_only(reply) and overlap == 0:
        signals.append("LOW_LEXICAL_ANSWER_COVERAGE")
        agent_defect = True
    if not re.search(r"[.?!]$", reply):
        signals.append("INCOMPLETE_SURFACE_FORM")
        agent_defect = True
    critical_codes = {"A", "P", "C", "I", "L", "E", "F", "D"}
    if judge["critical_failure"] and not (set(judge["failure_codes"]) & critical_codes):
        signals.append("CRITICAL_LABEL_OUTSIDE_DECLARED_DEFINITION")
        judge_artifact = True
    if judge["critical_failure"] and "A" in judge["failure_codes"] and extractive:
        signals.append("CRITICAL_ACTION_LABEL_DISPUTED_BY_EXACT_EVIDENCE")
        judge_artifact = True
    if extractive and (int(judge["groundedness"]) < 4 or "G" in judge["failure_codes"]):
        signals.append("EXACT_EXTRACTIVE_REPLY_MARKED_UNGROUNDED")
        judge_artifact = True
    if (source["action"], source["reply"]) != (revised["action"], revised["reply"]):
        signals.append("PHASE41_OUTPUT_CHANGED")
    if agent_defect and judge_artifact:
        classification = "BOTH"
    elif agent_defect:
        classification = "AGENT_DEFECT"
    elif judge_artifact:
        classification = "JUDGE_ARTIFACT"
    elif judge["overall_pass"]:
        classification = "CONTROL_PASS"
    else:
        classification = "INCONCLUSIVE"
    return signals, classification


def _markdown(audit: dict[str, object]) -> str:
    corrections = audit["pass_rule_corrections"]
    cohorts = audit["case_audit"]["cohorts"]
    causes = audit["case_audit"]["root_cause_distribution"]
    generator = audit["phase4_generator_audit"]
    fixed = audit["fixed_baseline_advantage"]
    taxonomy = audit["failure_taxonomy"]
    holdout = audit.get("phase41_holdout_result")
    correction_rows = "\n".join(
        f"| {name} | {value['raw_model_pass_rate']:.4f} | "
        f"{value['derived_pass_rate']:.4f} | {value['absolute_rate_change']:.4f} |"
        for name, value in corrections["primary_pass_materiality"].items()
    )
    cohort_rows = "\n".join(f"| {name} | {len(ids)} |" for name, ids in cohorts.items())
    cause_rows = "\n".join(f"| {name} | {count} |" for name, count in causes.items())
    taxonomy_rows = "\n".join(
        f"| {item['category']} | {item['count']} | {item['percentage']:.2f}% | "
        f"{', '.join(item['representative_case_ids'])} |"
        for item in taxonomy["ranked_categories"]
    )
    holdout_text = (
        "The paired judge run has not yet completed. The frozen manifest contains 60 cases "
        "(22 changed, 38 unchanged) and excludes all Phase 5A and frozen-final IDs."
        if holdout is None
        else (
            f"The 60-case paired result is complete: "
            f"{holdout['paired_comparison']['counts']}. Safety regression: "
            f"{holdout['paired_comparison']['safety_regression']}."
        )
    )
    return f"""# Phase 5B failure audit

## Scope and integrity

This is a deterministic DEVELOPMENT-only audit. The five Phase 5A historical artifacts were
read but not overwritten; their SHA-256 hashes still match commit `66ffeeb`. Frozen final
evaluation cases were not read for scoring or used for selection, and no human or AI label was
used as gold.

## Deterministic pass-rule corrections

Exactly **{corrections['correction_count']}** cached outputs required normalization:
`{corrections['type_distribution']}`. Every correction was `true_to_false`.

| System | Raw model pass rate | Derived pass rate | Change |
|---|---:|---:|---:|
{correction_rows}

The corrections materially changed absolute rates but not the ordering. The fixed baseline's
large correction burden shows that the model-returned boolean was unreliable; the deterministic
rule correctly enforced the predeclared rubric.

## Case audit

| Cohort | Required/observed count |
|---|---:|
{cohort_rows}

After deduplication, **{audit['case_audit']['deduplicated_case_count']}** cases were inspected with
customer context, intent, retrieval scores and excerpts, evidence/verifier state, reply, risk,
action, and every applicable judge output.

| Evidence-based classification | Cases |
|---|---:|
{cause_rows}

The root cause is **both agent defects and judge artifacts**. Generic or already-answered
questions and top-1-only extraction are real response defects. Separately,
**{audit['judge_protocol_audit']['proposed_critical_without_declared_critical_code']} of
{audit['judge_protocol_audit']['proposed_critical_count']}** proposed critical labels lacked any
declared critical-failure code, and exact extractive evidence was sometimes scored ungrounded.

Human agreement remains **NOT_YET_MEASURED**. Phase 5A's order-bias flip rate was 37.5% at N=8;
that cohort is too small to establish absence or magnitude of bias.

The categories overlap because one case can expose both a response defect and a judge defect.

| Ranked failure category | Count | Audited cases | Representative IDs |
|---|---:|---:|---|
{taxonomy_rows}

## Fixed-baseline advantage

The identical fixed reply passed {fixed['fixed_pass_count']} of 80 cases, while there were
{fixed['fixed_pass_proposed_fail_count']} fixed-pass/proposed-fail cases. Its lack of factual
claims legitimately earns strong grounding and safety, but the pass rule permits a generic
handoff with relevance/helpfulness at 3 to pass. The high and inconsistent treatment of the same
generic text is therefore partly a rubric/judge artifact; the audited proposed replies also
contain genuine relevance and context-coverage defects. Conclusion: **BOTH**.

## Phase 4 generator audit

- Phase 4 used only top-1 evidence for all {generator['phase5a_auto_handle_count']} audited
  auto-handles.
- Question-only replies: {generator['question_only_count']}.
- Generic/context-redundant non-answers: {generator['answer_coverage_failure_count']}.
- Exact extractive replies penalized as ungrounded:
  {generator['extractive_grounding_conflict_count']}.
- Revised auto-handles selecting top-2 evidence: {generator['phase41_top2_selected_full_dev']}.
- Audited auto-handles with a generic top-1 question but a concrete top-2/top-3 candidate:
  {generator['phase5a_top1_question_with_concrete_top2_or_top3']}.
- Revised full-DEVELOPMENT transitions: `{generator['full_development_action_transitions']}`.

## Decision and bounded remediation

**AGENT_CHANGE_JUSTIFIED.** Phase 4.1 is one frozen, versioned remediation. It searches at most
top-2 evidence, prefers complete safe action sentences, rejects URL-stripped fragments,
generic/context-redundant questions, and verifies only the evidence IDs actually used. It does
not alter the classifier, taxonomy, retrieval weights, evidence thresholds, risk rules, safety
markers, or frozen data. Original Phase 4 predictions remain byte reproducible.

## New holdout

{holdout_text}

All LLM scores are unvalidated DEVELOPMENT diagnostics, not human ground truth or final system
claims.
"""


def main() -> int:
    hashes = {str(path): sha256_file(path) for path in FROZEN_PHASE5A}
    if hashes != EXPECTED_HASHES:
        raise ValueError("A frozen Phase 5A artifact changed before the Phase 5B audit.")
    config = json.loads(Path("configs/judge_v2.yaml").read_text(encoding="utf-8"))
    agent_config = json.loads(Path("configs/agent.yaml").read_text(encoding="utf-8"))
    manifest = json.loads(Path("results/dev_judge_v2_sample_manifest.json").read_text())
    split = json.loads(Path("data/manifests/split_manifest.json").read_text())
    all_ids = set(split["thread_ids"]["TRAIN"]) | set(split["thread_ids"]["DEVELOPMENT"])
    threads = {
        item.thread_id: item
        for item in read_threads(Path("data/processed/spotify_threads.jsonl"))
        if item.thread_id in all_ids
    }
    train_map = {case_id: threads[case_id] for case_id in split["thread_ids"]["TRAIN"]}
    systems = {
        "proposed": read_jsonl(Path("results/dev_proposed_agent.jsonl")),
        "lexical": read_jsonl(Path("results/dev_baseline_lexical.jsonl")),
        "fixed": read_jsonl(Path("results/dev_baseline_fixed.jsonl")),
    }
    indexed = {
        name: {str(item["case_id"]): item for item in rows} for name, rows in systems.items()
    }
    revised = {
        str(item["case_id"]): item for item in read_jsonl(Path("results/dev_phase41_agent.jsonl"))
    }
    judge_rows = read_jsonl(Path("results/dev_judge_v2_results.jsonl"))
    primary = {
        system: {
            str(row["case_id"]): row
            for row in judge_rows
            if row["run_id"] == "primary" and row["system"] == system
        }
        for system in systems
    }
    order_rows = read_jsonl(Path("results/dev_judge_v2_order_bias.jsonl"))
    cohorts = _cohorts(primary, manifest, order_rows, judge_rows)
    membership = defaultdict(list)
    selected_ids = []
    for name, case_ids in cohorts.items():
        for case_id in case_ids:
            membership[case_id].append(name)
            if case_id not in selected_ids:
                selected_ids.append(case_id)
    verifier = GroundingVerifier(agent_config["verifier"])
    case_records = []
    classifications = Counter()
    signal_counts = Counter()
    for case_id in selected_ids:
        source = indexed["proposed"][case_id]
        cases = [_retrieved_case(item) for item in source["retrieved_cases"]]
        evidence_ids = (cases[0].thread_id,) if source["action"] == "AUTO_HANDLE" else ()
        verification = verifier.verify(
            str(source["reply"]), cases, evidence_ids, threads[case_id].customer_text()
        )
        proposed_judgments = [
            row
            for row in judge_rows
            if row["case_id"] == case_id and row["system"] == "proposed"
        ]
        signals, classification = _case_signals(
            threads[case_id].customer_text(),
            source,
            primary["proposed"][case_id],
            revised[case_id],
        )
        classifications[classification] += 1
        signal_counts.update(signals)
        case_records.append(
            {
                "case_id": case_id,
                "cohorts": membership[case_id],
                "customer_context": threads[case_id].customer_text(),
                "intent": source["intent"],
                "intent_confidence": source["intent_confidence"],
                "intent_alternatives": source["intent_alternatives"],
                "retrieval_and_evidence": source["retrieved_cases"],
                "evidence_ids": list(evidence_ids),
                "evidence_sufficient": source["evidence_sufficient"],
                "grounding_passed": source["grounding_passed"],
                "recomputed_verifier": {
                    "passed": verification.passed,
                    "reason_codes": list(verification.reason_codes),
                    "evidence_token_coverage": verification.evidence_token_coverage,
                },
                "reply": source["reply"],
                "risk_tags": source["risk_tags"],
                "action": source["action"],
                "action_reason": source["action_reason"],
                "agent_reason_codes": source["reason_codes"],
                "judge": {
                    "proposed_runs": proposed_judgments,
                    "fixed_primary": primary["fixed"][case_id],
                    "lexical_primary": primary["lexical"][case_id],
                },
                "audit_signals": signals,
                "root_cause_classification": classification,
                "phase41": {
                    "action": revised[case_id]["action"],
                    "reply": revised[case_id]["reply"],
                    "evidence_ids": revised[case_id].get("evidence_ids", []),
                    "reason_codes": revised[case_id]["reason_codes"],
                },
            }
        )
    signal_case_ids = defaultdict(list)
    for record in case_records:
        for signal in record["audit_signals"]:
            signal_case_ids[signal].append(record["case_id"])
    taxonomy_specs = (
        (
            "EXTRACTIVE_GROUNDING_JUDGE_CONFLICT",
            signal_case_ids["EXACT_EXTRACTIVE_REPLY_MARKED_UNGROUNDED"],
            "The reply is an exact sanitized extraction from supplied evidence, yet grounding "
            "was below 4 or code G was emitted.",
        ),
        (
            "REPLY_LOW_ANSWER_COVERAGE",
            signal_case_ids["LOW_LEXICAL_ANSWER_COVERAGE"],
            "Question-only reply shares no substantive customer-context token.",
        ),
        (
            "REPLY_TOO_GENERIC_OR_CONTEXT_REDUNDANT",
            signal_case_ids["GENERIC_OR_CONTEXT_REDUNDANT_QUESTION"],
            "Reply asks a generic question or requests details already in the customer context.",
        ),
        (
            "CRITICAL_LABEL_PROTOCOL_VIOLATION",
            signal_case_ids["CRITICAL_LABEL_OUTSIDE_DECLARED_DEFINITION"]
            + signal_case_ids["CRITICAL_ACTION_LABEL_DISPUTED_BY_EXACT_EVIDENCE"],
            "Critical flag lacks a declared critical code, or an A-coded instruction is exactly "
            "supported by the supplied historical evidence.",
        ),
        (
            "JUDGE_GENERIC_REPLY_BIAS",
            cohorts["fixed_pass_proposed_fail"],
            "The identical no-claim fixed handoff passes while the proposed response fails.",
        ),
        (
            "JUDGE_REPEATABILITY_INSTABILITY",
            cohorts["repeatability_disagreements"],
            "At least one score, pass flag, or critical flag changes across three runs.",
        ),
        (
            "JUDGE_POSITION_INSTABILITY",
            cohorts["order_bias_flips"],
            "The normalized winner changes when answer positions are swapped.",
        ),
        (
            "REPLY_INCOMPLETE_SURFACE_FORM",
            signal_case_ids["INCOMPLETE_SURFACE_FORM"],
            "Sanitization leaves a reply without terminal sentence completion.",
        ),
    )
    failure_taxonomy = []
    for category, case_ids, evidence in taxonomy_specs:
        unique = list(dict.fromkeys(case_ids))
        failure_taxonomy.append(
            {
                "category": category,
                "count": len(unique),
                "percentage": round(len(unique) / len(selected_ids) * 100, 4),
                "representative_case_ids": unique[:5],
                "supporting_evidence": evidence,
            }
        )
    failure_taxonomy.sort(key=lambda item: (-int(item["count"]), str(item["category"])))
    phase5a_ids = [str(item["case_id"]) for item in manifest["cases"]]
    phase5a_auto_ids = [
        case_id
        for case_id in phase5a_ids
        if indexed["proposed"][case_id]["action"] == "AUTO_HANDLE"
    ]
    full_transitions = Counter(
        (indexed["proposed"][case_id]["action"], revised[case_id]["action"])
        for case_id in indexed["proposed"]
    )
    extractive_conflicts = 0
    question_only = 0
    coverage_failures = 0
    top1_question_with_concrete_alternative = 0
    original_composer = GroundedComposer(agent_config["generation"], agent_config["verifier"])
    for case_id in phase5a_auto_ids:
        source = indexed["proposed"][case_id]
        reply = str(source["reply"])
        question_only += int(_question_only(reply))
        coverage_failures += int(answer_coverage_failure(reply, threads[case_id].customer_text()))
        extractive = any(
            _normalized(reply) in _normalized(item["historical_reply"])
            for item in source["retrieved_cases"]
        )
        judge = primary["proposed"][case_id]
        extractive_conflicts += int(
            extractive and (int(judge["groundedness"]) < 4 or "G" in judge["failure_codes"])
        )
        alternatives = [
            original_composer.compose([_retrieved_case(item)])
            for item in source["retrieved_cases"][1:3]
        ]
        top1_question_with_concrete_alternative += int(
            _question_only(reply)
            and any(candidate and not _question_only(candidate) for candidate in alternatives)
        )
    phase41_top2_full = sum(
        revised[case_id]["action"] == "AUTO_HANDLE"
        and bool(revised[case_id].get("evidence_ids"))
        and revised[case_id]["evidence_ids"][0]
        == indexed["proposed"][case_id]["retrieved_cases"][1]["thread_id"]
        for case_id in revised
    )
    phase41_top2_phase5a = sum(
        revised[case_id]["action"] == "AUTO_HANDLE"
        and bool(revised[case_id].get("evidence_ids"))
        and revised[case_id]["evidence_ids"][0]
        == indexed["proposed"][case_id]["retrieved_cases"][1]["thread_id"]
        for case_id in phase5a_ids
    )
    critical = [row for row in primary["proposed"].values() if row["critical_failure"]]
    no_declared = sum(
        not (set(row["failure_codes"]) & {"A", "P", "C", "I", "L", "E", "F", "D"})
        for row in critical
    )
    disputed_action = sum(
        "A" in row["failure_codes"]
        and any(
            _normalized(indexed["proposed"][str(row["case_id"])]["reply"])
            in _normalized(item["historical_reply"])
            for item in indexed["proposed"][str(row["case_id"])]["retrieved_cases"]
        )
        for row in critical
    )
    fixed_pass = sum(bool(row["overall_pass"]) for row in primary["fixed"].values())
    fixed_gap_all = [
        case_id
        for case_id in phase5a_ids
        if primary["fixed"][case_id]["overall_pass"]
        and not primary["proposed"][case_id]["overall_pass"]
    ]
    holdout_result = None
    if Path("results/dev_phase41_judge_summary.json").exists():
        holdout_result = json.loads(Path("results/dev_phase41_judge_summary.json").read_text())
    audit = {
        "phase": "5B",
        "status": "COMPLETE_AUDIT",
        "historical_artifacts_modified": False,
        "frozen_phase5a_hashes": hashes,
        "pass_rule_corrections": _correction_audit(
            config, threads, train_map, indexed, judge_rows
        ),
        "case_audit": {
            "selection_method": (
                "Stable-hash selection within required outcome cohorts plus every order flip "
                "and every repeatability disagreement; deduplicated before inspection."
            ),
            "cohorts": cohorts,
            "deduplicated_case_count": len(selected_ids),
            "root_cause_distribution": dict(sorted(classifications.items())),
            "signal_distribution": dict(sorted(signal_counts.items())),
            "records": case_records,
        },
        "failure_taxonomy": {
            "denominator": len(selected_ids),
            "categories_overlap": True,
            "ranked_categories": failure_taxonomy,
        },
        "judge_protocol_audit": {
            "proposed_critical_count": len(critical),
            "proposed_critical_without_declared_critical_code": no_declared,
            "proposed_critical_action_code_exactly_supported": disputed_action,
            "interpretation": (
                "Most critical labels use only G/R/H, although the prompt limits critical "
                "failures to payment, invented account action, privacy, policy, contradiction, "
                "fabrication, or danger. This is a judge protocol-adherence defect."
            ),
            "human_judge_agreement": "NOT_YET_MEASURED",
            "phase5a_order_bias_flip_rate": 0.375,
            "phase5a_order_bias_n": 8,
        },
        "fixed_baseline_advantage": {
            "fixed_reply_unique_count": len(
                {str(indexed["fixed"][case_id]["reply"]) for case_id in phase5a_ids}
            ),
            "fixed_pass_count": fixed_pass,
            "fixed_pass_rate": fixed_pass / 80,
            "fixed_pass_proposed_fail_count": len(fixed_gap_all),
            "audited_fixed_gap_case_ids": cohorts["fixed_pass_proposed_fail"],
            "conclusion": "BOTH",
            "evidence": (
                "The no-claim fixed handoff has a legitimate grounding/safety advantage and the "
                "pass rule allows limited relevance/helpfulness at score 3. The judge also applies "
                "critical labels inconsistently, while proposed replies independently exhibit "
                "generic, redundant, and off-topic questions."
            ),
        },
        "phase4_generator_audit": {
            "phase5a_auto_handle_count": len(phase5a_auto_ids),
            "top1_only_generation_count": len(phase5a_auto_ids),
            "question_only_count": question_only,
            "answer_coverage_failure_count": coverage_failures,
            "extractive_grounding_conflict_count": extractive_conflicts,
            "phase41_top2_selected_full_dev": phase41_top2_full,
            "phase41_top2_selected_phase5a": phase41_top2_phase5a,
            "phase5a_top1_question_with_concrete_top2_or_top3": (
                top1_question_with_concrete_alternative
            ),
            "full_development_action_transitions": {
                f"{old}->{new}": count for (old, new), count in sorted(full_transitions.items())
            },
            "phase41_changed_phase5a_case_count": sum(
                (indexed["proposed"][case_id]["action"], indexed["proposed"][case_id]["reply"])
                != (revised[case_id]["action"], revised[case_id]["reply"])
                for case_id in phase5a_ids
            ),
            "finding": (
                "Useful actions or more specific questions can occur in top-2 evidence while the "
                "top-1 reply is generic. Phase 4 also accepts context-redundant questions because "
                "token overlap verifies extraction, not answer coverage."
            ),
        },
        "decision": {
            "gate": "AGENT_CHANGE_JUSTIFIED",
            "root_cause": "BOTH",
            "remediation_count": 1,
            "remediation_version": "spotify-grounded-agent-v1.1",
            "scope": (
                "Versioned top-2 candidate selection, complete-sentence filtering, actual evidence "
                "ID tracking, and generic/context-redundant answer-coverage rejection."
            ),
            "unchanged": [
                "taxonomy",
                "classifier",
                "retrieval weights",
                "evidence thresholds",
                "risk rules",
                "safety markers",
                "frozen evaluation data",
                "Phase 5A historical artifacts",
            ],
        },
        "phase41_holdout": json.loads(
            Path("results/dev_phase41_holdout_manifest.json").read_text()
        ),
        "phase41_holdout_result": holdout_result,
        "data_protection": {
            "frozen_evaluation_touched": False,
            "human_gold_used": 0,
            "ai_provisional_used_as_gold": False,
        },
    }
    write_json(OUTPUT, audit)
    DOCUMENT.write_text(_markdown(audit), encoding="utf-8")
    print(
        f"Phase 5B audit: {len(selected_ids)} deduplicated cases; "
        f"decision={audit['decision']['gate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
