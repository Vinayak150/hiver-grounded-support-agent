# SpotifyCares Intent Taxonomy

## Status and provenance

Version `spotify-intents-v1` is a provisional Phase 2 annotation taxonomy for the
frozen `SpotifyCares` corpus. It was informed only by the 19,793 TRAIN threads in
split version `spotify-temporal-v1`. DEVELOPMENT and GOLDEN_CANDIDATE text did not
enter TF-IDF fitting, clustering, signal counts, representative selection, or
boundary drafting.

The deterministic exploration used word unigram/bigram TF-IDF, 12-cluster KMeans
with random state `20260918`, cluster sizes, centroid-nearest thread IDs, lexical
signal counts, and pairwise top-token overlap. Codex GPT-5 assisted in interpreting
the aggregate cluster terms and drafting operational boundaries. That assistance
is recorded in `results/taxonomy_exploration.json`; it did not create human labels.
No external candidate taxonomy was used.

Support counts below are deterministic TRAIN-side lexical-group counts. They are
evidence of data support, not gold intent frequencies or classifier labels.

| ID | Display name | TRAIN support | Short definition |
| --- | --- | ---: | --- |
| `playback_or_app_behavior` | Playback or app behavior | 6,022 | Playback failures, crashes, slowness, offline behavior, or unexpected app operation. |
| `device_or_connectivity` | Device or connectivity | 1,111 | Device, operating-system, network, casting, synchronization, or installation problems. |
| `account_access_or_security` | Account access or security | 2,566 | Login, password, identity, unauthorized access, and recovery concerns. |
| `subscription_or_plan` | Subscription or plan | 2,431 | Premium state, trials, family/student plans, invitations, upgrades, or cancellation. |
| `billing_or_payment` | Billing or payment | 1,215 | Charges, payment methods, receipts, gift cards, refunds, and billing disputes. |
| `library_playlist_or_saved_content` | Library, playlist, or saved content | 491 | User collections, playlists, saved songs, downloads, local files, and missing saved state. |
| `content_availability_or_metadata` | Content availability or metadata | 1,356 | Catalog availability, releases, artist pages, lyrics, podcasts, or incorrect metadata. |
| `feature_request_or_product_feedback` | Feature request or product feedback | 586 | Requests for new capabilities, interface changes, and product feedback. |
| `other_or_unclear` | Other, unclear, or non-support | 4,015 | Low-context, ambiguous, multi-intent, non-support, or unsupported cases. |

## Intent boundaries

### `playback_or_app_behavior`

- Include when making playback or the Spotify app function is the primary need.
- Exclude device/network handoff problems that fit `device_or_connectivity`.
- Boundary: an operating-system-only crash remains here unless external-device
  integration is causal.
- TRAIN examples: `twcs-17c57e153e12cd220a46`,
  `twcs-468c3f2bcb3741840fd7`, `twcs-57ccf7d063cefe9be297`,
  `twcs-3446d661947eff20aafa`, `twcs-ca1a066a0ca788baebaa`.

### `device_or_connectivity`

- Include when a device, OS, network, speaker, console, car, or cross-device
  connection is central.
- Exclude ordinary playback behavior without an integration boundary.
- Boundary: device context alone is insufficient; it must be central to the issue.
- TRAIN examples: `twcs-ea724e920de31f51e05b`,
  `twcs-9c9a719a823860e11e3d`, `twcs-1723a43c317aba734624`,
  `twcs-5aad50c4695d1525c681`, `twcs-ff529d3ce0e21994e678`.

### `account_access_or_security`

- Include login, password, email identity, compromise, and recovery issues.
- Exclude working accounts whose problem is only plan entitlement.
- Boundary: ownership and security cases generally require escalation even when
  intent is unambiguous.
- TRAIN examples: `twcs-f6cad043044f9a9567dc`,
  `twcs-de4af99d0b822190dc9f`, `twcs-ed81e547ae9a3f63cc6f`,
  `twcs-e5d6b5dc18190c34d240`, `twcs-174e65e820b657d2d99b`.

### `subscription_or_plan`

- Include plan eligibility, membership state, invitations, upgrades, and
  cancellation.
- Exclude charge, receipt, payment-method, and refund disputes.
- Boundary: missing Premium entitlement is a plan issue unless a completed charge
  is the central dispute.
- TRAIN examples: `twcs-362669d1ccad84c3f586`,
  `twcs-431671dc99da81476226`, `twcs-22e4a3ef128ef4e99faa`,
  `twcs-277122a1953954c57ee3`, `twcs-a64f3fd580be5eac9aa6`.

### `billing_or_payment`

- Include money movement, charges, cards, gift cards, receipts, and refunds.
- Exclude plan-feature questions without a transaction problem.
- Boundary: transaction-specific cases normally require private lookup or action.
- TRAIN examples: `twcs-3768d867cce9ed811638`,
  `twcs-44be3305c4a504c1fc45`, `twcs-fbdd0ef288970147a842`,
  `twcs-aa507b58475f40729b4a`, `twcs-30e7f65366dc2b0e79e5`.

### `library_playlist_or_saved_content`

- Include user-created collections, saved state, downloads, and local files.
- Exclude globally missing catalog items or metadata defects.
- Boundary: missing saved items are library issues; globally unavailable tracks
  are catalog issues.
- TRAIN examples: `twcs-9f80c5eb98831380cc90`,
  `twcs-e8e439563ede20eba477`, `twcs-42c9f97318809472b359`,
  `twcs-5cb54cc78007c0029b0f`, `twcs-45ab3795f6754668e9af`.

### `content_availability_or_metadata`

- Include missing catalog items, artist pages, releases, lyrics, podcasts, and
  metadata corrections.
- Exclude personal playlist/library-state loss.
- Boundary: licensing and metadata cases may be policy-sensitive or need
  escalation despite a clear intent.
- TRAIN examples: `twcs-dd43c0af73858ee69045`,
  `twcs-645df514787baf8ae6ba`, `twcs-82494e3b0b321816acfb`,
  `twcs-bdc0ea7f54b66838edc1`, `twcs-d409fe6227f7979f8bef`.

### `feature_request_or_product_feedback`

- Include new-capability requests, interface feedback, and availability questions.
- Exclude a concrete malfunction, account issue, or transaction problem.
- Boundary: restoring an intentionally removed feature is feedback; a failed
  existing feature is not.
- TRAIN examples: `twcs-d940cdcda1b3e3891dee`,
  `twcs-3336c37c84b43d550ce5`, `twcs-c0133177cd44e2e4b2d9`,
  `twcs-75dbc739cf8624b964c2`, `twcs-51a861e252982069aa0b`.

### `other_or_unclear`

- Include noise, low context, true multi-intent, non-support, and unsupported cases.
- Exclude any case with a sufficiently clear primary operational intent.
- Boundary: this class intentionally preserves later abstention rather than
  forcing every message into a support category.
- TRAIN examples: `twcs-17246b47b3a1ca35c166`,
  `twcs-fe3364daa61024355b52`, `twcs-131fec1a0836422ba920`,
  `twcs-bd518b8450f1b434e4b7`, `twcs-bda316f48686406724a9`.

## Freeze rule

The taxonomy may be clarified after a user-completed 20-case pilot, but it must not
be tuned against final golden results. Any post-pilot change requires a version
bump, decision-log entry, and explicit migration of affected human labels.
