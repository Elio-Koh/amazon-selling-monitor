import asyncio
import json
import sys
import types
from types import SimpleNamespace

from src.lingxing_client import LingxingClient, build_blocked_dashboard, normalize_dashboard_payload


class FakeAsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def install_fake_mcp(monkeypatch, *, streamable_initialize_error=None):
    calls = []

    class FakeClientSession:
        def __init__(self, *streams):
            self.streams = streams
            calls.append(("client_session", streams))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def initialize(self):
            calls.append(("initialize", self.streams))
            if self.streams == ("stream_read", "stream_write") and streamable_initialize_error:
                raise streamable_initialize_error

        async def list_tools(self):
            calls.append(("list_tools", self.streams))
            suffix = "B0TEST0001"
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name=f"get_orders_{suffix}"),
                    SimpleNamespace(name=f"get_asin_sales_{suffix}"),
                    SimpleNamespace(name=f"list_campaigns_with_date_and_portfolio_with_config_{suffix}"),
                    SimpleNamespace(name=f"listing_{suffix}"),
                ]
            )

    def streamable_http_client(url):
        calls.append(("streamable_http_client", url))
        return FakeAsyncContext(("stream_read", "stream_write", lambda: "session-id"))

    def sse_client(url):
        calls.append(("sse_client", url))
        return FakeAsyncContext(("sse_read", "sse_write"))

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = FakeClientSession
    client_module = types.ModuleType("mcp.client")
    streamable_module = types.ModuleType("mcp.client.streamable_http")
    streamable_module.streamable_http_client = streamable_http_client
    sse_module = types.ModuleType("mcp.client.sse")
    sse_module.sse_client = sse_client

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", client_module)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_module)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", sse_module)
    return calls


async def fake_call_known_tools(session, tool_names, **kwargs):
    return {"tool_names": list(tool_names)}


def test_streamable_http_transport_uses_two_streams_and_preserves_module_url(monkeypatch):
    calls = install_fake_mcp(monkeypatch)
    client = LingxingClient(
        server_url="http://example.test/lingxing_config_B0TEST0001/",
        asin="B0TEST0001",
        transport="streamable_http",
    )
    monkeypatch.setattr(client, "_call_known_tools", fake_call_known_tools)

    payload = asyncio.run(client.fetch_live_payload())

    assert ("streamable_http_client", "http://example.test/lingxing_config_B0TEST0001/") in calls
    assert ("client_session", ("stream_read", "stream_write")) in calls
    assert not any(call[0] == "sse_client" for call in calls)
    assert payload["tool_names"][0] == "get_orders_B0TEST0001"


def test_sse_transport_still_uses_sse_client(monkeypatch):
    calls = install_fake_mcp(monkeypatch)
    client = LingxingClient(
        server_url="http://example.test/legacy-sse",
        asin="B0TEST0001",
        transport="sse",
    )
    monkeypatch.setattr(client, "_call_known_tools", fake_call_known_tools)

    payload = asyncio.run(client.fetch_live_payload())

    assert ("sse_client", "http://example.test/legacy-sse") in calls
    assert ("client_session", ("sse_read", "sse_write")) in calls
    assert not any(call[0] == "streamable_http_client" for call in calls)
    assert payload["tool_names"][0] == "get_orders_B0TEST0001"


def test_auto_transport_falls_back_to_sse_when_streamable_initialize_fails(monkeypatch):
    calls = install_fake_mcp(monkeypatch, streamable_initialize_error=RuntimeError("streamable failed"))
    client = LingxingClient(
        server_url="http://example.test/lingxing_config_B0TEST0001/",
        asin="B0TEST0001",
        transport="auto",
    )
    monkeypatch.setattr(client, "_call_known_tools", fake_call_known_tools)

    payload = asyncio.run(client.fetch_live_payload())

    assert ("streamable_http_client", "http://example.test/lingxing_config_B0TEST0001/") in calls
    assert ("sse_client", "http://example.test/lingxing_config_B0TEST0001/") in calls
    assert ("client_session", ("sse_read", "sse_write")) in calls
    assert payload["tool_names"][0] == "get_orders_B0TEST0001"


