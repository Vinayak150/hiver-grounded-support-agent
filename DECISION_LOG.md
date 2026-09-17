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
| ADR-08 | Use canonical parent linkage for reconstruction, with child-link fields retained only for consistency checks. | Accepted | A reply has at most one parent; child fields can be plural, absent, or inconsistent. The actual dataset schema will be validated before profiling. |
| ADR-09 | Use SQLite as an ephemeral profiling index rather than loading the full TWCS export into memory. | Accepted | It supports deterministic joins, anomaly checks, and a multi-million-row CSV on ordinary hardware without committing raw data or adding distributed infrastructure. |
| ADR-10 | Select a brand by configured eligibility gates and deterministic, visible tie-breaks—not a hidden composite score. | Accepted | The assignment requires raw evidence and stated trade-offs; selection remains blocked until real data is profiled. |
| ADR-11 | Parse TWCS `created_at` values with the Twitter timestamp format in addition to ISO 8601. | Accepted | The supplied data uses `Tue Oct 31 22:10:47 +0000 2017`; without this parser every timestamp would have been falsely counted as invalid. |
| ADR-12 | Exclude replies containing a clarifying question from the generic/redirect proxy. | Accepted | Manual deterministic samples showed that apology-plus-question responses were public diagnostic engagement, not generic deflection. A regression test protects this distinction. |
| ADR-13 | Select `AmazonHelp` for Phase 2 preparation. | Accepted | Among 101 volume-eligible accounts, the predeclared lexicographic rule selected it with 51,260 reconstructed multi-turn threads, 90.9109% unique normalized replies, and 9.0891% exact duplicate replies. Its weaker 77.7408% public-containment proxy is an explicit trade-off. |

This log will grow to 10–15 non-obvious decisions as evidence is collected.
