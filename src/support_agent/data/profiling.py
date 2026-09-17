"""Deterministic Phase 1 profiling and transparent brand selection evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from .loader import TwcsCsvLoader
from .threads import ThreadIndex, ThreadSummary


@dataclass(frozen=True)
class ProfilingConfig:
    """Documented, non-optimised profiling parameters from YAML."""

    source_dataset_name: str
    source_url: str
    minimum_outbound_messages: int
    minimum_substantive_word_count: int
    top_template_count: int
    generic_or_redirect_terms: tuple[str, ...]
    actionable_terms: tuple[str, ...]
    selection_priority: tuple[str, ...]


@dataclass(frozen=True)
class BrandProfile:
    """Raw and explicitly heuristic signals for one eligible outbound account."""

    brand: str
    brand_authored_messages: int
    unique_inbound_customer_messages_linked: int
    linked_customer_brand_pairs: int
    brand_related_threads: int
    reconstructible_multi_turn_threads: int
    outbound_parent_link_completeness: float | None
    outbound_orphan_parent_rate: float | None
    median_outbound_word_count: float | None
    substantive_reply_proxy_fraction: float | None
    generic_or_redirect_reply_proxy_fraction: float | None
    actionable_reply_proxy_fraction: float | None
    public_containment_proxy_fraction: float | None
    exact_normalized_duplicate_reply_rate: float | None
    unique_normalized_reply_ratio: float | None
    top_template_concentration: float | None
    unique_normalized_customer_message_ratio: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileResult:
    """Output metadata; raw tweet text is intentionally never included."""

    manifest_path: Path
    profile_csv_path: Path
    profile_json_path: Path
    brand_report_path: Path
    summary: ThreadSummary
    selected_brand: str | None
    eligible_candidates: int


def load_config(path: Path) -> ProfilingConfig:
    """Load and validate the small Phase 1 configuration surface."""

    # JSON is a strict, portable subset of YAML. Keeping this configuration in
    # JSON-compatible YAML avoids a runtime dependency for a single small file.
    with path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("Profiling configuration must be a JSON-compatible YAML mapping.")
    heuristics = raw.get("heuristics", {})
    selection = raw.get("selection", {})
    if not isinstance(heuristics, dict) or not isinstance(selection, dict):
        raise ValueError("profiling.yaml requires mapping values for heuristics and selection.")
    config = ProfilingConfig(
        source_dataset_name=str(raw.get("source_dataset_name", "")).strip(),
        source_url=str(raw.get("source_url", "")).strip(),
        minimum_outbound_messages=int(selection.get("minimum_outbound_messages", 500)),
        minimum_substantive_word_count=int(heuristics.get("minimum_substantive_word_count", 8)),
        top_template_count=int(heuristics.get("top_template_count", 5)),
        generic_or_redirect_terms=tuple(
            str(item).casefold() for item in heuristics.get("generic_or_redirect_terms", [])
        ),
        actionable_terms=tuple(
            str(item).casefold() for item in heuristics.get("actionable_terms", [])
        ),
        selection_priority=tuple(
            str(item)
            for item in selection.get(
                "priority",
                [
                    "reconstructible_multi_turn_threads",
                    "public_containment_proxy_fraction",
                    "unique_normalized_reply_ratio",
                    "brand_authored_messages",
                ],
            )
        ),
    )
    if not config.source_dataset_name or not config.source_url:
        raise ValueError("profiling.yaml must identify the source dataset name and URL.")
    if config.minimum_outbound_messages < 1 or config.minimum_substantive_word_count < 1:
        raise ValueError("Eligibility and substantive-word thresholds must be positive.")
    if config.top_template_count < 1:
        raise ValueError("top_template_count must be positive.")
    if not config.selection_priority:
        raise ValueError("selection.priority must contain at least one metric.")
    return config


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fraction(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 8)


def reply_proxy_flags(
    text: str, words: int, config: ProfilingConfig
) -> tuple[bool, bool, bool, bool]:
    """Apply narrow, documented reply proxies without treating questions as generic replies.

    A generic/apology/redirect phrase alone is insufficient: a response asking a
    substantive clarifying question is evidence of public engagement, even if it
    also contains an apology. This remains a proxy, not a resolution label.
    """

    actionable = any(term in text for term in config.actionable_terms)
    generic_hint = any(term in text for term in config.generic_or_redirect_terms)
    generic_or_redirect = generic_hint and not actionable and "?" not in text
    substantive = words >= config.minimum_substantive_word_count
    public_containment = substantive and not generic_or_redirect
    return substantive, actionable, generic_or_redirect, public_containment


def _median_words(index: ThreadIndex, brand: str, count: int) -> float | None:
    if not count:
        return None
    offsets = [count // 2] if count % 2 else [count // 2 - 1, count // 2]
    values = [
        int(
            index.connection.execute(
                """
                SELECT word_count FROM messages
                WHERE author_id = ? AND inbound = 0
                ORDER BY word_count, tweet_id LIMIT 1 OFFSET ?
                """,
                (brand, offset),
            ).fetchone()[0]
        )
        for offset in offsets
    ]
    return float(median(values))


def _linked_inbound_cte() -> str:
    """Return a reusable CTE identifying inbound messages directly linked to a brand."""

    return """
        WITH linked_inbound AS (
            SELECT customer.tweet_id AS customer_id, brand.tweet_id AS brand_id
            FROM messages AS brand
            JOIN messages AS customer ON customer.parent_id = brand.tweet_id
            WHERE brand.author_id = ? AND brand.inbound = 0 AND customer.inbound = 1
            UNION
            SELECT customer.tweet_id AS customer_id, brand.tweet_id AS brand_id
            FROM messages AS brand
            JOIN messages AS customer ON brand.parent_id = customer.tweet_id
            WHERE brand.author_id = ? AND brand.inbound = 0 AND customer.inbound = 1
        )
    """


def _profile_brand(
    index: ThreadIndex, brand: str, outbound_count: int, config: ProfilingConfig
) -> BrandProfile:
    connection = index.connection
    linked_cte = _linked_inbound_cte()
    linked_counts = connection.execute(
        linked_cte + "SELECT COUNT(DISTINCT customer_id), COUNT(*) FROM linked_inbound",
        (brand, brand),
    ).fetchone()
    related_threads = int(
        connection.execute(
            """
            SELECT COUNT(DISTINCT cache.root_id)
            FROM messages AS message
            JOIN root_cache AS cache ON cache.tweet_id = message.tweet_id
            WHERE message.author_id = ? AND message.inbound = 0
            """,
            (brand,),
        ).fetchone()[0]
    )
    multi_turn_threads = int(
        connection.execute(
            """
            WITH sizes AS (SELECT root_id, COUNT(*) AS size FROM root_cache GROUP BY root_id)
            SELECT COUNT(DISTINCT cache.root_id)
            FROM messages AS message
            JOIN root_cache AS cache ON cache.tweet_id = message.tweet_id
            JOIN sizes ON sizes.root_id = cache.root_id
            WHERE message.author_id = ? AND message.inbound = 0 AND sizes.size >= 3
            """,
            (brand,),
        ).fetchone()[0]
    )
    valid_parent = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM messages AS child
            JOIN messages AS parent ON child.parent_id = parent.tweet_id
            WHERE child.author_id = ? AND child.inbound = 0
            """,
            (brand,),
        ).fetchone()[0]
    )
    orphan_parent = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM messages AS child
            LEFT JOIN messages AS parent ON child.parent_id = parent.tweet_id
            WHERE child.author_id = ? AND child.inbound = 0
              AND child.parent_id IS NOT NULL AND parent.tweet_id IS NULL
            """,
            (brand,),
        ).fetchone()[0]
    )
    unique_templates = int(
        connection.execute(
            """
            SELECT COUNT(DISTINCT normalized_text) FROM messages
            WHERE author_id = ? AND inbound = 0
            """,
            (brand,),
        ).fetchone()[0]
    )
    top_template_rows = connection.execute(
        """
        SELECT COUNT(*) AS count FROM messages
        WHERE author_id = ? AND inbound = 0
        GROUP BY normalized_text
        ORDER BY count DESC, normalized_text ASC LIMIT ?
        """,
        (brand, config.top_template_count),
    ).fetchall()
    heuristic_counts: Counter[str] = Counter()
    for row in connection.execute(
        """
        SELECT normalized_text, word_count FROM messages
        WHERE author_id = ? AND inbound = 0
        """,
        (brand,),
    ):
        text = str(row["normalized_text"])
        word_total = int(row["word_count"])
        substantive, actionable, generic_or_redirect, public_containment = reply_proxy_flags(
            text, word_total, config
        )
        heuristic_counts["substantive"] += substantive
        heuristic_counts["actionable"] += actionable
        heuristic_counts["generic_or_redirect"] += generic_or_redirect
        heuristic_counts["public_containment"] += public_containment
    customer_diversity = connection.execute(
        linked_cte
        + """
        SELECT COUNT(DISTINCT customer_id), COUNT(DISTINCT message.normalized_text)
        FROM linked_inbound
        JOIN messages AS message ON message.tweet_id = linked_inbound.customer_id
        """,
        (brand, brand),
    ).fetchone()
    return BrandProfile(
        brand=brand,
        brand_authored_messages=outbound_count,
        unique_inbound_customer_messages_linked=int(linked_counts[0]),
        linked_customer_brand_pairs=int(linked_counts[1]),
        brand_related_threads=related_threads,
        reconstructible_multi_turn_threads=multi_turn_threads,
        outbound_parent_link_completeness=_fraction(valid_parent, outbound_count),
        outbound_orphan_parent_rate=_fraction(orphan_parent, outbound_count),
        median_outbound_word_count=_median_words(index, brand, outbound_count),
        substantive_reply_proxy_fraction=_fraction(heuristic_counts["substantive"], outbound_count),
        generic_or_redirect_reply_proxy_fraction=_fraction(
            heuristic_counts["generic_or_redirect"], outbound_count
        ),
        actionable_reply_proxy_fraction=_fraction(heuristic_counts["actionable"], outbound_count),
        public_containment_proxy_fraction=_fraction(
            heuristic_counts["public_containment"], outbound_count
        ),
        exact_normalized_duplicate_reply_rate=_fraction(
            outbound_count - unique_templates, outbound_count
        ),
        unique_normalized_reply_ratio=_fraction(unique_templates, outbound_count),
        top_template_concentration=_fraction(
            sum(int(row["count"]) for row in top_template_rows), outbound_count
        ),
        unique_normalized_customer_message_ratio=_fraction(
            int(customer_diversity[1]), int(customer_diversity[0])
        ),
    )


def profile_brands(index: ThreadIndex, config: ProfilingConfig) -> list[BrandProfile]:
    """Discover outbound accounts, apply a volume floor, then calculate raw signals."""

    accounts = index.connection.execute(
        """
        SELECT author_id, COUNT(*) AS count FROM messages
        WHERE inbound = 0 AND author_id <> ''
        GROUP BY author_id HAVING COUNT(*) >= ?
        ORDER BY count DESC, author_id ASC
        """,
        (config.minimum_outbound_messages,),
    ).fetchall()
    return [
        _profile_brand(index, str(row["author_id"]), int(row["count"]), config) for row in accounts
    ]


def select_brand(profiles: Iterable[BrandProfile], config: ProfilingConfig) -> str | None:
    """Select one eligible brand via visible lexicographic priorities, never a composite."""

    candidates = list(profiles)
    if not candidates:
        return None
    allowed = set(BrandProfile.__dataclass_fields__)
    unknown = [name for name in config.selection_priority if name not in allowed]
    if unknown:
        raise ValueError(f"Unknown selection metric(s): {', '.join(unknown)}")

    def value(profile: BrandProfile, field: str) -> float:
        raw = getattr(profile, field)
        return float(raw) if raw is not None else float("-inf")

    ranked = sorted(
        candidates,
        key=lambda profile: (
            tuple([-value(profile, field) for field in config.selection_priority])
            + (profile.brand.casefold(),)
        ),
    )
    return ranked[0].brand


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, profiles: list[BrandProfile]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(BrandProfile.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(profile.as_dict() for profile in profiles)


def _timestamp_bounds(index: ThreadIndex) -> tuple[str | None, str | None]:
    bounds = index.connection.execute(
        "SELECT MIN(created_epoch), MAX(created_epoch) FROM messages "
        "WHERE created_epoch IS NOT NULL"
    ).fetchone()
    if bounds[0] is None:
        return None, None
    return (
        datetime.fromtimestamp(float(bounds[0]), tz=UTC).isoformat(),
        datetime.fromtimestamp(float(bounds[1]), tz=UTC).isoformat(),
    )


def _update_brand_report(
    path: Path,
    config: ProfilingConfig,
    summary: ThreadSummary,
    profiles: list[BrandProfile],
    selected_brand: str | None,
) -> None:
    """Replace only the explicit generated evidence block, preserving authored prose."""

    start = "<!-- BEGIN GENERATED PROFILE EVIDENCE -->"
    end = "<!-- END GENERATED PROFILE EVIDENCE -->"
    table_columns = [
        "brand",
        "brand_authored_messages",
        "reconstructible_multi_turn_threads",
        "public_containment_proxy_fraction",
        "exact_normalized_duplicate_reply_rate",
        "unique_normalized_customer_message_ratio",
    ]
    rows = [
        "| " + " | ".join(table_columns) + " |",
        "|" + "|".join(["---"] * len(table_columns)) + "|",
    ]
    for profile in profiles:
        values = [str(getattr(profile, column)) for column in table_columns]
        rows.append("| " + " | ".join(values) + " |")
    selected = selected_brand or "No eligible account met the configured volume threshold."
    generated = "\n".join(
        [
            start,
            "## Generated profile evidence",
            "",
            f"- Source: {config.source_dataset_name}",
            f"- Eligible outbound accounts: {len(profiles)} "
            f"(minimum {config.minimum_outbound_messages} brand-authored messages)",
            f"- Reconstructed threads: {summary.reconstructed_threads}",
            f"- Selected brand by configured lexicographic priority: **{selected}**",
            "",
            "### Candidate comparison",
            "",
            *rows,
            "",
            "All values are raw counts or explicitly named heuristics. "
            "They are not resolution rates or present-day policy claims.",
            end,
        ]
    )
    existing = path.read_text(encoding="utf-8")
    before, marker, remainder = existing.partition(start)
    if not marker:
        raise ValueError(f"Brand report is missing required marker: {start}")
    _, end_marker, after = remainder.partition(end)
    if not end_marker:
        raise ValueError(f"Brand report is missing required marker: {end}")
    path.write_text(before + generated + after, encoding="utf-8")


def profile_dataset(
    input_path: Path,
    config_path: Path,
    manifest_path: Path,
    profile_csv_path: Path,
    profile_json_path: Path,
    brand_report_path: Path,
) -> ProfileResult:
    """Run the complete Phase 1 data pass and emit only aggregate artifacts."""

    config = load_config(config_path)
    loader = TwcsCsvLoader(input_path)
    schema = loader.validate()
    with tempfile.TemporaryDirectory(prefix="twcs-profile-") as temporary_directory:
        database_path = Path(temporary_directory) / "twcs.sqlite3"
        with ThreadIndex(database_path) as index:
            for message in loader.rows():
                index.add(message)
            index.finalize_ingestion()
            cyclic_components = index.reconstruct_threads()
            summary = index.summary(cyclic_components)
            profiles = profile_brands(index, config)
            selected_brand = select_brand(profiles, config)
            earliest, latest = _timestamp_bounds(index)

    generated_at = datetime.now(UTC).isoformat()
    manifest = {
        "source_dataset_name": config.source_dataset_name,
        "source_url": config.source_url,
        "local_filename": input_path.name,
        "sha256": _sha256(input_path),
        "file_size_bytes": os.path.getsize(input_path),
        "detected_encoding": loader.encoding,
        "columns": list(schema.input_columns),
        "resolved_logical_columns": schema.columns,
        "total_row_count": index.raw_rows,
        "duplicate_tweet_id_count": summary.duplicate_tweet_ids,
        "null_or_unparseable_essential_field_counts": {
            "tweet_id": summary.malformed_tweet_ids,
            "inbound": summary.unknown_direction_messages + summary.invalid_inbound_values,
            "parent_lineage": summary.malformed_lineage_references,
        },
        "earliest_valid_timestamp": earliest,
        "latest_valid_timestamp": latest,
        "generation_timestamp": generated_at,
    }
    profiles_payload = {
        "generation_timestamp": generated_at,
        "selection_method": {
            "minimum_outbound_messages": config.minimum_outbound_messages,
            "lexicographic_priority": list(config.selection_priority),
            "selected_brand": selected_brand,
        },
        "heuristics": {
            "minimum_substantive_word_count": config.minimum_substantive_word_count,
            "top_template_count": config.top_template_count,
            "generic_or_redirect_terms": list(config.generic_or_redirect_terms),
            "actionable_terms": list(config.actionable_terms),
        },
        "thread_summary": summary.as_dict(),
        "profiles": [profile.as_dict() for profile in profiles],
    }
    _write_json(manifest_path, manifest)
    _write_csv(profile_csv_path, profiles)
    _write_json(profile_json_path, profiles_payload)
    _update_brand_report(brand_report_path, config, summary, profiles, selected_brand)
    return ProfileResult(
        manifest_path=manifest_path,
        profile_csv_path=profile_csv_path,
        profile_json_path=profile_json_path,
        brand_report_path=brand_report_path,
        summary=summary,
        selected_brand=selected_brand,
        eligible_candidates=len(profiles),
    )
