import time

import pytest

from src.lingxing_api_client import (
    LingxingAPIClient,
    LingxingAPIConfig,
    LingxingAPIConfigError,
    LingxingAPIError,
)


def make_config(**overrides):
    values = {
        "api_base_url": "http://203.0.113.10:8367",
        "account": "ExampleAccount",
        "profile_id": "0000000000000000",
        "user_token": "token-123",
        "parent_asin": "B0PARENT01",
        "focus_asin": "B0TEST0001",
        "timeout": 0.5,
    }
    values.update(overrides)
    return LingxingAPIConfig(**values)


def test_config_from_mapping_requires_user_token():
    with pytest.raises(LingxingAPIConfigError) as exc:
        LingxingAPIConfig.from_mapping(
            {
                "LINGXING_API_BASE_URL": "http://203.0.113.10:8367",
                "LINGXING_ACCOUNT": "ExampleAccount",
                "LINGXING_PROFILE_ID": "0000000000000000",
                "LINGXING_PARENT_ASIN": "B0PARENT01",
                "ASIN": "B0TEST0001",
            }
        )

    assert "LINGXING_USER_TOKEN" in str(exc.value)
    assert "Streamlit secrets" in str(exc.value)


def test_discover_child_asins_uses_auth_headers_and_parent_list_payload():
    calls = []

    def post_json(path, payload, headers, timeout):
        calls.append((path, payload, headers, timeout))
        return {
            "success": True,
            "data": {
                "list": [
                    {
                        "parent_asin": "B0PARENT01",
                        "child_asins": [
                            {"asin": "B0TEST0001", "title": "Main child"},
                            {"asin": "B0NEWCHILD", "title": "Merged child"},
                        ],
                    }
                ]
            },
        }

    client = LingxingAPIClient(make_config(), post_json=post_json)

    children = client.discover_child_asins("2026-06-13", "2026-06-13")

    assert [row["asin"] for row in children] == ["B0TEST0001", "B0NEWCHILD"]
    path, payload, headers, timeout = calls[0]
    assert path == "/api/lingxing/asin-all-list"
    assert payload["start_date"] == "2026-06-13"
    assert payload["end_date"] == "2026-06-13"
    assert "date_start" not in payload
    assert "date_end" not in payload
    assert payload["asin_type"] == "parent_asin"
    assert payload["offset"] == 0
    assert payload["length"] >= 100
    assert "search_value" not in payload
    assert headers["X-USER-TOKEN"] == "token-123"
    assert headers["X-LINGXING-ACCOUNT"] == "ExampleAccount"
    assert headers["X-Profile-Id"] == "0000000000000000"
    assert timeout == 0.5


