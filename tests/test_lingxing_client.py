from src.lingxing_client import normalize_dashboard_payload


def test_normalize_dashboard_payload_extracts_sales_and_campaigns():
    payload = {
        "orders": {"total_orders": 80, "total_sale_total": 1000, "currency_code": "USD"},
        "asin_sales": {"total_units": 90},
        "campaigns": [
            {"campaign_id": "sp-1", "campaign_name": "LH-B0GXYYZPBW-SP-exact", "spend": 100, "sales": 240, "orders": 8},
            {"campaign_id": "sd-1", "campaign_name": "LH-B0GXYYZPBW-SD-retarget", "spend": 20, "sales": 30, "orders": 1},
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
