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


def test_github_action_runs_every_ten_minutes_and_publishes_encrypted_data_branch():
    workflow = Path(".github/workflows/market-context-snapshot.yml")

    assert workflow.exists()
    text = workflow.read_text()
    assert "*/10 * * * *" in text
    assert "workflow_dispatch" in text
    assert "market-context-data" in text
    assert "contents: write" in text
    assert "latest.enc.json" in text
    assert "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY" in text
    assert "MARKET_CONTEXT_ASIN" in text
    assert "git push --force" in text
    assert "TENCENT_SSH_HOST" not in text
    assert "scp" not in text
    assert "ssh-keyscan" not in text


def test_encrypted_snapshot_generation_requires_private_target_asin(monkeypatch, tmp_path):
    monkeypatch.setenv("PANGOLINFO_API_TOKEN", "token")
    monkeypatch.setenv("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY", "secret")
    monkeypatch.delenv("MARKET_CONTEXT_ASIN", raising=False)

    rc = snapshot_generator.main(["--encrypt", "--output", str(tmp_path / "latest.enc.json")])

    assert rc == 2


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
