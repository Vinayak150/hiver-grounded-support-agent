# Phase 4 deterministic safety policy

## Decision rule

`AUTO_HANDLE` requires all of the following: classifier confidence and margin at
or above their configured DEVELOPMENT heuristics; adequate retrieval and customer
similarity; at least 60% predicted-intent agreement among retrieved cases; no
excessive template concentration; no risk tag; a non-empty evidence-preserving
draft; valid TRAIN evidence references; and a passing grounding/safety verifier.
Every other case returns the fixed safe handoff with `ESCALATE`.

Historical replies are evidence of prior public responses, not authority for
current policy, account state, payment state, or completed action.

## Escalation reasons

- `LOW_INTENT_CONFIDENCE`: classifier confidence is below the calibrated heuristic.
- `AMBIGUOUS_INTENT`: the top-two probability margin is too small or uncertainty is high.
- `INSUFFICIENT_EVIDENCE`: top retrieval evidence or customer similarity is too weak.
- `INTENT_RETRIEVAL_MISMATCH`: fewer than 60% of retrieved cases match the predicted intent.
- `TEMPLATE_CONCENTRATION`: one exact historical reply dominates retrieved evidence.
- `SECURITY_RISK`: compromise, breach, hacking, or unauthorized access is indicated.
- `PAYMENT_ACTION_REQUIRED`: a charge, refund, or predicted billing/payment intent may require protected action.
- `PRIVATE_ACCOUNT_REQUIRED`: private lookup, PII, login, subscription, account state, or predicted account/security intent is involved.
- `UNSUPPORTED_POLICY_RISK`: a current eligibility, licensing, country, or policy claim is needed.
- `LOW_CONTEXT`: five or fewer lexical tokens do not provide enough context.
- `GROUNDING_FAILURE`: too little of the draft is supported by retrieved evidence.
- `PII_LEAK`: a handle, URL, email-like value, or long identifier remains in the draft.
- `UNSUPPORTED_ACTION_CLAIM`: the draft says Spotify performed an unverified action.
- `MISSING_EVIDENCE`: a draft lacks usable historical support evidence.
- `INVALID_EVIDENCE_REFERENCE`: a referenced source is not in the retrieved set.

The rules are deliberately inspectable and conservative. Keyword matches are
phrase-based where an isolated generic term would be overly broad; nevertheless,
these DEVELOPMENT diagnostics do not establish real-world safety.
