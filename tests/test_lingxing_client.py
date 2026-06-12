from src.lingxing_client import build_blocked_dashboard, normalize_dashboard_payload


def test_normalize_dashboard_payload_extracts_sales_and_campaigns():
    payload = {
        "orders": {"total_orders": 80, "total_sale_total": 1000, "currency_code": "USD"},
        "asin_sales": {"total_units": 90},
        "campaigns": [
            {"campaign_id": "sp-1", "campaign_name": "LH-B0F9FS822W-SP-exact", "spend": 100, "sales": 240, "orders": 8},
            {"campaign_id": "sd-1", "campaign_name": "LH-B0F9FS822W-SD-retarget", "spend": 20, "sales": 30, "orders": 1},
        ],
        "listing": {"title": "Sample product", "fba_fulfillable": 120},
        "pulled_at": "2026-06-12T08:00:00Z",
    }

    normalized = normalize_dashboard_payload(payload)

    assert normalized["sales"]["total_orders"] == 80
    assert normalized["sales"]["total_sales"] == 1000
    assert normalized["sales"]["total_units"] == 90
    assert normalized["advertising"]["sp"]["spend"] == 100
    assert normalized["advertising"]["all_ads"]["spend"] == 120
    assert normalized["context"]["listing"]["title"] == "Sample product"
    assert normalized["source_status"]["mode"] == "live_or_fixture"


def test_normalize_dashboard_payload_records_missing_parent_sales():
    payload = {
        "orders": {},
        "asin_sales": {"total_units": 3},
        "campaigns": [],
    }

    normalized = normalize_dashboard_payload(payload)

    assert "sales.total_sales" in normalized["source_status"]["missing_fields"]
    assert "sales.total_orders" in normalized["source_status"]["missing_fields"]


def test_build_blocked_dashboard_does_not_return_fixture_metrics():
    dashboard = build_blocked_dashboard(
        asin="B0F9FS822W",
        mode="live_blocked",
        reason="HTTP 404 Not Found",
    )

    assert dashboard["source_status"]["mode"] == "live_blocked"
    assert dashboard["source_status"]["blocked"] is True
    assert dashboard["sales"]["total_sales"] == 0
    assert dashboard["sales"]["total_orders"] == 0
    assert dashboard["campaigns"] == []
    assert "HTTP 404 Not Found" in dashboard["source_status"]["warnings"][0]
