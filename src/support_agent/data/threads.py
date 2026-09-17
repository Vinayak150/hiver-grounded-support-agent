"""SQLite-backed reconstruction of thread components from canonical parent links."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .loader import ParsedMessage


@dataclass(frozen=True)
class ThreadSummary:
    """Aggregate thread-quality facts. Counts include anomalies rather than hiding them."""

    total_messages: int
    inbound_messages: int
    outbound_messages: int
    unknown_direction_messages: int
    unique_authors: int
    duplicate_tweet_ids: int
    malformed_tweet_ids: int
    malformed_lineage_references: int
    invalid_inbound_values: int
    root_messages: int
    linked_messages: int
    orphan_parent_references: int
    child_reference_count: int
    missing_child_references: int
    inconsistent_child_references: int
    reconstructed_threads: int
    single_message_threads: int
    two_message_threads: int
    multi_turn_threads: int
    branching_threads: int
    timestamp_parse_failures: int | None
    chronological_inconsistencies: int | None
    cyclic_components: int
    self_references: int

    def as_dict(self) -> dict[str, int | None]:
        return asdict(self)


class ThreadIndex:
    """Disk-backed temporary index for a large TWCS CSV.

    Text exists only in this temporary local SQLite file during profiling. The
    committed artifacts contain aggregates and never raw message text.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()
        self.raw_rows = 0
        self.duplicate_tweet_ids = 0
        self.malformed_tweet_ids = 0
        self.malformed_lineage_references = 0
        self.invalid_inbound_values = 0
        self.timestamp_parse_failures = 0
        self.timestamp_seen = False

    def __enter__(self) -> "ThreadIndex":
        return self

    def __exit__(self, *_: object) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            CREATE TABLE messages (
                tweet_id TEXT PRIMARY KEY,
                author_id TEXT NOT NULL,
                inbound INTEGER,
                created_at TEXT NOT NULL,
                created_epoch REAL,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                parent_id TEXT,
                child_ids TEXT NOT NULL
            );
            CREATE INDEX messages_parent_idx ON messages(parent_id);
            CREATE INDEX messages_author_direction_idx ON messages(author_id, inbound);
            CREATE TABLE child_refs (
                source_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                PRIMARY KEY(source_id, child_id)
            );
            CREATE INDEX child_refs_child_idx ON child_refs(child_id);
            CREATE TABLE root_cache (
                tweet_id TEXT PRIMARY KEY,
                root_id TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _parse_timestamp(value: str) -> float | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()

    def add(self, message: ParsedMessage) -> None:
        self.raw_rows += 1
        self.malformed_tweet_ids += message.malformed_id_count
        self.malformed_lineage_references += message.malformed_lineage_count
        self.invalid_inbound_values += int(message.invalid_inbound)
        if message.created_at:
            self.timestamp_seen = True
        timestamp = self._parse_timestamp(message.created_at)
        if message.created_at and timestamp is None:
            self.timestamp_parse_failures += 1
        if message.tweet_id is None:
            return
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO messages
            (tweet_id, author_id, inbound, created_at, created_epoch, text, normalized_text,
             word_count, parent_id, child_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.tweet_id,
                message.author_id,
                None if message.inbound is None else int(message.inbound),
                message.created_at,
                timestamp,
                message.text,
                message.normalized_text,
                message.words,
                message.parent_id,
                json.dumps(message.child_ids),
            ),
        )
        if cursor.rowcount == 0:
            self.duplicate_tweet_ids += 1
            return
        self.connection.executemany(
            "INSERT OR IGNORE INTO child_refs(source_id, child_id) VALUES (?, ?)",
            [(message.tweet_id, child_id) for child_id in message.child_ids],
        )

    def finalize_ingestion(self) -> None:
        self.connection.commit()

    def _resolve_root(self, tweet_id: str, cycle_roots: set[str]) -> str:
        cached = self.connection.execute(
            "SELECT root_id FROM root_cache WHERE tweet_id = ?", (tweet_id,)
        ).fetchone()
        if cached is not None:
            return str(cached["root_id"])

        visited: list[str] = []
        positions: dict[str, int] = {}
        current = tweet_id
        while True:
            cached = self.connection.execute(
                "SELECT root_id FROM root_cache WHERE tweet_id = ?", (current,)
            ).fetchone()
            if cached is not None:
                root_id = str(cached["root_id"])
                break
            if current in positions:
                cycle = visited[positions[current] :]
                root_id = min(cycle)
                cycle_roots.add(root_id)
                break
            positions[current] = len(visited)
            visited.append(current)
            row = self.connection.execute(
                "SELECT parent_id FROM messages WHERE tweet_id = ?", (current,)
            ).fetchone()
            if row is None or row["parent_id"] is None:
                root_id = current
                break
            parent_id = str(row["parent_id"])
            parent = self.connection.execute(
                "SELECT 1 FROM messages WHERE tweet_id = ?", (parent_id,)
            ).fetchone()
            if parent is None:
                root_id = current
                break
            current = parent_id

        self.connection.executemany(
            "INSERT OR REPLACE INTO root_cache(tweet_id, root_id) VALUES (?, ?)",
            [(node_id, root_id) for node_id in visited],
        )
        return root_id

    def reconstruct_threads(self) -> int:
        """Populate the disk-backed root cache and return cyclic-component count."""

        cycle_roots: set[str] = set()
        for row in self.connection.execute("SELECT tweet_id FROM messages ORDER BY tweet_id"):
            self._resolve_root(str(row["tweet_id"]), cycle_roots)
        self.connection.commit()
        return len(cycle_roots)

    def thread_id_for(self, tweet_id: str) -> str | None:
        """Return the deterministic thread identifier for one reconstructed tweet."""

        row = self.connection.execute(
            "SELECT root_id FROM root_cache WHERE tweet_id = ?", (tweet_id,)
        ).fetchone()
        if row is None:
            return None
        stable = hashlib.sha256(f"twcs-thread:{row['root_id']}".encode()).hexdigest()[:20]
        return f"twcs-{stable}"

    def summary(self, cyclic_components: int) -> ThreadSummary:
        total_messages = int(self.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        directions = dict(
            self.connection.execute(
                "SELECT inbound, COUNT(*) FROM messages GROUP BY inbound"
            ).fetchall()
        )
        root_messages = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM messages WHERE parent_id IS NULL"
            ).fetchone()[0]
        )
        linked_messages = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM messages AS child
                JOIN messages AS parent ON child.parent_id = parent.tweet_id
                """
            ).fetchone()[0]
        )
        orphan_parent_references = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM messages AS child
                LEFT JOIN messages AS parent ON child.parent_id = parent.tweet_id
                WHERE child.parent_id IS NOT NULL AND parent.tweet_id IS NULL
                """
            ).fetchone()[0]
        )
        child_reference_count = int(
            self.connection.execute("SELECT COUNT(*) FROM child_refs").fetchone()[0]
        )
        missing_child_references = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM child_refs AS ref
                LEFT JOIN messages AS child ON ref.child_id = child.tweet_id
                WHERE child.tweet_id IS NULL
                """
            ).fetchone()[0]
        )
        inconsistent_child_references = int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM child_refs AS ref
                JOIN messages AS child ON ref.child_id = child.tweet_id
                WHERE child.parent_id IS NOT ref.source_id
                """
            ).fetchone()[0]
        )
        thread_sizes = self.connection.execute(
            "SELECT root_id, COUNT(*) AS size FROM root_cache GROUP BY root_id"
        ).fetchall()
        branch_roots = {
            str(row["root_id"])
            for row in self.connection.execute(
                """
                SELECT DISTINCT cache.root_id FROM (
                    SELECT parent_id FROM messages
                    WHERE parent_id IS NOT NULL
                    GROUP BY parent_id HAVING COUNT(*) > 1
                ) AS branches
                JOIN root_cache AS cache ON cache.tweet_id = branches.parent_id
                """
            )
        }
        chronological = (
            int(
                self.connection.execute(
                    """
                    SELECT COUNT(*) FROM messages AS child
                    JOIN messages AS parent ON child.parent_id = parent.tweet_id
                    WHERE child.created_epoch IS NOT NULL AND parent.created_epoch IS NOT NULL
                      AND child.created_epoch < parent.created_epoch
                    """
                ).fetchone()[0]
            )
            if self.timestamp_seen
            else None
        )
        self_references = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM messages WHERE parent_id = tweet_id"
            ).fetchone()[0]
        )
        return ThreadSummary(
            total_messages=total_messages,
            inbound_messages=int(directions.get(1, 0)),
            outbound_messages=int(directions.get(0, 0)),
            unknown_direction_messages=int(directions.get(None, 0)),
            unique_authors=int(
                self.connection.execute(
                    "SELECT COUNT(DISTINCT author_id) FROM messages"
                ).fetchone()[0]
            ),
            duplicate_tweet_ids=self.duplicate_tweet_ids,
            malformed_tweet_ids=self.malformed_tweet_ids,
            malformed_lineage_references=self.malformed_lineage_references,
            invalid_inbound_values=self.invalid_inbound_values,
            root_messages=root_messages,
            linked_messages=linked_messages,
            orphan_parent_references=orphan_parent_references,
            child_reference_count=child_reference_count,
            missing_child_references=missing_child_references,
            inconsistent_child_references=inconsistent_child_references,
            reconstructed_threads=len(thread_sizes),
            single_message_threads=sum(int(row["size"]) == 1 for row in thread_sizes),
            two_message_threads=sum(int(row["size"]) == 2 for row in thread_sizes),
            multi_turn_threads=sum(int(row["size"]) >= 3 for row in thread_sizes),
            branching_threads=len(branch_roots),
            timestamp_parse_failures=self.timestamp_parse_failures if self.timestamp_seen else None,
            chronological_inconsistencies=chronological,
            cyclic_components=cyclic_components,
            self_references=self_references,
        )