def test_call_known_tools_uses_default_date_range_for_current_lingxing_tools(monkeypatch):
    monkeypatch.setattr("src.lingxing_client._default_report_dates", lambda: ("2026-06-11", "2026-06-11"))
    calls = []

    class FakeSession:
        async def call_tool(self, name, args):
            calls.append((name, args))
            if name.startswith("get_orders"):
                body = {"total_orders": 1, "total_sale_total": 39.99, "currency_code": "USD"}
            elif name.startswith("get_asin_sales"):
                body = {"total_units": 1}
            elif name.startswith("list_campaigns_with_date"):
                body = {"campaigns": [{"campaign_id": "c1", "campaign_name": "SC_B0TEST0001_MF04"}]}
            else:
                body = {"title": "Sample listing"}
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(body))])

    tool_names = [
        "list_campaigns_with_date_and_portfolio_with_config_B0TEST0001",
        "get_product_listing_B0TEST0001",
        "get_asin_sales_B0TEST0001",
        "get_orders_B0TEST0001",
    ]
    client = LingxingClient("http://example.test/lingxing_config_B0TEST0001/", asin="B0TEST0001")

    payload = asyncio.run(client._call_known_tools(FakeSession(), tool_names))

    assert payload["orders"]["total_orders"] == 1
    assert payload["asin_sales"]["total_units"] == 1
    assert payload["campaigns"][0]["campaign_id"] == "c1"
    assert ("get_orders_B0TEST0001", {"start_date": "2026-06-11", "end_date": "2026-06-11"}) in calls
    assert ("get_asin_sales_B0TEST0001", {"start_date": "2026-06-11", "end_date": "2026-06-11"}) in calls
    assert ("list_campaigns_with_date_and_portfolio_with_config_B0TEST0001", {"start_date": "2026-06-11", "end_date": "2026-06-11", "page": 1, "length": 50}) in calls


def test_call_known_tools_uses_selected_date_window():
    calls = []

    class FakeSession:
        async def call_tool(self, name, args):
            calls.append((name, args))
            if name.startswith("get_orders"):
                body = {"total_orders": 3, "total_sale_total": 119.97, "currency_code": "USD"}
            elif name.startswith("get_asin_sales"):
                body = {"total_units": 3}
            elif name.startswith("list_campaigns_with_date"):
                body = {"campaigns": [{"campaign_id": "c1", "campaign_type": "manual"}]}
            else:
                body = {"listing": {"title": "Sample listing"}}
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(body))])

    tool_names = [
        "list_campaigns_with_date_and_portfolio_with_config_B0TEST0001",
        "get_product_listing_B0TEST0001",
        "get_asin_sales_B0TEST0001",
        "get_orders_B0TEST0001",
    ]
    client = LingxingClient("http://example.test/lingxing_config_B0TEST0001/", asin="B0TEST0001")

    payload = asyncio.run(
        client._call_known_tools(
            FakeSession(),
            tool_names,
            start_date="2026-06-05",
            end_date="2026-06-11",
        )
    )

    assert payload["date_window"] == {"start_date": "2026-06-05", "end_date": "2026-06-11"}
    assert ("get_orders_B0TEST0001", {"start_date": "2026-06-05", "end_date": "2026-06-11"}) in calls
    assert ("get_asin_sales_B0TEST0001", {"start_date": "2026-06-05", "end_date": "2026-06-11"}) in calls
    assert ("list_campaigns_with_date_and_portfolio_with_config_B0TEST0001", {"start_date": "2026-06-05", "end_date": "2026-06-11", "page": 1, "length": 50}) in calls


def test_call_known_tools_records_optional_context_failures():
    class FakeSession:
        async def call_tool(self, name, args):
            if "placement_profile" in name:
                raise RuntimeError("placement unavailable")
            if name.startswith("get_orders"):
                body = {"total_orders": 1, "total_sale_total": 39.99, "currency_code": "USD"}
            elif name.startswith("get_asin_sales"):
                body = {"total_units": 1}
            elif name.startswith("list_campaigns_with_date"):
                body = {"campaigns": [{"campaign_id": "c1", "campaign_type": "manual"}]}
            else:
                body = {"listing": {"title": "Sample listing"}}
            return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(body))])

    tool_names = [
        "list_campaigns_with_date_and_portfolio_with_config_B0TEST0001",
        "get_product_listing_B0TEST0001",
        "get_asin_sales_B0TEST0001",
        "get_orders_B0TEST0001",
        "list_placement_profile_B0TEST0001",
    ]
    client = LingxingClient("http://example.test/lingxing_config_B0TEST0001/", asin="B0TEST0001")

    payload = asyncio.run(client._call_known_tools(FakeSession(), tool_names))

    assert payload["placement_profile"] == {}
    assert any("placement_profile" in warning for warning in payload["warnings"])


