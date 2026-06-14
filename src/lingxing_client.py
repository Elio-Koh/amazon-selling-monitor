"""Lingxing data access and dashboard normalization.

The Streamlit app uses this module instead of calling Lingxing directly from
page code. It supports a fixture mode for local development and a live MCP mode
for deployment once the ASIN-specific route is reachable from the host.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .ad_scope import AdScopeResolver, split_campaigns_by_scope
from .metrics import summarize_advertising


DEFAULT_ASIN = "B0GXYYZPBW"
DEFAULT_FIXTURE_PATH = Path("data/fixtures/sample_dashboard_payload.json")
VALID_MCP_TRANSPORTS = {"auto", "streamable_http", "sse"}


class MCPTransportError(RuntimeError):
    """Raised when a transport cannot connect, initialize, or list tools."""


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
    raw_campaigns = payload.get("campaigns") if isinstance(payload.get("campaigns"), list) else []
    campaigns = [_normalize_campaign_row(row) for row in raw_campaigns if isinstance(row, Mapping)]
    listing_payload = payload.get("listing") if isinstance(payload.get("listing"), Mapping) else {}
    listing = _normalize_listing(listing_payload)
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), Mapping) else {}
    variations = _normalize_variations(payload.get("child_asins") or payload.get("variations"))
    sales_family = payload.get("sales_family") if isinstance(payload.get("sales_family"), Mapping) else {}
    parent_asin = payload.get("parent_asin") or sales_family.get("parent_asin")
    selected_child_asin = payload.get("selected_child_asin") or sales_family.get("selected_child_asin") or payload.get("asin") or DEFAULT_ASIN

    total_sales = as_float(
        first_present(orders, ("total_sale_total", "daily_sale_total", "total_sales", "sales"))
    )
    total_orders = as_int(first_present(orders, ("total_orders", "daily_orders", "orders")))
    total_units = as_int(first_present(asin_sales, ("total_units", "units", "store_sales_units")))
    if total_units is None:
        total_units = total_orders

    resolver = AdScopeResolver(
        whitelist=payload.get("sp_campaign_ids") if isinstance(payload.get("sp_campaign_ids"), list) else [],
        known_non_sp=payload.get("known_non_sp_campaign_ids") if isinstance(payload.get("known_non_sp_campaign_ids"), list) else [],
        route_scope=str(payload.get("route_scope") or ""),
    )
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
        "parent_asin": parent_asin,
        "selected_child_asin": selected_child_asin,
        "pulled_at": payload.get("pulled_at") or now_iso(),
        "date_window": payload.get("date_window") if isinstance(payload.get("date_window"), Mapping) else {},
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
        "variations": variations,
        "sales_family": dict(sales_family),
        "context": {
            "listing": dict(listing),
            "inventory": dict(inventory),
            "market": payload.get("market") if isinstance(payload.get("market"), Mapping) else {},
            "keyword_market": payload.get("keyword_market") if isinstance(payload.get("keyword_market"), list) else [],
            "placement_profile": _extract_rows(payload.get("placement_profile")),
            "keyword_placement": _extract_rows(payload.get("keyword_placement")),
            "action_history": payload.get("action_history") if isinstance(payload.get("action_history"), list) else [],
        },
        "source_status": {
            "mode": payload.get("source_mode") or "live_or_fixture",
            "freshness": payload.get("pulled_at") or now_iso(),
            "missing_fields": missing_fields,
            "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        },
    }


def _normalize_variations(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        row.setdefault("asin", first_present(item, ("child_asin", "childAsin")))
        row.setdefault("parent_asin", first_present(item, ("parentAsin",)))
        row.setdefault("title", first_present(item, ("product_name", "productName", "item_name")))
        row.setdefault("image_url", first_present(item, ("small_image_url", "main_image", "pic_url")))
        row.setdefault("seller_sku", first_present(item, ("sku", "local_sku", "local_sku_name")))
        row["sales"] = as_float(first_present(row, ("sales", "amount", "total_sale_total", "total_sales"))) or 0
        row["orders"] = as_int(first_present(row, ("orders", "order_items", "total_orders"))) or 0
        row["units"] = as_int(first_present(row, ("units", "volume", "quantity", "total_units"))) or 0
        row["ad_spend"] = as_float(first_present(row, ("ad_spend", "spend", "spends", "ads_spend"))) or 0
        row["inventory"] = as_int(first_present(row, ("inventory", "fba_fulfillable", "afn_fulfillable_quantity"))) or 0
        rows.append(row)
    return rows


def _normalize_campaign_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    out["campaign_id"] = first_present(row, ("campaign_id", "id"))
    out["campaign_name"] = first_present(row, ("campaign_name", "name"))
    out["campaign_type"] = first_present(row, ("campaign_type", "targeting_type"))
    out["targeting_type"] = first_present(row, ("targeting_type", "campaign_type"))
    out["status"] = first_present(row, ("status", "campaign_state", "state"))
    out["spend"] = as_float(first_present(row, ("spend", "spends", "cost"))) or 0
    out["sales"] = as_float(first_present(row, ("sales", "ad_sales", "direct_sales"))) or 0
    out["orders"] = as_float(first_present(row, ("orders", "ad_orders", "direct_orders"))) or 0
    out["clicks"] = as_float(row.get("clicks")) or 0
    out["impressions"] = as_float(row.get("impressions")) or 0
    if "bidding" in row and "placement_bid_adjustments" not in out:
        out["placement_bid_adjustments"] = row.get("bidding")
    return out


def _normalize_listing(listing: Mapping[str, Any]) -> Dict[str, Any]:
    raw_listing = listing.get("listing")
    if isinstance(raw_listing, Mapping):
        listing = raw_listing
    promotion = listing.get("promotion_status") if isinstance(listing.get("promotion_status"), Mapping) else {}
    normalized = dict(listing)
    normalized.setdefault("price_display", promotion.get("current_price") or listing.get("price"))
    normalized.setdefault("list_price_display", promotion.get("list_price") or listing.get("list_price"))
    normalized.setdefault("coupon_present", promotion.get("has_coupon") if "has_coupon" in promotion else listing.get("has_coupon"))
    normalized.setdefault("discount_present", promotion.get("has_discount") if "has_discount" in promotion else listing.get("has_discount"))
    normalized.setdefault("deal_present", _explicit_deal_present(listing, promotion))
    normalized.setdefault("coupon_pct", promotion.get("discount_percentage"))
    return normalized


def _explicit_deal_present(listing: Mapping[str, Any], promotion: Mapping[str, Any]) -> bool:
    for source in (listing, promotion):
        for key in ("deal_present", "has_deal", "is_deal", "lightning_deal", "best_deal", "deal"):
            if key not in source:
                continue
            value = source.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "yes", "1", "deal", "lightning_deal", "best_deal"}
            return bool(value)
        for key in ("deal_status", "deal_type", "badge"):
            value = source.get(key)
            if isinstance(value, str) and "deal" in value.lower():
                return True
    return False


def _extract_rows(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "rows", "items", "campaigns", "keywords"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def load_fixture_payload(path: Path = DEFAULT_FIXTURE_PATH) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_dashboard(
    path: Path = DEFAULT_FIXTURE_PATH,
    *,
    sp_campaign_ids: Optional[Iterable[str]] = None,
    known_non_sp_campaign_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    payload = load_fixture_payload(path)
    payload["source_mode"] = "fixture"
    payload["sp_campaign_ids"] = list(sp_campaign_ids or [])
    payload["known_non_sp_campaign_ids"] = list(known_non_sp_campaign_ids or [])
    return normalize_dashboard_payload(payload)


def build_blocked_dashboard(*, asin: str, mode: str, reason: str) -> Dict[str, Any]:
    timestamp = now_iso()
    return {
        "asin": asin,
        "pulled_at": timestamp,
        "date_window": {},
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
            "placement_profile": [],
            "keyword_placement": [],
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

    def __init__(self, server_url: str, asin: str = DEFAULT_ASIN, transport: str = "auto") -> None:
        self.server_url = _normalize_mcp_url(server_url)
        self.asin = asin
        self.transport = transport.strip().lower()
        if self.transport not in VALID_MCP_TRANSPORTS:
            raise ValueError(
                f"Unsupported Lingxing MCP transport: {transport}. "
                f"Expected one of: {', '.join(sorted(VALID_MCP_TRANSPORTS))}."
            )

    async def fetch_live_payload(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        if self.transport == "auto":
            try:
                return await self._fetch_with_transport("streamable_http", start_date=start_date, end_date=end_date)
            except MCPTransportError as streamable_error:
                try:
                    return await self._fetch_with_transport("sse", start_date=start_date, end_date=end_date)
                except Exception as sse_error:
                    raise RuntimeError(
                        "Lingxing MCP auto transport failed. "
                        f"streamable_http: {streamable_error}; "
                        f"sse: {type(sse_error).__name__}: {sse_error}"
                    ) from sse_error
        return await self._fetch_with_transport(self.transport, start_date=start_date, end_date=end_date)

    async def _fetch_with_transport(self, transport: str, *, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        if transport == "streamable_http":
            return await self._fetch_streamable_http(start_date=start_date, end_date=end_date)
        if transport == "sse":
            return await self._fetch_sse(start_date=start_date, end_date=end_date)
        raise ValueError(f"Unsupported Lingxing MCP transport: {transport}")

    async def _fetch_streamable_http(self, *, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        ClientSession = _load_client_session()
        try:
            from mcp.client.streamable_http import streamable_http_client  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on deployment deps
            raise MCPTransportError("streamable_http transport is unavailable in the installed mcp package") from exc

        initialized = False
        try:
            async with streamable_http_client(self.server_url) as streams:  # pragma: no cover
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    tool_names = await _initialize_and_list_tools(session, "streamable_http")
                    initialized = True
                    return await self._call_known_tools(session, tool_names, start_date=start_date, end_date=end_date)
        except Exception as exc:
            if initialized:
                raise
            if isinstance(exc, MCPTransportError):
                raise
            raise MCPTransportError(f"streamable_http transport failed before tool calls: {exc}") from exc

    async def _fetch_sse(self, *, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        ClientSession = _load_client_session()
        try:
            from mcp.client.sse import sse_client  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on deployment deps
            raise MCPTransportError("sse transport is unavailable in the installed mcp package") from exc

        initialized = False
        try:
            async with sse_client(self.server_url) as streams:  # pragma: no cover
                async with ClientSession(*streams) as session:
                    tool_names = await _initialize_and_list_tools(session, "sse")
                    initialized = True
                    return await self._call_known_tools(session, tool_names, start_date=start_date, end_date=end_date)
        except Exception as exc:
            if initialized:
                raise
            if isinstance(exc, MCPTransportError):
                raise
            raise MCPTransportError(f"sse transport failed before tool calls: {exc}") from exc

    async def _call_known_tools(
        self,
        session: Any,
        tool_names: Iterable[str],
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        names = list(tool_names)
        default_start, default_end = _default_report_dates()
        start_date = start_date or default_start
        end_date = end_date or default_end
        dated_args = {
            "start_date": start_date,
            "end_date": end_date,
        }
        campaign_args = {
            "start_date": start_date,
            "end_date": end_date,
            "page": 1,
            "length": 50,
        }
        warnings: List[str] = []

        async def call_first(fragments: Iterable[str], args: Mapping[str, Any]) -> Any:
            for name in names:
                compact = name.lower()
                if all(fragment.lower() in compact for fragment in fragments):
                    result = await session.call_tool(name, dict(args))
                    return _mcp_result_to_json(result)
            return {}

        async def call_optional(fragments: Iterable[str], args: Mapping[str, Any]) -> Any:
            try:
                return await call_first(fragments, args)
            except Exception as exc:
                warnings.append(
                    f"Optional Lingxing context pull failed for {'/'.join(fragments)}: {type(exc).__name__}: {exc}"
                )
                return {}

        orders = await call_first(("get_orders", self.asin), dated_args)
        asin_sales = await call_first(("get_asin_sales", self.asin), dated_args)
        campaigns = await call_first(("list_campaigns_with_date", self.asin), campaign_args)
        if not campaigns:
            campaigns = await call_first(("campaign",), campaign_args)
        listing = await call_first(("listing", self.asin), {"asin": self.asin})
        placement_profile = await call_optional(
            ("placement_profile", self.asin),
            {**campaign_args, "sort_field": "spends", "sort_type": "desc", "with_ring": 0},
        )
        keyword_placement = await call_optional(
            ("keywords_placement",),
            {**campaign_args, "sort_field": "spends", "sort_type": "desc"},
        )

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
            "placement_profile": placement_profile,
            "keyword_placement": keyword_placement,
            "date_window": {"start_date": start_date, "end_date": end_date},
            "pulled_at": now_iso(),
            "source_mode": "live_mcp",
            "warnings": warnings,
        }

    def fetch_dashboard(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        *,
        sp_campaign_ids: Optional[Iterable[str]] = None,
        known_non_sp_campaign_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        payload = asyncio.run(self.fetch_live_payload(start_date=start_date, end_date=end_date))
        payload["sp_campaign_ids"] = list(sp_campaign_ids or [])
        payload["known_non_sp_campaign_ids"] = list(known_non_sp_campaign_ids or [])
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


def _load_client_session() -> Any:
    try:
        from mcp import ClientSession  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on deployment deps
        raise RuntimeError(
            "Live Lingxing MCP mode requires the optional `mcp` package. "
            "Install project requirements in a Python 3.10+ environment."
        ) from exc
    return ClientSession


async def _initialize_and_list_tools(session: Any, transport: str) -> Iterable[str]:
    try:
        await session.initialize()
        tools = await session.list_tools()
    except Exception as exc:
        raise MCPTransportError(f"{transport} transport failed during MCP initialize/list_tools: {exc}") from exc
    return [tool.name for tool in tools.tools]


def _normalize_mcp_url(server_url: str) -> str:
    url = server_url.strip()
    if not url:
        raise ValueError("Lingxing MCP server_url cannot be empty.")
    fastmcp_config_markers = (
        "/lingxing_config_",
        "/xingshang_config_",
        "/xingshang_advertiser_config_",
        "/xingshang_sb_config_",
        "/luckee_config_",
    )
    if not url.endswith("/") and any(marker in url for marker in fastmcp_config_markers):
        return f"{url}/"
    return url


def _default_report_dates() -> Tuple[str, str]:
    report_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    value = report_date.isoformat()
    return value, value
