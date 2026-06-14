import json
from pathlib import Path

from scripts import generate_market_context_snapshot as snapshot_generator
from src.market_context_snapshot import decrypt_snapshot_envelope, encrypt_snapshot


def test_snapshot_generator_script_exists_with_expected_entrypoint():
    script = Path("scripts/generate_market_context_snapshot.py")

    assert script.exists()
    text = script.read_text()
    assert "def main(" in text
    assert "validate_market_context_snapshot" in text
    assert "PANGOLINFO_API_TOKEN" in text
    assert "MARKET_CONTEXT_ASIN" in text
    assert "targets_with_env_overrides" in text


def test_github_action_runs_offset_ten_minute_schedule_and_publishes_encrypted_data_branch():
    workflow = Path(".github/workflows/market-context-snapshot.yml")

    assert workflow.exists()
    text = workflow.read_text()
    assert "3,13,23,33,43,53 * * * *" in text
    assert "*/10 * * * *" not in text
    assert "workflow_dispatch" in text
    assert "repository_dispatch" in text
    assert "market_context_snapshot" in text
    assert "concurrency:" in text
    assert "paths:" in text
    assert "market-context-data" in text
    assert "contents: write" in text
    assert "latest.enc.json" in text
    assert "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY" in text
    assert "MARKET_CONTEXT_ASIN" in text
    assert "Snapshot envelope:" in text
    assert "Data branch head:" in text
    assert "for attempt in 1 2 3" in text
    assert "Market context snapshot generation failed on attempt" in text
    assert "Fetch previous encrypted snapshot" in text
    assert "--fallback-encrypted-snapshot" in text
    assert "git push --force" in text
    assert "TENCENT_SSH_HOST" not in text
    assert "scp" not in text
    assert "ssh-keyscan" not in text


def test_default_snapshot_stale_threshold_allows_schedule_jitter():
    targets = Path("config/targets.yaml").read_text()

    assert "market_context_snapshot_stale_minutes: 20" in targets


def test_encrypted_snapshot_generation_requires_private_target_asin(monkeypatch, tmp_path):
    monkeypatch.setenv("PANGOLINFO_API_TOKEN", "token")
    monkeypatch.setenv("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY", "secret")
    monkeypatch.delenv("MARKET_CONTEXT_ASIN", raising=False)

    rc = snapshot_generator.main(["--encrypt", "--output", str(tmp_path / "latest.enc.json")])

    assert rc == 2


def _complete_snapshot_with_listing(title: str) -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_status": "complete",
        "captured_at": "2026-06-14T12:00:00Z",
        "source_versions": {"generator": "test"},
        "market_context": {
            "public_listing": {
                "title": title,
                "price_display": "$39.99",
                "rating": 4.8,
                "review_count": 36,
                "delivery_promise": "Mon, Jun 15",
                "fulfillment_method": "FBA",
                "coupon_present": False,
                "deal_present": False,
                "source": "previous",
            },
            "rank": {"own_bsr_leaf_rank": 53, "own_bsr_leaf_category": "Milk Frothers"},
            "core_keywords": [{"keyword": "milk frother"}, {"keyword": "coffee frother"}, {"keyword": "handheld milk frother"}],
            "market": {"selected_competitors": [{"asin": "B111111111"}]},
            "public_context_status": {"status": "ok", "message": "Complete", "warnings": []},
        },
        "warnings": [],
    }


