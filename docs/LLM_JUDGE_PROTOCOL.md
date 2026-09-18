# Phase 5A LLM judge protocol

## Blinding and inputs

Each request contains only the rubric, case ID, customer context, response, action,
retrieved TRAIN evidence excerpts, and evidence IDs. System names, expected
answers, earlier judgments, frozen labels, and AI provisional labels are excluded.
System identity is attached only after the provider returns a validated judgment.

## DEVELOPMENT sampling

The deterministic sample contains 200 shared DEVELOPMENT case IDs. All 65 proposed
`AUTO_HANDLE` cases are included. The other 135 cases are selected by stable hash
and round-robin strata over predicted intent, evidence sufficiency, risk presence,
and challenge-like lexical characteristics. All three systems use these same IDs.

Repeatability uses a stable 100-case proposed-agent subset and three passes. The
first pass reuses the primary cached judgment; passes two and three are explicit
repeatability replicates. This intentional exception receives separate cache
namespaces while preserving the exact same blinded prompt. It is reported as LLM
self-consistency, never human agreement.

Order bias uses 40 stable cases comparing lexical and proposed responses. A stable
hash decides which anonymous response is A in the first call; the second call swaps
the order. Preference-flip rate is reported. Provider inputs never include system
names.

## Provider, validation, and cache

The OpenAI-compatible adapter uses a configured model, temperature 0, strict JSON
schema, a 60-second timeout, and at most two retries after the initial attempt.
Credentials and optional base URLs come from environment variables. Cache keys
cover model, rubric/prompt versions, exact blinded input, and experiment namespace.
Validated responses and provider-reported token usage are cached; credentials are
never serialized. Cost remains null unless explicit pricing and provider usage are
both available.

As of the Phase 5A infrastructure commit, no supported credential is configured.
Therefore only the protected sample manifest is generated; judge result,
repeatability, order-bias, and score-summary artifacts must not be fabricated.

## Interpretation

Future outputs must be labeled **UNVALIDATED LLM-JUDGE DEVELOPMENT DIAGNOSTICS**.
They cannot support final accuracy, safety, trustworthiness, human agreement, or a
headline metric. `HUMAN_JUDGE_AGREEMENT_STATUS` remains `NOT_YET_MEASURED`.
