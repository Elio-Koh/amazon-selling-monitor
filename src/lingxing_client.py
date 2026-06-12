"""Lingxing data access and dashboard normalization.

The Streamlit app uses this module instead of calling Lingxing directly from
page code. It supports a fixture mode for local development and a live MCP mode
for deployment once the ASIN-specific route is reachable from the host.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .ad_scope import AdScopeResolver, split_campaigns_by_scope
from .metrics import summarize_advertising


DEFAULT_ASIN = "B0GXYYZPBW"
DEFAULT_FIXTURE_PATH = Path("data/fixtures/sample_dashboard_payload.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def first_present(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_dashboard_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    orders = payload.get("orders") if isinstance(payload.get("orders"), Mapping) else {}
    asin_sales = payload.get("asin_sales") if isinstance(payload.get("asin_sales"), Mapping) else {}
    campaigns = payload.get("campaigns") if isinstance(payload.get("campaigns"), list) else []
    listing = payload.get("listing") if isinstance(payload.get("listing"), Mapping) else {}
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), Mapping) else {}

    total_sales = as_float(
        first_present(orders, ("total_sale_total", "daily_sale_total", "total_sales", "sales"))
    )
    total_orders = as_int(first_present(orders, ("total_orders", "daily_orders", "orders")))
    total_units = as_int(first_present(asin_sales, ("total_units", "units", "store_sales_units")))
    if total_units is None:
        total_units = total_orders

    resolver = AdScopeResolver(route_scope=str(payload.get("route_scope") or ""))
    split = split_campaigns_by_scope(campaigns, resolver)
    ad_summary = summarize_advertising(
        sp_campaigns=split.sp_campaigns,
        all_campaigns=split.all_campaigns,
        total_sales=total_sales,
        total_orders=total_orders,
    )

    missing_fields = []
    if total_sales is None:
        missing_fields.append("sales.total_sales")
    if total_orders is None:
        missing_fields.append("sales.total_orders")
    if total_units is None:
        missing_fields.append("sales.total_units")
    if not campaigns:
        missing_fields.append("advertising.campaigns")

    return {
        "asin": payload.get("asin") or DEFAULT_ASIN,
        "pulled_at": payload.get("pulled_at") or now_iso(),
        "sales": {
            "total_sales": total_sales or 0,
            "total_orders": total_orders or 0,
            "total_units": total_units or 0,
            "currency": orders.get("currency_code") or payload.get("currency") or "USD",
        },
        "campaigns": split.all_campaigns,
        "sp_campaigns": split.sp_campaigns,
        "ad_scope_resolutions": [item.__dict__ for item in split.resolutions],
        "advertising": ad_summary,
        "context": {
            "listing": dict(listing),
            "inventory": dict(inventory),
            "market": payload.get("market") if isinstance(payload.get("market"), Mapping) else {},
            "keyword_market": payload.get("keyword_market") if isinstance(payload.get("keyword_market"), list) else [],
            "action_history": payload.get("action_history") if isinstance(payload.get("action_history"), list) else [],
        },
        "source_status": {
            "mode": payload.get("source_mode") or "live_or_fixture",
            "freshness": payload.get("pulled_at") or now_iso(),
            "missing_fields": missing_fields,
            "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        },
    }


def load_fixture_payload(path: Path = DEFAULT_FIXTURE_PATH) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_dashboard(path: Path = DEFAULT_FIXTURE_PATH) -> Dict[str, Any]:
    payload = load_fixture_payload(path)
    payload["source_mode"] = "fixture"
    return normalize_dashboard_payload(payload)


def build_blocked_dashboard(*, asin: str, mode: str, reason: str) -> Dict[str, Any]:
    timestamp = now_iso()
    return {
        "asin": asin,
        "pulled_at": timestamp,
        "sales": {
            "total_sales": 0,
            "total_orders": 0,
            "total_units": 0,
            "currency": "USD",
        },
        "campaigns": [],
        "sp_campaigns": [],
        "ad_scope_resolutions": [],
        "advertising": {
            "sp": _empty_ad_summary(),
            "all_ads": _empty_ad_summary(),
            "by_product": {},
        },
        "context": {
            "listing": {},
            "inventory": {},
            "market": {},
            "keyword_market": [],
            "action_history": [],
        },
        "source_status": {
            "mode": mode,
            "freshness": timestamp,
            "blocked": True,
            "missing_fields": [
                "sales.total_sales",
                "sales.total_orders",
                "advertising.campaigns",
            ],
            "warnings": [reason],
        },
    }


def _empty_ad_summary() -> Dict[str, Optional[float]]:
    return {
        "spend": 0,
        "sales": 0,
        "orders": 0,
        "clicks": 0,
        "impressions": 0,
        "acos": None,
        "roas": None,
        "cpc": None,
        "ctr": None,
        "cvr": None,
        "cpa": None,
        "tacos": None,
        "order_share": None,
    }


class LingxingClient:
    """Best-effort live Lingxing MCP client wrapper.

    Live mode requires the optional `mcp` package and a Streamlit deployment
    network path that can reach the configured MCP server URL.
    """

    def __init__(self, server_url: str, asin: str = DEFAULT_ASIN) -> None:
        self.server_url = server_url.rstrip("/")
        self.asin = asin

    async def fetch_live_payload(self) -> Dict[str, Any]:
        try:
            from mcp import ClientSession  # type: ignore
            from mcp.client.sse import sse_client  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on deployment deps
            raise RuntimeError(
                "Live Lingxing MCP mode requires the optional mcp package. "
                "Install project requirements in the deployment environment."
            ) from exc

        async with sse_client(self.server_url) as streams:  # pragma: no cover
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = [tool.name for tool in tools.tools]
                return await self._call_known_tools(session, tool_names)

    async def _call_known_tools(self, session: Any, tool_names: Iterable[str]) -> Dict[str, Any]:
        names = list(tool_names)

        async def call_first(fragments: Iterable[str], args: Mapping[str, Any]) -> Any:
            for name in names:
                compact = name.lower()
                if all(fragment.lower() in compact for fragment in fragments):
                    result = await session.call_tool(name, dict(args))
                    return _mcp_result_to_json(result)
            return {}

        orders = await call_first(("get_orders", self.asin), {"asin": self.asin})
        asin_sales = await call_first(("get_asin_sales", self.asin), {"asin": self.asin})
        campaigns = await call_first(("campaign",), {"asin": self.asin})
        listing = await call_first(("listing",), {"asin": self.asin})

        if isinstance(campaigns, Mapping):
            campaign_rows = campaigns.get("campaigns") or campaigns.get("data") or []
        elif isinstance(campaigns, list):
            campaign_rows = campaigns
        else:
            campaign_rows = []

        return {
            "asin": self.asin,
            "orders": orders if isinstance(orders, Mapping) else {},
            "asin_sales": asin_sales if isinstance(asin_sales, Mapping) else {},
            "campaigns": campaign_rows if isinstance(campaign_rows, list) else [],
            "listing": listing if isinstance(listing, Mapping) else {},
            "pulled_at": now_iso(),
            "source_mode": "live_mcp",
            "warnings": [],
        }

    def fetch_dashboard(self) -> Dict[str, Any]:
        payload = asyncio.run(self.fetch_live_payload())
        return normalize_dashboard_payload(payload)


def _mcp_result_to_json(result: Any) -> Any:
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        text = getattr(content[0], "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw_text": text}
    return result