def test_fetch_dashboard_uses_asin_all_and_sales_fallback_without_orders_endpoint():
    calls = []

    def post_json(path, payload, headers, timeout):
        calls.append((path, payload))
        if path == "/api/lingxing/asin-all-list":
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "parent_asin": "B0PARENT01",
                            "child_asins": [
                                {"asin": "B0TEST0001", "title": "Main child", "small_image_url": "https://img/main.jpg"},
                                {"asin": "B0NEWCHILD", "title": "New child"},
                            ],
                        }
                    ]
                },
            }
        if path == "/api/lingxing/asin-all" and payload["asin"] == "B0TEST0001":
            assert payload["date_start"] == "2026-06-13"
            assert payload["date_end"] == "2026-06-13"
            assert "date_range" not in payload
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "asin": "B0TEST0001",
                            "parent_asin": "B0PARENT01",
                            "title": "Main child",
                            "amount": "100.50",
                            "order_items": "2",
                            "volume": "3",
                            "spend": "10.25",
                            "ad_sales_amount": "31.00",
                            "available_inventory": {"afn_fulfillable_quantity": "50"},
                        }
                    ]
                },
            }
        if path == "/api/lingxing/asin-all" and payload["asin"] == "B0NEWCHILD":
            assert payload["date_start"] == "2026-06-13"
            assert payload["date_end"] == "2026-06-13"
            assert "date_range" not in payload
            return {"success": True, "data": {"list": []}}
        if path == "/api/lingxing/asin-sales" and payload["asin"] == "B0NEWCHILD":
            assert payload["date_range"] == ["2026-06-13", "2026-06-13"]
            assert "date_start" not in payload
            assert "date_end" not in payload
            return {"success": True, "data": {"total_units": "5"}}
        if path == "/api/lingxing/campaigns":
            assert payload["date_range"] == ["2026-06-13", "2026-06-13"]
            assert "date_start" not in payload
            assert "date_end" not in payload
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "campaign_id": None,
                            "campaign_name": None,
                            "spends": "9.00",
                            "sales": "20.00",
                            "orders": "1",
                            "clicks": "4",
                            "impressions": "100",
                        },
                        {
                            "campaign_id": "c1",
                            "campaign_name": "SC_B0TEST0001_MF04_Auto_260606",
                            "targeting_type": "auto",
                            "spends": "9.00",
                            "sales": "20.00",
                            "orders": "1",
                            "clicks": "4",
                            "impressions": "100",
                        },
                    ]
                },
            }
        raise AssertionError(f"unexpected call {path} {payload}")

    client = LingxingAPIClient(make_config(), post_json=post_json)

    dashboard = client.fetch_dashboard(
        start_date="2026-06-13",
        end_date="2026-06-13",
        sp_campaign_ids=[],
        known_non_sp_campaign_ids=[],
    )

    assert dashboard["parent_asin"] == "B0PARENT01"
    assert dashboard["selected_child_asin"] == "B0TEST0001"
    assert dashboard["sales"]["total_sales"] == 100.5
    assert dashboard["sales"]["total_orders"] == 2
    assert dashboard["sales"]["total_units"] == 8
    assert [row["asin"] for row in dashboard["variations"]] == ["B0TEST0001", "B0NEWCHILD"]
    assert dashboard["variations"][1]["units"] == 5
    assert dashboard["campaigns"][0]["campaign_id"] == "c1"
    assert dashboard["advertising"]["all_ads"]["spend"] == 9.0
    assert "unknown" not in dashboard["advertising"]["by_product"]
    assert not any(path == "/api/lingxing/orders" for path, _payload in calls)
    assert any("asin-all returned no detail for B0NEWCHILD" in warning for warning in dashboard["source_status"]["warnings"])


def test_code_one_success_response_does_not_trigger_asin_all_fallback():
    calls = []

    def post_json(path, payload, headers, timeout):
        calls.append((path, payload))
        if path == "/api/lingxing/asin-all-list":
            return {
                "code": 1,
                "message": "success",
                "data": {
                    "list": [
                        {
                            "parent_asin": "B0PARENT01",
                            "child_asins": [{"asin": "B0TEST0001"}],
                        }
                    ]
                },
            }
        if path == "/api/lingxing/asin-all":
            assert payload["date_start"] == "2026-06-13"
            assert payload["date_end"] == "2026-06-13"
            assert "date_range" not in payload
            return {
                "code": 1,
                "message": "success",
                "data": {
                    "list": [
                        {
                            "asin": "B0TEST0001",
                            "parent_asin": "B0PARENT01",
                            "amount": "1306.67",
                            "order_items": "33",
                            "volume": "33",
                        }
                    ]
                },
            }
        if path == "/api/lingxing/campaigns":
            return {"code": 1, "message": "success", "data": {"list": []}}
        if path == "/api/lingxing/asin-sales":
            raise AssertionError("asin-sales fallback should not be called for code=1 success")
        raise AssertionError(f"unexpected call {path}")

    client = LingxingAPIClient(make_config(), post_json=post_json)

    dashboard = client.fetch_dashboard(
        start_date="2026-06-13",
        end_date="2026-06-13",
        sp_campaign_ids=[],
        known_non_sp_campaign_ids=[],
    )

    assert dashboard["sales"]["total_sales"] == 1306.67
    assert dashboard["sales"]["total_orders"] == 33
    assert dashboard["sales"]["total_units"] == 33
    assert not any(path == "/api/lingxing/asin-sales" for path, _payload in calls)
    assert not any("code=1" in warning for warning in dashboard["source_status"]["warnings"])


