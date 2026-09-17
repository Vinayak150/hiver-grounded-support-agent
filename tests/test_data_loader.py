from __future__ import annotations

from pathlib import Path

import pytest

from support_agent.data.loader import TwcsCsvLoader
from support_agent.data.schema import (
    SchemaValidationError,
    normalized_reply,
    parse_id_list,
    parse_inbound,
    parse_parent_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "twcs_mini.csv"


def test_loader_resolves_actual_fixture_schema_and_streams_rows() -> None:
    loader = TwcsCsvLoader(FIXTURE)
    schema = loader.validate()

    assert schema.columns["tweet_id"] == "tweet_id"
    assert schema.parent_column == "in_response_to_tweet_id"
    assert len(list(loader.rows())) == 12


def test_missing_required_column_fails_clearly(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "tweet_id,inbound,text,in_response_to_tweet_id\n1,true,hello,\n", encoding="utf-8"
    )

    with pytest.raises(SchemaValidationError, match="author_id"):
        TwcsCsvLoader(invalid).validate()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("TRUE", True), ("0", False), ("yes", True), ("", None), ("unknown", None)],
)
def test_inbound_parsing(raw: str, expected: bool | None) -> None:
    assert parse_inbound(raw) is expected


def test_response_identifiers_support_multiple_values_and_malformed_tokens() -> None:
    parsed = parse_id_list('["6", "7", "oops"]')
    assert parsed.values == ("6", "7")
    assert parsed.malformed == ("oops",)
    parent = parse_parent_id("6,7")
    assert parent.values == ()
    assert parent.malformed == ("multiple_parent_ids",)


def test_reply_normalization_replaces_only_mentions_urls_and_whitespace() -> None:
    assert (
        normalized_reply("  Hi @BrandOne  see https://example.test/help  ")
        == "hi <mention> see <url>"
    )
