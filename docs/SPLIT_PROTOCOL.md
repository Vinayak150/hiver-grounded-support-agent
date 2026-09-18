# Phase 2 Split Protocol

## Unit and source

The split unit is the canonical reconstructed `thread_id`. The source is the
28,277-thread usable SpotifyCares corpus with SHA-256
`8847bea00fee7f7686c37231269594b31dd79d53abc7c5fff504a49cafabac92`.
No message row is assigned independently.

## Strategy decision

Phase 2 evaluated deterministic-random and chronological 70/15/15 starts. The
random alternative produced 19,753 TRAIN, 4,316 DEVELOPMENT, and 4,208
GOLDEN_CANDIDATE threads spread across the full date range. Chronological splitting
was selected before any model existed because it better simulates later unseen
tickets and prevents selection based on favorable accuracy.

The initial chronological assignment was 19,793 / 4,241 / 4,243. After later-split
decontamination, the frozen counts are:

| Split | Threads | Time range |
| --- | ---: | --- |
| TRAIN | 19,793 | 2013-09-18T19:23:17Z to 2017-11-16T00:35:28Z |
| DEVELOPMENT | 2,594 | 2017-11-16T00:51:32Z to 2017-11-25T18:23:15Z |
| GOLDEN_CANDIDATE | 2,619 | 2017-11-25T18:27:25Z to 2017-12-03T22:07:39Z |

DEVELOPMENT may later support model and threshold selection. GOLDEN_CANDIDATE may
only supply blinded human-evaluation candidates and must never enter training,
retrieval, demonstrations, prompt examples, threshold tuning, or taxonomy fitting.

## Leakage controls

Exact checks cover every normalized customer message, normalized customer-thread
prefix, and Spotify reply of at least eight words. High-similarity checks use
bottom-k character 5-gram blocking followed by exact token-Jaccard and character
5-gram-Jaccard measurement. Thresholds are 0.90 and 0.92 respectively and are
versioned in `configs/splits.yaml`.

The initial boundaries exposed 2,206 later-split exact conflicts and 8,311
near-duplicate pairs affecting 1,065 later-split threads. The policy retained the
earlier chronological thread and excluded the later thread. The independent final
audit found zero exact and zero detected near-duplicate collisions across protected
boundaries.

This intentionally removes many repeated Spotify reply templates. Very short
common language remains subject to exact checking; near-duplicate analysis requires
at least four distinct tokens to avoid treating ordinary short phrases as the same
case.

## Reproducibility

`make splits` regenerates the ID manifest, while `make leakage-audit` independently
rechecks the final boundaries. Generated timestamps are excluded; ordering,
hashing, thresholds, and tie-breaking are deterministic.
