# Minimum information for Phase 1

Phase 1 needs a permitted local copy of the Kaggle **Customer Support on Twitter (TWCS)** data, or equivalent documented access. Do not infer statistics before reading it.

Required raw fields (or an unambiguous mapping):

- unique tweet/message ID;
- author or account identifier/name;
- inbound/customer-versus-brand flag;
- message text;
- response-to or conversation lineage ID;
- timestamp or deterministic chronology field;
- brand identity sufficient to identify the support account.

Also required:

- dataset version/source URL and download date;
- license/usage confirmation appropriate for the assignment;
- encoding, delimiter, and null-value conventions;
- an expected file checksum when available;
- permission to retain a small derived, non-sensitive reproducibility sample if the raw export cannot be committed.

With those inputs, Phase 1 can profile schema and reconstructability, generate candidate-brand comparison artifacts, and recommend—not assume—a brand.
