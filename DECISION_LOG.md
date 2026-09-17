# Decision log

| ID | Decision | Status | Rationale |
| --- | --- | --- | --- |
| ADR-01 | Build independently rather than importing either reference repository. | Accepted | Assignment integrity requires citations and forbids silent copying. |
| ADR-02 | Treat assignment documents as constraints, not as evidence of dataset results. | Accepted | No unmeasured statistics or claims should enter the report. |
| ADR-03 | Make all data-dependent choices provisional until profiling. | Accepted | Brand, taxonomy, split and retrieval choices require evidence. |
| ADR-04 | Use thread-level isolation for every evaluation partition. | Accepted | Tweet-level splits would leak conversational context. |
| ADR-05 | Fail closed for private, account-specific, security, payment, or weak-evidence cases. | Accepted | Historical data cannot authorize current/account actions. |
| ADR-06 | Defer model, prompt, and threshold decisions. | Pending Phase 1–4 | These need data profiling and development-only calibration. |
| ADR-07 | Require a genuine LLM quality judge plus actual human comparison. | Accepted | A deterministic proxy alone does not satisfy the brief. |

This log will grow to 10–15 non-obvious decisions as evidence is collected.
