# Phase 5A LLM judge protocol

## Scientific status

Protocol V1 used Groq `openai/gpt-oss-120b` but stopped at 313 of 880 planned
judgments because of provider quota. Those partial outputs remain in the ignored
cache for auditability but were never finalized or inspected to select V2 cases or
thresholds. They are excluded from every reported comparison.

Protocol V2 was declared as a quota-safe resource-constrained protocol before V2
results were analyzed. It uses Groq `openai/gpt-oss-20b` for every final Phase 5A
judgment and preserves the five-dimension `support-response-rubric-v1`. All V2
outputs are labeled **UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS**.

## Blinding, sample, and prompt

The V2 sample contains exactly 80 DEVELOPMENT IDs: every one of the 65 proposed
`AUTO_HANDLE` cases and 15 deterministic `ESCALATE` cases selected by stable-hash
round-robin strata over predicted intent, evidence sufficiency, risk presence, and
lexical challenge flags. All three systems use the same IDs. Frozen final cases,
human annotations, AI provisional labels, system names, expected answers, and
earlier judgments are absent from provider inputs.

The byte-stable compact prompt places the role, rubric, pass rule, critical-failure
definitions, and output contract before case-specific content. The case suffix has
only sanitized customer context, candidate reply, action, and at most two concise
TRAIN evidence excerpts. Cache keys include model, rubric and prompt versions,
exact input, settings, experiment namespace, and a prompt/schema fingerprint.

The judge returns five 1–5 scores, critical failure, short failure codes, and a
brief rationale under strict JSON schema. `overall_pass` is deterministically
derived from the validated scores and critical-failure flag according to the
rubric; corrections of inconsistent returned booleans are counted in the run
manifest. Temperature is zero, reasoning effort is low, and maximum completion is
256 tokens.

## Validity diagnostics

Main judging is 80 cases × three systems, ordered proposed, lexical, then fixed.
Repeatability uses 12 predeclared proposed-agent cases (eight `AUTO_HANDLE`, four
`ESCALATE`) and three passes; the main result is pass one and two independent
namespaces provide the extra 24 calls. This N=12 result is LLM self-consistency,
not human agreement.

Order bias uses eight predeclared cases and two anonymous proposed-vs-lexical calls
with swapped positions. N=8 has limited power; a low flip rate could not establish
absence of bias.

## Protection and interpretation

The provider credential is environment-only. Every validated response is cached
immediately; credentials are never serialized. The 200 frozen final-evaluation
IDs remain untouched, human gold used is zero, and AI provisional labels are not
truth. No Phase 4 threshold is tuned from these results.

V2 is a smaller, deliberately automation-heavy DEVELOPMENT diagnostic. It cannot
support final accuracy, safety, trustworthiness, or superiority claims. Human
agreement remains `NOT_YET_MEASURED` and must be collected independently later.
