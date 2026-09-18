"""Deterministic extraction of reconstructed SpotifyCares support threads."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator

from .loader import TwcsCsvLoader
from .threads import ThreadIndex


@dataclass(frozen=True)
class Turn:
    tweet_id: str
    author_role: str
    text: str
    timestamp: str
    parent_id: str | None


@dataclass(frozen=True)
class SupportThread:
    thread_id: str
    root_tweet_id: str
    message_count: int
    customer_message_count: int
    spotify_message_count: int
    start_time: str
    end_time: str
    participant_count: int
    turns: tuple[Turn, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["turns"] = [asdict(turn) for turn in self.turns]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SupportThread":
        return cls(
            thread_id=str(payload["thread_id"]),
            root_tweet_id=str(payload["root_tweet_id"]),
            message_count=int(payload["message_count"]),
            customer_message_count=int(payload["customer_message_count"]),
            spotify_message_count=int(payload["spotify_message_count"]),
            start_time=str(payload["start_time"]),
            end_time=str(payload["end_time"]),
            participant_count=int(payload["participant_count"]),
            turns=tuple(Turn(**turn) for turn in payload["turns"]),  # type: ignore[arg-type]
        )

    def customer_text(self) -> str:
        return " ".join(turn.text for turn in self.turns if turn.author_role == "CUSTOMER")

    def spotify_text(self) -> str:
        return " ".join(turn.text for turn in self.turns if turn.author_role == "SPOTIFY")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_threads(path: Path, threads: Iterable[SupportThread]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for thread in threads:
            stream.write(json.dumps(thread.as_dict(), sort_keys=True, ensure_ascii=False) + "\n")


def read_threads(path: Path) -> Iterator[SupportThread]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield SupportThread.from_dict(json.loads(line))


def _thread_from_index(index: ThreadIndex, root_id: str, brand: str) -> SupportThread | None:
    rows = index.connection.execute(
        """
        SELECT tweet_id, author_id, inbound, created_at, created_epoch, parent_id, text
        FROM messages JOIN root_cache USING (tweet_id)
        WHERE root_id = ?
        ORDER BY created_epoch, tweet_id
        """,
        (root_id,),
    ).fetchall()
    if not rows or any(row["created_epoch"] is None for row in rows):
        return None
    turns = []
    for row in rows:
        role = (
            "SPOTIFY"
            if row["author_id"] == brand and row["inbound"] == 0
            else "CUSTOMER"
            if row["inbound"] == 1
            else "OTHER"
        )
        tweet_id = str(row["tweet_id"])
        timestamp = datetime.fromtimestamp(float(row["created_epoch"]), tz=UTC).isoformat()
        turns.append(
            Turn(
                tweet_id=tweet_id,
                author_role=role,
                text=str(row["text"]),
                timestamp=timestamp,
                parent_id=None if row["parent_id"] is None else str(row["parent_id"]),
            )
        )
    customer_count = sum(turn.author_role == "CUSTOMER" for turn in turns)
    spotify_count = sum(turn.author_role == "SPOTIFY" for turn in turns)
    if not customer_count or not spotify_count:
        return None
    return SupportThread(
        thread_id=index.thread_id_for(root_id) or "",
        root_tweet_id=root_id,
        message_count=len(turns),
        customer_message_count=customer_count,
        spotify_message_count=spotify_count,
        start_time=turns[0].timestamp,
        end_time=turns[-1].timestamp,
        participant_count=len({str(row["author_id"]) for row in rows}),
        turns=tuple(turns),
    )


def extract_spotify_corpus(
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    brand: str = "SpotifyCares",
) -> dict[str, object]:
    """Extract complete reconstructed threads containing Spotify and a customer."""

    loader = TwcsCsvLoader(input_path)
    loader.validate()
    with tempfile.TemporaryDirectory(prefix="spotify-extract-") as temporary_directory:
        with ThreadIndex(Path(temporary_directory) / "twcs.sqlite3") as index:
            for message in loader.rows():
                index.add(message)
            index.finalize_ingestion()
            index.reconstruct_threads()
            index.connection.execute(
                "CREATE INDEX IF NOT EXISTS root_cache_root_idx ON root_cache(root_id)"
            )
            index.connection.commit()
            brand_roots = [
                str(row["root_id"])
                for row in index.connection.execute(
                    """
                    SELECT DISTINCT cache.root_id
                    FROM messages AS message
                    JOIN root_cache AS cache ON cache.tweet_id = message.tweet_id
                    WHERE message.author_id = ? AND message.inbound = 0
                    ORDER BY cache.root_id
                    """,
                    (brand,),
                )
            ]
            relevant_roots = {
                str(row["root_id"])
                for row in index.connection.execute(
                    """
                    SELECT cache.root_id
                    FROM messages AS message
                    JOIN root_cache AS cache ON cache.tweet_id = message.tweet_id
                    GROUP BY cache.root_id
                    HAVING SUM(message.author_id = ? AND message.inbound = 0) > 0
                       AND SUM(message.inbound = 1) > 0
                    """,
                    (brand,),
                )
            }
            threads: list[SupportThread] = []
            missing_timestamps = 0
            for root_id in sorted(relevant_roots, key=int):
                thread = _thread_from_index(index, root_id, brand)
                if thread is None:
                    missing_timestamps += 1
                else:
                    threads.append(thread)

    threads.sort(key=lambda thread: (thread.start_time, thread.thread_id))
    write_threads(output_path, threads)
    manifest = {
        "phase": "2",
        "brand": brand,
        "source_sha256": sha256_file(input_path),
        "processed_path": str(output_path),
        "processed_sha256": sha256_file(output_path),
        "total_brand_threads": len(brand_roots),
        "total_relevant_threads": len(relevant_roots),
        "usable_threads": len(threads),
        "customer_messages": sum(item.customer_message_count for item in threads),
        "spotify_messages": sum(item.spotify_message_count for item in threads),
        "multi_turn_threads": sum(item.message_count >= 3 for item in threads),
        "exclusions": {
            "brand_threads_without_inbound_customer": len(brand_roots) - len(relevant_roots),
            "relevant_threads_missing_required_timestamp": missing_timestamps,
        },
        "schema": {
            "thread_fields": [
                "thread_id",
                "root_tweet_id",
                "message_count",
                "customer_message_count",
                "spotify_message_count",
                "start_time",
                "end_time",
                "participant_count",
                "turns",
            ],
            "turn_fields": ["tweet_id", "author_role", "text", "timestamp", "parent_id"],
        },
    }
    write_json(manifest_path, manifest)
    return manifest
