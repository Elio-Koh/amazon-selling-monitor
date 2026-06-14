import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.market_context_snapshot import (
    MARKET_CONTEXT_REQUIRED_FIELDS,
    SnapshotValidationError,
    apply_snapshot_to_dashboard,
    cleanup_history,
    decrypt_snapshot_envelope,
    encrypt_snapshot,
    load_encrypted_snapshot_from_url,
    load_snapshot_from_url,
    snapshot_freshness,
    validate_market_context_snapshot,
    write_snapshot_atomically,
)


def complete_snapshot(captured_at="2026-06-14T12:00:00Z"):
    return {
        "schema_version": "1.0",
        "snapshot_status": "complete",
        "captured_at": captured_at,
        "source_versions": {"generator": "test"},
        "market_context": {
            "public_listing": {
                "title": "SampleWhisk Milk Frother",
                "price_display": "$39.99",
                "rating": 4.8,
                "review_count": 36,
                "delivery_promise": "Mon, Jun 15",
                "fulfillment_method": "FBA",
                "coupon_present": False,
                "deal_present": False,
            },
            "rank": {
                "own_bsr_leaf_rank": 53,
                "own_bsr_leaf_category": "Milk Frothers",
                "own_new_release_leaf_rank": None,
                "own_new_release_leaf_category": "Milk Frothers",
            },
            "core_keywords": [
                {"keyword": "milk frother", "rank_status": "measured"},
                {"keyword": "coffee frother", "rank_status": "measured"},
                {"keyword": "handheld milk frother", "rank_status": "measured"},
            ],
            "market": {
                "selected_competitors": [
                    {"asin": "B111111111", "title": "Competitor"},
                ]
            },
            "public_context_status": {
                "status": "ok",
                "message": "Complete market context snapshot.",
            },
        },
        "warnings": [],
    }


def test_validate_market_context_snapshot_accepts_complete_snapshot():
    snapshot = complete_snapshot()

    validated = validate_market_context_snapshot(snapshot)

    assert validated["snapshot_status"] == "complete"
    assert validated["market_context"]["rank"]["own_bsr_leaf_rank"] == 53


def test_validate_market_context_snapshot_rejects_missing_required_field():
    snapshot = complete_snapshot()
    snapshot["market_context"]["public_listing"]["price_display"] = None

    with pytest.raises(SnapshotValidationError) as exc:
        validate_market_context_snapshot(snapshot)

    assert "public_listing.price_display" in str(exc.value)
    assert "public_listing.price_display" in MARKET_CONTEXT_REQUIRED_FIELDS


def test_apply_snapshot_to_dashboard_updates_context_and_status():
    dashboard = {
        "context": {"listing": {"title": "Lingxing listing"}},
        "source_status": {"warnings": []},
    }
    snapshot = complete_snapshot()

    result = apply_snapshot_to_dashboard(
        dashboard,
        snapshot,
        now=datetime(2026, 6, 14, 12, 5, tzinfo=timezone.utc),
        stale_minutes=10,
        expired_minutes=120,
    )

    assert result["context"]["public_listing"]["title"] == "SampleWhisk Milk Frother"
    assert result["context"]["public_context_status"]["status"] == "fresh"
    assert result["context"]["public_context_status"]["snapshot_age_minutes"] == 5


def test_apply_snapshot_to_dashboard_marks_expired_snapshot():
    dashboard = {"context": {}, "source_status": {"warnings": []}}
    snapshot = complete_snapshot()

    result = apply_snapshot_to_dashboard(
        dashboard,
        snapshot,
        now=datetime(2026, 6, 14, 14, 30, tzinfo=timezone.utc),
        stale_minutes=10,
        expired_minutes=120,
    )

    assert result["context"]["public_context_status"]["status"] == "expired"
    assert "expired" in result["context"]["public_context_status"]["message"].lower()


def test_load_snapshot_from_url_uses_bearer_token(monkeypatch):
    payload = json.dumps(complete_snapshot()).encode("utf-8")
    captured_headers = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return payload

    def fake_urlopen(request, timeout):
        captured_headers.update(dict(request.header_items()))
        assert timeout == 3
        return FakeResponse()

    monkeypatch.setattr("src.market_context_snapshot.urllib.request.urlopen", fake_urlopen)

    snapshot = load_snapshot_from_url("https://example.test/latest.json", token="secret", timeout=3)

    assert snapshot["snapshot_status"] == "complete"
    assert captured_headers["Authorization"] == "Bearer secret"


def test_load_encrypted_snapshot_from_url_sends_no_cache_headers(monkeypatch):
    envelope = encrypt_snapshot(complete_snapshot(), key="unit-test-secret")
    payload = json.dumps(envelope).encode("utf-8")
    captured_headers = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return payload

    def fake_urlopen(request, timeout):
        captured_headers.update(dict(request.header_items()))
        assert timeout == 3
        return FakeResponse()

    monkeypatch.setattr("src.market_context_snapshot.urllib.request.urlopen", fake_urlopen)

    snapshot = load_encrypted_snapshot_from_url("https://example.test/latest.enc.json", key="unit-test-secret", timeout=3)

    assert snapshot["snapshot_status"] == "complete"
    assert captured_headers["Cache-control"] == "no-cache"
    assert captured_headers["Pragma"] == "no-cache"


def test_encrypt_snapshot_envelope_hides_plaintext_and_decrypts():
    snapshot = complete_snapshot()
    snapshot["market_context"]["public_listing"]["asin"] = "B0TEST0001"
    snapshot["market_context"]["public_listing"]["title"] = "Sensitive Sample Product"

    envelope = encrypt_snapshot(snapshot, key="unit-test-secret")
    serialized = json.dumps(envelope)

    assert envelope["algorithm"] == "AES-256-GCM"
    assert "B0TEST0001" not in serialized
    assert "Sensitive Sample Product" not in serialized
    assert decrypt_snapshot_envelope(envelope, key="unit-test-secret")["market_context"]["public_listing"]["asin"] == "B0TEST0001"
    with pytest.raises(Exception):
        decrypt_snapshot_envelope(envelope, key="wrong-secret")


def test_write_snapshot_atomically_and_cleanup_history(tmp_path):
    snapshot = complete_snapshot("2026-06-14T12:00:00Z")
    latest_path = tmp_path / "latest.json"
    history_path = tmp_path / "history" / "2026-06-14" / "12-00-00.json"

    write_snapshot_atomically(snapshot, latest_path=latest_path, history_path=history_path)

    assert json.loads(latest_path.read_text())["snapshot_status"] == "complete"
    assert history_path.exists()
    old_path = tmp_path / "history" / "2026-06-13" / "12-00-00.json"
    old_path.parent.mkdir(parents=True)
    old_path.write_text("{}")

    cleanup_history(tmp_path / "history", now=datetime(2026, 6, 14, 13, tzinfo=timezone.utc), retention_hours=24)

    assert history_path.exists()
    assert not old_path.exists()


def test_snapshot_freshness_thresholds():
    captured_at = "2026-06-14T12:00:00Z"

    assert snapshot_freshness(captured_at, now=datetime(2026, 6, 14, 12, 5, tzinfo=timezone.utc), stale_minutes=10, expired_minutes=120)["status"] == "fresh"
    assert snapshot_freshness(captured_at, now=datetime(2026, 6, 14, 12, 30, tzinfo=timezone.utc), stale_minutes=10, expired_minutes=120)["status"] == "stale"
    assert snapshot_freshness(captured_at, now=datetime(2026, 6, 14, 14, 30, tzinfo=timezone.utc), stale_minutes=10, expired_minutes=120)["status"] == "expired"
