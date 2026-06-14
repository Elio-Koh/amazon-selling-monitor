from pathlib import Path

from scripts import generate_market_context_snapshot as snapshot_generator


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