def test_normalize_dashboard_payload_handles_lingxing_string_metrics_and_manual_sp():
    payload = {
        "orders": {"total_orders": "1", "total_sale_total": "39.99", "currency_code": "USD"},
        "asin_sales": {"total_units": "1"},
        "campaigns": [
            {
                "campaign_id": "173844737302109",
                "campaign_name": "SC_B0TEST0001_MF04_Frother_P_260610",
                "campaign_type": "manual",
                "spends": "12.46",
                "sales": "39.99",
                "orders": "1",
                "clicks": "6",
                "impressions": "1402",
            },
        ],
        "pulled_at": "2026-06-12T08:00:00Z",
        "date_window": {"start_date": "2026-06-11", "end_date": "2026-06-11"},
    }

    normalized = normalize_dashboard_payload(payload)

    assert normalized["date_window"]["start_date"] == "2026-06-11"
    assert normalized["campaigns"][0]["spend"] == 12.46
    assert normalized["campaigns"][0]["ad_scope_status"] == "sp_verified"
    assert normalized["advertising"]["sp"]["spend"] == 12.46
    assert normalized["advertising"]["sp"]["orders"] == 1


def test_normalize_dashboard_payload_extracts_sales_and_campaigns():
    payload = {
        "orders": {"total_orders": 80, "total_sale_total": 1000, "currency_code": "USD"},
        "asin_sales": {"total_units": 90},
        "campaigns": [
            {"campaign_id": "sp-1", "campaign_name": "LH-B0TEST0001-SP-exact", "spend": 100, "sales": 240, "orders": 8},
            {"campaign_id": "sd-1", "campaign_name": "LH-B0TEST0001-SD-retarget", "spend": 20, "sales": 30, "orders": 1},
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


def test_lingxing_discount_does_not_imply_amazon_deal():
    payload = {
        "orders": {"total_orders": 0, "total_sale_total": 0, "currency_code": "USD"},
        "asin_sales": {"total_units": 0},
        "campaigns": [],
        "listing": {
            "listing": {
                "title": "Sample product",
                "promotion_status": {
                    "has_coupon": False,
                    "has_discount": True,
                    "current_price": "$39.99",
                    "list_price": "",
                },
            }
        },
    }

    normalized = normalize_dashboard_payload(payload)
    listing = normalized["context"]["listing"]

    assert listing["discount_present"] is True
    assert listing["deal_present"] is False
    assert listing["coupon_present"] is False


def test_explicit_deal_signal_sets_deal_present():
    payload = {
        "orders": {"total_orders": 0, "total_sale_total": 0, "currency_code": "USD"},
        "asin_sales": {"total_units": 0},
        "campaigns": [],
        "listing": {
            "listing": {
                "title": "Sample product",
                "has_deal": True,
                "promotion_status": {
                    "has_discount": True,
                    "current_price": "$39.99",
                },
            }
        },
    }

    normalized = normalize_dashboard_payload(payload)

    assert normalized["context"]["listing"]["discount_present"] is True
    assert normalized["context"]["listing"]["deal_present"] is True


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
        asin="B0TEST0001",
        mode="live_blocked",
        reason="HTTP 404 Not Found",
    )

    assert dashboard["source_status"]["mode"] == "live_blocked"
    assert dashboard["source_status"]["blocked"] is True
    assert dashboard["sales"]["total_sales"] == 0
    assert dashboard["sales"]["total_orders"] == 0
    assert dashboard["campaigns"] == []
    assert "HTTP 404 Not Found" in dashboard["source_status"]["warnings"][0]
