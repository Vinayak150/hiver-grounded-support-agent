from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from support_agent.data.profiling import (
    load_config,
    profile_dataset,
    reply_proxy_flags,
    select_brand,
)

FIXTURE = Path(__file__).parent / "fixtures" / "twcs_mini.csv"
REPOSITORY = Path(__file__).resolve().parents[1]


def test_profiling_emits_aggregate_artifacts_and_no_raw_fixture_text(tmp_path: Path) -> None:
    config = replace(
        load_config(REPOSITORY / "configs" / "profiling.yaml"), minimum_outbound_messages=1
    )
    config_path = tmp_path / "profiling.yaml"
    config_path.write_text(
        json.dumps(
            {
                "source_dataset_name": config.source_dataset_name,
                "source_url": config.source_url,
                "heuristics": {
                    "minimum_substantive_word_count": 8,
                    "top_template_count": 5,
                    "generic_or_redirect_terms": ["sorry", "please dm"],
                    "actionable_terms": ["try", "settings"],
                },
                "selection": {
                    "minimum_outbound_messages": 1,
                    "priority": ["reconstructible_multi_turn_threads", "brand_authored_messages"],
                },
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "BRAND_SELECTION.md"
    report.write_text(
        (REPOSITORY / "docs" / "BRAND_SELECTION.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = profile_dataset(
        input_path=FIXTURE,
        config_path=config_path,
        manifest_path=tmp_path / "twcs_manifest.json",
        profile_csv_path=tmp_path / "brand_profile.csv",
        profile_json_path=tmp_path / "brand_profile.json",
        brand_report_path=report,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    output = result.profile_json_path.read_text(encoding="utf-8")
    assert manifest["total_row_count"] == 12
    assert manifest["duplicate_tweet_id_count"] == 1
    assert result.selected_brand == "BrandOne"
    assert "I cannot sign in" not in output
    assert "I cannot sign in" not in report.read_text(encoding="utf-8")
    profiles = json.loads(output)["profiles"]
    brand_two = next(profile for profile in profiles if profile["brand"] == "BrandTwo")
    assert brand_two["generic_or_redirect_reply_proxy_fraction"] == 0.5
    assert brand_two["actionable_reply_proxy_fraction"] == 0.5


def test_selection_tie_breaks_by_brand_name_deterministically() -> None:
    config = replace(
        load_config(REPOSITORY / "configs" / "profiling.yaml"),
        selection_priority=("brand_authored_messages",),
    )
    from support_agent.data.profiling import BrandProfile

    prototype = BrandProfile(
        brand="zeta",
        brand_authored_messages=10,
        unique_inbound_customer_messages_linked=0,
        linked_customer_brand_pairs=0,
        brand_related_threads=0,
        reconstructible_multi_turn_threads=0,
        outbound_parent_link_completeness=None,
        outbound_orphan_parent_rate=None,
        median_outbound_word_count=None,
        substantive_reply_proxy_fraction=None,
        generic_or_redirect_reply_proxy_fraction=None,
        actionable_reply_proxy_fraction=None,
        public_containment_proxy_fraction=None,
        exact_normalized_duplicate_reply_rate=None,
        unique_normalized_reply_ratio=None,
        top_template_concentration=None,
        unique_normalized_customer_message_ratio=None,
    )
    assert select_brand([prototype, replace(prototype, brand="Alpha")], config) == "Alpha"


def test_generic_proxy_does_not_mislabel_an_apology_with_a_clarifying_question() -> None:
    config = load_config(REPOSITORY / "configs" / "profiling.yaml")
    flags = reply_proxy_flags(
        "sorry to hear that. has your card been used on another account recently?", 13, config
    )
    assert flags == (True, False, False, True)
    assert reply_proxy_flags("sorry. please dm us.", 5, config)[2] is True


def test_raw_data_path_is_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "data/raw/twcs.csv"],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