def test_fetch_dashboard_pulls_child_details_in_parallel():
    child_asins = [f"B0CHILD{i}" for i in range(4)]

    def post_json(path, payload, headers, timeout):
        if path == "/api/lingxing/asin-all-list":
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "parent_asin": "B0PARENT01",
                            "child_asins": [{"asin": asin} for asin in child_asins],
                        }
                    ]
                },
            }
        if path == "/api/lingxing/asin-all":
            time.sleep(0.08)
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "asin": payload["asin"],
                            "parent_asin": "B0PARENT01",
                            "amount": "10",
                            "order_items": "1",
                            "volume": "1",
                        }
                    ]
                },
            }
        if path == "/api/lingxing/campaigns":
            return {"success": True, "data": {"list": []}}
        raise AssertionError(f"unexpected call {path}")

    client = LingxingAPIClient(make_config(focus_asin="B0CHILD0"), post_json=post_json)
    started = time.monotonic()

    dashboard = client.fetch_dashboard(
        start_date="2026-06-13",
        end_date="2026-06-13",
        sp_campaign_ids=[],
        known_non_sp_campaign_ids=[],
    )

    elapsed = time.monotonic() - started
    assert len(dashboard["variations"]) == 4
    assert elapsed < 0.24


def test_asin_all_failure_falls_back_to_asin_sales_for_child_units():
    def post_json(path, payload, headers, timeout):
        if path == "/api/lingxing/asin-all-list":
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "parent_asin": "B0PARENT01",
                            "child_asins": [{"asin": "B0TEST0001"}],
                        }
                    ]
                },
            }
        if path == "/api/lingxing/asin-all":
            raise LingxingAPIError("HTTP 504 from asin-all")
        if path == "/api/lingxing/asin-sales":
            assert payload["date_range"] == ["2026-06-13", "2026-06-13"]
            return {"success": True, "data": {"total_units": "33"}}
        if path == "/api/lingxing/campaigns":
            return {"success": True, "data": {"list": []}}
        raise AssertionError(f"unexpected call {path}")

    client = LingxingAPIClient(make_config(), post_json=post_json)

    dashboard = client.fetch_dashboard(
        start_date="2026-06-13",
        end_date="2026-06-13",
        sp_campaign_ids=[],
        known_non_sp_campaign_ids=[],
    )

    assert dashboard["sales"]["total_units"] == 33
    assert dashboard["variations"][0]["units"] == 33
    assert any("asin-all failed for B0TEST0001" in warning for warning in dashboard["source_status"]["warnings"])


def test_api_warnings_do_not_embed_full_validation_json():
    long_validation_error = (
        'HTTP 422 from /api/lingxing/asin-all-list: {"detail":[{"type":"missing",'
        '"loc":["body","start_date"],"msg":"Field required","input":{"date_start":"2026-06-13"}},'
        '{"type":"missing","loc":["body","end_date"],"msg":"Field required"}]}'
    )

    def post_json(path, payload, headers, timeout):
        if path in {"/api/lingxing/asin-all-list", "/api/lingxing/asin-all", "/api/lingxing/campaigns"}:
            raise LingxingAPIError(long_validation_error)
        if path == "/api/lingxing/asin-sales":
            return {"success": True, "data": {"total_units": "1"}}
        raise AssertionError(f"unexpected call {path}")

    client = LingxingAPIClient(make_config(), post_json=post_json)

    dashboard = client.fetch_dashboard(
        start_date="2026-06-13",
        end_date="2026-06-13",
        sp_campaign_ids=[],
        known_non_sp_campaign_ids=[],
    )

    warnings = dashboard["source_status"]["warnings"]
    assert any("missing request fields: start_date, end_date" in warning for warning in warnings)
    assert not any('{"detail"' in warning for warning in warnings)
