from __future__ import annotations

from pathlib import Path

from support_agent.data.loader import TwcsCsvLoader
from support_agent.data.threads import ThreadIndex

FIXTURE = Path(__file__).parent / "fixtures" / "twcs_mini.csv"


def _index(tmp_path: Path) -> ThreadIndex:
    index = ThreadIndex(tmp_path / "fixture.sqlite3")
    loader = TwcsCsvLoader(FIXTURE)
    loader.validate()
    for row in loader.rows():
        index.add(row)
    index.finalize_ingestion()
    return index


def test_roots_two_turn_multi_turn_and_branching_are_reconstructed(tmp_path: Path) -> None:
    with _index(tmp_path) as index:
        cycles = index.reconstruct_threads()
        summary = index.summary(cycles)

        assert summary.total_messages == 11
        assert summary.duplicate_tweet_ids == 1
        assert summary.reconstructed_threads == 5
        assert summary.single_message_threads == 2
        assert summary.two_message_threads == 1
        assert summary.multi_turn_threads == 2
        assert summary.branching_threads == 1
        assert summary.linked_messages == 8
        assert summary.child_reference_count == 5
        assert summary.missing_child_references == 0
        assert summary.inconsistent_child_references == 0


def test_missing_parent_cycles_and_timestamps_are_reported(tmp_path: Path) -> None:
    with _index(tmp_path) as index:
        cycles = index.reconstruct_threads()
        summary = index.summary(cycles)

        assert summary.orphan_parent_references == 1
        assert summary.self_references == 1
        assert summary.cyclic_components == 2
        assert summary.timestamp_parse_failures == 1


def test_thread_identifiers_are_stable_and_component_scoped(tmp_path: Path) -> None:
    with _index(tmp_path) as index:
        index.reconstruct_threads()

        assert index.thread_id_for("1") == index.thread_id_for("4")
        assert index.thread_id_for("5") == index.thread_id_for("7")
        assert index.thread_id_for("1") != index.thread_id_for("5")
        assert index.thread_id_for("8") is not None


def test_twitter_style_timestamp_parses() -> None:
    assert ThreadIndex._parse_timestamp("Tue Oct 31 22:10:47 +0000 2017") is not None