def test_snapshot_generator_reuses_previous_listing_when_current_listing_is_incomplete(monkeypatch, tmp_path):
    current = _complete_snapshot_with_listing("Current")
    current["market_context"]["public_listing"] = {
        "source": "pangolin:amzProductDetail+amazon:directProductPage",
        "missing_fields": ["title", "price_display", "rating", "review_count", "delivery_promise"],
        "coupon_present": False,
        "deal_present": False,
    }
    previous = _complete_snapshot_with_listing("Previous Complete Listing")
    fallback_path = tmp_path / "previous.enc.json"
    fallback_path.write_text(json.dumps(encrypt_snapshot(previous, key="secret-key")), encoding="utf-8")
    output_path = tmp_path / "latest.enc.json"

    monkeypatch.setenv("PANGOLINFO_API_TOKEN", "secret-token")
    monkeypatch.setenv("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY", "secret-key")
    monkeypatch.setenv("MARKET_CONTEXT_ASIN", "B0SECRET001")
    monkeypatch.setattr(snapshot_generator, "build_snapshot", lambda **kwargs: current)

    rc = snapshot_generator.main(
        [
            "--encrypt",
            "--fallback-encrypted-snapshot",
            str(fallback_path),
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    envelope = json.loads(output_path.read_text())
    snapshot = decrypt_snapshot_envelope(envelope, key="secret-key")
    listing = snapshot["market_context"]["public_listing"]
    assert listing["title"] == "Previous Complete Listing"
    assert listing["price_display"] == "$39.99"
    assert listing["source"] == "pangolin:amzProductDetail+amazon:directProductPage+previousSnapshot"
    assert listing["missing_fields"] == []
    assert snapshot["market_context"]["rank"]["own_bsr_leaf_rank"] == 53
    assert "previous complete snapshot" in snapshot["warnings"][0]


def test_snapshot_generator_failure_prints_safe_field_diagnostics(monkeypatch, tmp_path, capsys):
    snapshot = {
        "schema_version": "1.0",
        "snapshot_status": "complete",
        "captured_at": "2026-06-14T12:00:00Z",
        "market_context": {
            "public_listing": {
                "source": "pangolin:amzProductDetail",
                "missing_fields": ["title", "price_display"],
            },
            "public_context_status": {
                "status": "partial",
                "message": "Pangolin product detail missing fields; direct product page fallback failed.",
            },
            "rank": {
                "bsr_capture_status": "measured",
                "bsr_capture_attempts": [
                    {
                        "source": "amazon:directBestSellersUrl",
                        "rank_level": "leaf",
                        "bsr_capture_status": "not_in_leaf_bsr_window",
                        "bsr_result_count": 48,
                    }
                ],
            },
            "core_keywords": [],
            "market": {"selected_competitors": []},
        },
    }

    monkeypatch.setenv("PANGOLINFO_API_TOKEN", "secret-token")
    monkeypatch.setenv("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY", "secret-key")
    monkeypatch.setenv("MARKET_CONTEXT_ASIN", "B0SECRET001")
    monkeypatch.setattr(snapshot_generator, "build_snapshot", lambda **kwargs: snapshot)

    rc = snapshot_generator.main(["--encrypt", "--output", str(tmp_path / "latest.enc.json")])

    captured = capsys.readouterr()
    assert rc == 1
    assert "listing_source=pangolin:amzProductDetail" in captured.err
    assert "listing_missing_fields=title, price_display" in captured.err
    assert "public_context_status=partial" in captured.err
    assert "bsr_capture_status=measured" in captured.err
    assert "amazon:directBestSellersUrl:leaf:not_in_leaf_bsr_window:48" in captured.err
    assert "secret-token" not in captured.err
    assert "B0SECRET001" not in captured.err


def test_repo_does_not_contain_real_product_identifiers():
    blocked = [
        "B0G" + "XYYZPBW",
        "B0F" + "PBGR1XZ",
        "34.143" + ".132.97",
        "Xian" + "fa",
        "340442" + "0091097881",
        "Insta" + "Whisk",
    ]
    roots = [
        Path("README.md"),
        Path("config"),
        Path("src"),
        Path("scripts"),
        Path("tests"),
        Path("data/fixtures"),
        Path(".github"),
    ]
    text = ""
    for root in roots:
        if root.is_file():
            text += root.read_text(errors="ignore")
            continue
        for path in root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text += path.read_text(errors="ignore")
    for value in blocked:
        assert value not in text
