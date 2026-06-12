"""Streamlit dashboard for Amazon selling monitor."""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
from datetime import date
from typing import Any, Dict, Iterable, Mapping

import streamlit as st

from src import lingxing_client
from src import metrics
from src.config import load_targets
from src.date_windows import PRESETS, DateWindow, resolve_date_window, today_for_timezone
from src.pangolin_client import PangolinClient, PangolinError
from src.public_context import build_public_context


st.set_page_config(
    page_title="Amazon Selling Monitor",
    page_icon="AMZ",
    layout="wide",
)


def percent(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.2f}%"


def money(value: Any, currency: str = "$") -> str:
    if value is None:
        return "-"
    return f"{currency}{float(value):,.2f}"


def number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        return f"{value:,.0f}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{float(value):,.0f}"


def safe_text(value: Any, fallback: str = "-") -> str:
    if value in (None, "", [], {}):
        return fallback
    return str(value)


def secrets_get(key: str, default: Any = None) -> Any:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def create_lingxing_client(server_url: str, asin: str, transport: str) -> Any:
    try:
        return lingxing_client.LingxingClient(
            server_url=server_url,
            asin=asin,
            transport=transport,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'transport'" not in str(exc):
            raise
        refreshed = importlib.reload(lingxing_client)
        try:
            return refreshed.LingxingClient(
                server_url=server_url,
                asin=asin,
                transport=transport,
            )
        except TypeError as retry_exc:
            if "unexpected keyword argument 'transport'" in str(retry_exc):
                raise RuntimeError(
                    "Streamlit deployment is still using a stale LingxingClient module "
                    "without transport support. Reboot the Streamlit app or clear cache and rerun."
                ) from retry_exc
            raise


def fetch_dashboard_with_reload(
    *,
    server_url: str,
    asin: str,
    transport: str,
    start_date: str,
    end_date: str,
    sp_campaign_ids: tuple[str, ...],
    known_non_sp_campaign_ids: tuple[str, ...],
) -> Dict[str, Any]:
    client = create_lingxing_client(server_url=server_url, asin=asin, transport=transport)
    try:
        return client.fetch_dashboard(
            start_date=start_date,
            end_date=end_date,
            sp_campaign_ids=sp_campaign_ids,
            known_non_sp_campaign_ids=known_non_sp_campaign_ids,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        importlib.invalidate_caches()
        refreshed = importlib.reload(lingxing_client)
        client = refreshed.LingxingClient(
            server_url=server_url,
            asin=asin,
            transport=transport,
        )
        return client.fetch_dashboard(
            start_date=start_date,
            end_date=end_date,
            sp_campaign_ids=sp_campaign_ids,
            known_non_sp_campaign_ids=known_non_sp_campaign_ids,
        )


def build_summary_with_reload(
    *,
    total_sales: float,
    total_orders: float,
    total_units: float,
    ad_summary: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Any],
    window_days: int,
) -> Dict[str, object]:
    try:
        return metrics.build_dashboard_summary(
            total_sales=total_sales,
            total_orders=total_orders,
            total_units=total_units,
            ad_summary=ad_summary,
            targets=targets,
            window_days=window_days,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        importlib.invalidate_caches()
        refreshed = importlib.reload(metrics)
        return refreshed.build_dashboard_summary(
            total_sales=total_sales,
            total_orders=total_orders,
            total_units=total_units,
            ad_summary=ad_summary,
            targets=targets,
            window_days=window_days,
        )


def enrich_public_context(data: Dict[str, Any], targets: Mapping[str, Any]) -> Dict[str, Any]:
    enabled = bool(targets.get("pangolin_enabled", True))
    token = secrets_get("PANGOLINFO_API_TOKEN") or secrets_get("PANGOLIN_API_TOKEN")
    context = data.setdefault("context", {})
    warnings = data.setdefault("source_status", {}).setdefault("warnings", [])
    if not enabled:
        warnings.append("Pangolin public context is disabled in targets config.")
        return data
    if not token:
        warnings.append("Pangolin public context skipped: PANGOLINFO_API_TOKEN is not configured.")
        return data

    asin = str(targets.get("asin") or data.get("asin") or lingxing_client.DEFAULT_ASIN)
    marketplace = str(targets.get("marketplace") or "US")
    core_keywords = [str(item) for item in targets.get("core_keywords", []) or [] if str(item).strip()]
    if not core_keywords:
        title = context.get("listing", {}).get("title") if isinstance(context.get("listing"), Mapping) else ""
        core_keywords = _keywords_from_title(str(title), limit=6)
    try:
        public = build_public_context(
            asin=asin,
            marketplace=marketplace,
            zipcode=str(targets.get("pangolin_zipcode") or "10041"),
            core_keywords=core_keywords,
            pinned_competitor_asins=[str(item) for item in targets.get("pinned_competitor_asins", []) or []],
            excluded_competitor_asins=[str(item) for item in targets.get("excluded_competitor_asins", []) or []],
            max_competitors=int(targets.get("max_competitors") or 10),
            client=PangolinClient(api_token=str(token)),
        )
    except (PangolinError, RuntimeError, ValueError) as exc:
        warnings.append(f"Pangolin public context failed: {type(exc).__name__}: {exc}")
        return data

    context.update(public)
    return data


def _keywords_from_title(title: str, *, limit: int) -> list[str]:
    normalized = " ".join(re.sub(r"[^a-zA-Z0-9 ]+", " ", title).lower().split())
    candidates = []
    for phrase in (
        "milk frother",
        "coffee frother",
        "handheld frother",
        "electric drink mixer",
        "latte frother",
        "matcha whisk",
        "protein mixer",
    ):
        if phrase in normalized:
            candidates.append(phrase)
    return candidates[:limit] or ["milk frother", "coffee frother", "handheld milk frother"][:limit]


def ensure_runtime_compatibility() -> None:
    lingxing_params = inspect.signature(lingxing_client.LingxingClient.fetch_dashboard).parameters
    metrics_params = inspect.signature(metrics.build_dashboard_summary).parameters
    stale_parts = []
    if "start_date" not in lingxing_params or "end_date" not in lingxing_params:
        stale_parts.append("src.lingxing_client")
    if "window_days" not in metrics_params:
        stale_parts.append("src.metrics")
    if not stale_parts:
        return

    importlib.invalidate_caches()
    if "src.lingxing_client" in stale_parts:
        importlib.reload(lingxing_client)
    if "src.metrics" in stale_parts:
        importlib.reload(metrics)

    refreshed_lingxing_params = inspect.signature(lingxing_client.LingxingClient.fetch_dashboard).parameters
    refreshed_metrics_params = inspect.signature(metrics.build_dashboard_summary).parameters
    still_stale = []
    if "start_date" not in refreshed_lingxing_params or "end_date" not in refreshed_lingxing_params:
        still_stale.append("src.lingxing_client")
    if "window_days" not in refreshed_metrics_params:
        still_stale.append("src.metrics")
    if still_stale:
        st.error(
            "The Streamlit process is running stale Python modules: "
            + ", ".join(still_stale)
            + ". Reboot the Streamlit app from Manage app, then rerun."
        )
        st.stop()


@st.cache_data(ttl=60, show_spinner=False)
def load_dashboard_data(
    force_refresh_key: int,
    start_date: str,
    end_date: str,
    sp_campaign_ids: tuple[str, ...] = (),
    known_non_sp_campaign_ids: tuple[str, ...] = (),
) -> Dict[str, Any]:
    del force_refresh_key
    server_url = secrets_get("LINGXING_MCP_URL")
    asin = secrets_get("ASIN", lingxing_client.DEFAULT_ASIN)
    transport = secrets_get("LINGXING_MCP_TRANSPORT", "auto")
    if server_url:
        try:
            dashboard = fetch_dashboard_with_reload(
                server_url=str(server_url),
                asin=str(asin),
                transport=str(transport),
                start_date=start_date,
                end_date=end_date,
                sp_campaign_ids=sp_campaign_ids,
                known_non_sp_campaign_ids=known_non_sp_campaign_ids,
            )
            return enrich_public_context(dashboard, load_targets())
        except Exception as exc:
            blocked = lingxing_client.build_blocked_dashboard(
                asin=str(asin),
                mode="live_blocked",
                reason=(
                    "Lingxing live pull failed. The configured LINGXING_MCP_URL did not complete "
                    "an MCP session. "
                    f"Configured URL: {server_url}. Configured transport: {transport}. "
                    f"Error: {type(exc).__name__}: {exc}"
                ),
            )
            blocked["date_window"] = {"start_date": start_date, "end_date": end_date}
            return enrich_public_context(blocked, load_targets())
    dashboard = lingxing_client.load_fixture_dashboard(
        sp_campaign_ids=sp_campaign_ids,
        known_non_sp_campaign_ids=known_non_sp_campaign_ids,
    )
    dashboard["date_window"] = {"start_date": start_date, "end_date": end_date}
    dashboard["source_status"]["mode"] = "fixture_no_live_url"
    dashboard["source_status"]["warnings"].append("LINGXING_MCP_URL is not configured.")
    return enrich_public_context(dashboard, load_targets())


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 2.2rem; max-width: 1180px; }
        div[data-testid="stMetric"] {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 14px 16px;
            background: #ffffff;
            min-height: 112px;
        }
        div[data-testid="stMetricLabel"] p { color: #4b5563; font-size: 0.88rem; }
        div[data-testid="stMetricValue"] { color: #111827; }
        .status-strip {
            border: 1px solid #dbeafe;
            border-radius: 8px;
            padding: 12px 14px;
            background: #f8fbff;
            color: #1f2937;
        }
        .section-note { color: #6b7280; font-size: 0.9rem; }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 2px 8px;
            background: #eef2ff;
            color: #3730a3;
            font-size: 0.78rem;
            margin-left: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(targets: Mapping[str, Any]) -> DateWindow:
    timezone_name = str(targets.get("report_timezone") or "Asia/Shanghai")
    anchor = today_for_timezone(timezone_name)
    st.title("Amazon Selling Monitor")
    st.caption(f"ASIN: {targets.get('asin', lingxing_client.DEFAULT_ASIN)} | Marketplace: {targets.get('marketplace', 'US')}")

    cols = st.columns([1.4, 1, 1, 1])
    preset = cols[0].selectbox("Date Window", PRESETS, index=1)
    preview_window = resolve_date_window(preset, anchor_date=anchor)
    start_default = date.fromisoformat(preview_window.start_date) if preset != "Custom" else anchor
    end_default = date.fromisoformat(preview_window.end_date) if preset != "Custom" else anchor
    custom_start = cols[1].date_input("Start Date", start_default)
    custom_end = cols[2].date_input("End Date", end_default)
    if cols[3].button("Refresh Data", use_container_width=True):
        st.session_state.refresh_counter = st.session_state.get("refresh_counter", 0) + 1
        load_dashboard_data.clear()

    selected_start = _as_date(custom_start)
    selected_end = _as_date(custom_end)
    effective_preset = preset
    if selected_start != start_default or selected_end != end_default:
        effective_preset = "Custom"
    return resolve_date_window(
        effective_preset,
        anchor_date=anchor,
        custom_start=selected_start,
        custom_end=selected_end,
    )


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return today_for_timezone()


def render_source_status(data: Dict[str, Any], window: DateWindow) -> None:
    status = data["source_status"]
    mode = status["mode"]
    partial_badge = '<span class="badge">partial day</span>' if window.is_partial else ""
    if mode == "live_mcp":
        body = f"Source: Lingxing live MCP. Window: {window.start_date} to {window.end_date}. Pulled at: {data['pulled_at']} {partial_badge}"
        st.markdown(f'<div class="status-strip">{body}</div>', unsafe_allow_html=True)
    elif status.get("blocked"):
        st.error(f"Live data unavailable. Mode: {mode}. Checked at: {data['pulled_at']}")
    elif mode.startswith("fixture"):
        st.warning(f"Using sample data. Mode: {mode}. Window: {window.start_date} to {window.end_date}. Updated at: {data['pulled_at']}")
    else:
        st.info(f"Source mode: {mode}. Window: {window.start_date} to {window.end_date}. Updated at: {data['pulled_at']}")

    missing = status.get("missing_fields") or []
    warnings = status.get("warnings") or []
    if missing:
        st.caption("Missing fields: " + ", ".join(missing))
    if warnings:
        with st.expander("Source notes", expanded=False):
            for warning in warnings:
                st.write(f"- {warning}")
            if status.get("blocked"):
                st.write("- This page does not show fixture business metrics while live data is blocked.")
                st.write("- Check Streamlit secrets: `LINGXING_MCP_URL` and `LINGXING_MCP_TRANSPORT`.")


def render_metric_row(summary: Dict[str, Any], currency: str) -> None:
    sales = summary["sales"]
    sp_goal = summary["sp_goal"]
    advertising = summary["advertising"]
    sp = advertising["sp"]
    all_ads = advertising["all_ads"]

    cols = st.columns(6)
    cols[0].metric("Total Sales", money(sales["total_sales"], currency))
    cols[1].metric("Total Orders", number(sales["total_orders"]))
    cols[2].metric("SP Orders", number(sp_goal["orders"]), f"Target {number(sp_goal['orders_min'])}-{number(sp_goal['orders_max'])}")
    cols[3].metric("SP ACOS", percent(sp["acos"]), f"Target {percent(sp_goal['target_acos'])}")
    cols[4].metric("SP Spend", money(sp["spend"], currency), f"Budget {money(sp_goal['window_budget'], currency)}")
    cols[5].metric("All-Ads TACOS", percent(all_ads["tacos"]))


def render_overview(data: Dict[str, Any], summary: Dict[str, Any], currency: str, window: DateWindow) -> None:
    render_metric_row(summary, currency)
    st.divider()

    sp_goal = summary["sp_goal"]
    all_ads = summary["advertising"]["all_ads"]
    inventory = data["context"]["inventory"]
    listing = data["context"].get("public_listing") or data["context"]["listing"]

    cols = st.columns(3)
    with cols[0]:
        st.subheader("SP Goal Pace")
        st.progress(min(float(sp_goal["orders_progress_max"] or 0), 1.0), text=f"Order target pace for {window.label}")
        st.write(f"Order status: `{sp_goal['orders_status']}`")
        st.write(f"Budget usage: {percent(sp_goal['budget_used_pct'])}")
        st.write(f"ACOS gap: {percent(sp_goal['acos_delta'])}")

    with cols[1]:
        st.subheader("All Advertising")
        st.write(f"Spend: {money(all_ads['spend'], currency)}")
        st.write(f"Sales: {money(all_ads['sales'], currency)}")
        st.write(f"ACOS: {percent(all_ads['acos'])}")
        st.write(f"ROAS: {number(all_ads['roas'])}")

    with cols[2]:
        st.subheader("Inventory & Listing")
        st.write(f"FBA fulfillable: {number(inventory.get('fba_fulfillable'))}")
        st.write(f"Days of supply: {number(inventory.get('days_of_supply'))}")
        st.write(f"Stockout risk: `{safe_text(inventory.get('stockout_risk'))}`")
        st.write(f"Price: {safe_text(listing.get('price_display') or listing.get('price'))}")


def render_sp_ads(data: Dict[str, Any], summary: Dict[str, Any], currency: str) -> None:
    sp = summary["advertising"]["sp"]
    cols = st.columns(6)
    cols[0].metric("SP Spend", money(sp["spend"], currency))
    cols[1].metric("SP Sales", money(sp["sales"], currency))
    cols[2].metric("SP Orders", number(sp["orders"]))
    cols[3].metric("SP ACOS", percent(sp["acos"]))
    cols[4].metric("SP CVR", percent(sp["cvr"]))
    cols[5].metric("SP CPA", money(sp["cpa"], currency))
    st.dataframe(_campaign_table(data["sp_campaigns"]), use_container_width=True, hide_index=True)


def render_all_ads(data: Dict[str, Any], summary: Dict[str, Any], currency: str) -> None:
    by_product = summary["advertising"]["by_product"]
    rows = []
    for ad_product, metrics in sorted(by_product.items()):
        rows.append(
            {
                "Ad Product": ad_product,
                "Spend": metrics["spend"],
                "Sales": metrics["sales"],
                "Orders": metrics["orders"],
                "ACOS": metrics["acos"],
                "ROAS": metrics["roas"],
                "CPC": metrics["cpc"],
                "CTR": metrics["ctr"],
                "CVR": metrics["cvr"],
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.subheader("Campaign Detail")
    st.dataframe(_campaign_table(data["campaigns"]), use_container_width=True, hide_index=True)


def _campaign_table(campaigns: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in campaigns:
        rows.append(
            {
                "Campaign ID": row.get("campaign_id"),
                "Campaign Name": row.get("campaign_name"),
                "Type": row.get("campaign_type") or row.get("targeting_type"),
                "Status": row.get("status"),
                "Ad Product": row.get("ad_product"),
                "Scope Evidence": row.get("ad_scope_evidence"),
                "Spend": row.get("spend"),
                "Sales": row.get("sales"),
                "Orders": row.get("orders"),
                "Clicks": row.get("clicks"),
                "Impressions": row.get("impressions"),
            }
        )
    return rows


def render_context(data: Dict[str, Any], summary: Dict[str, Any], currency: str) -> None:
    context = data["context"]
    listing = context.get("public_listing") or context.get("listing", {})
    inventory = context.get("inventory", {})
    market = context.get("market", {})
    core_keywords = context.get("core_keywords", [])
    keyword_market = context.get("keyword_market", [])
    placement_profile = context.get("placement_profile", [])
    keyword_placement = context.get("keyword_placement", [])
    action_history = context.get("action_history", [])
    sales = data.get("sales", {})
    all_ads = summary["advertising"]["all_ads"]
    sp = summary["advertising"]["sp"]

    st.subheader("Context Quality")
    render_key_values(
        {
            "Source": data["source_status"].get("mode"),
            "Pulled At": data.get("pulled_at"),
            "Missing Fields": ", ".join(data["source_status"].get("missing_fields") or []) or "None",
            "Warnings": len(data["source_status"].get("warnings") or []),
        }
    )

    cols = st.columns(2)
    with cols[0]:
        st.subheader("Business & Profit")
        render_key_values(
            {
                "Average Selling Price": money(_safe_float(sales.get("total_sales")) / _safe_float(sales.get("total_orders")), currency)
                if _safe_float(sales.get("total_orders")) else "-",
                "Target ACOS": percent(summary["sp_goal"]["target_acos"]),
                "SP ACOS": percent(sp["acos"]),
                "Break-even ACOS": safe_text(context.get("business_financial", {}).get("break_even_acos")),
                "Contribution Margin": safe_text(context.get("business_financial", {}).get("contribution_margin")),
            }
        )

    with cols[1]:
        st.subheader("Inventory & Logistics")
        render_key_values(
            {
                "FBA Fulfillable": number(inventory.get("fba_fulfillable")),
                "Days of Supply": number(inventory.get("days_of_supply")),
                "Inbound Quantity": number(inventory.get("inbound_quantity")),
                "Inbound ETA": safe_text(inventory.get("inbound_eta")),
                "Stockout Risk": safe_text(inventory.get("stockout_risk")),
                "Delivery Promise": safe_text(inventory.get("own_delivery_promise")),
            }
        )

    cols = st.columns(2)
    with cols[0]:
        st.subheader("Listing & Offer")
        if listing.get("main_image_url"):
            st.image(listing["main_image_url"], width=180)
        render_key_values(
            {
                "Title": safe_text(listing.get("title")),
                "Price": safe_text(listing.get("price_display") or listing.get("price")),
                "List Price": safe_text(listing.get("list_price_display")),
                "Coupon": safe_text(listing.get("coupon_present")),
                "Discount / Price Reduction": safe_text(listing.get("discount_present")),
                "Amazon Deal": safe_text(listing.get("deal_present")),
                "Rating": safe_text(listing.get("rating")),
                "Reviews": number(listing.get("review_count")),
                "Fulfillment": safe_text(listing.get("fulfillment_method")),
                "Delivery Promise": safe_text(listing.get("delivery_promise")),
                "Source": safe_text(listing.get("source")),
                "Freshness": safe_text(listing.get("freshness")),
            }
        )

    with cols[1]:
        st.subheader("Sales Trend")
        render_key_values(
            {
                "Window Sales": money(sales.get("total_sales"), currency),
                "Window Orders": number(sales.get("total_orders")),
                "Window Units": number(sales.get("total_units")),
                "All-Ads Spend": money(all_ads.get("spend"), currency),
                "All-Ads TACOS": percent(all_ads.get("tacos")),
                "Ad Order Share": percent(all_ads.get("order_share")),
            }
        )

    st.subheader("Core Keywords")
    if core_keywords:
        st.dataframe(_core_keyword_table(core_keywords), use_container_width=True, hide_index=True)
    else:
        st.caption("Core keyword context is not available in the current pull.")

    st.subheader("Market & Competitors")
    selected_competitors = market.get("selected_competitors") if isinstance(market, Mapping) else []
    if selected_competitors:
        st.dataframe(_competitor_table(selected_competitors), use_container_width=True, hide_index=True)
        render_key_values(
            {
                "Category CVR": safe_text(market.get("category_average_cvr")),
                "CVR Source": safe_text(market.get("category_average_cvr_source")),
                "Competitor Source": safe_text(market.get("selected_competitors_source") or market.get("source")),
                "Freshness": safe_text(market.get("freshness")),
                "Confidence": safe_text(market.get("confidence")),
            }
        )
    else:
        st.caption("No selected competitor context is available. Connect Pangolin public context or configure core keywords.")

    st.subheader("Keyword & Placement")
    if keyword_placement:
        st.dataframe(keyword_placement, use_container_width=True, hide_index=True)
    elif keyword_market:
        st.dataframe(keyword_market, use_container_width=True, hide_index=True)
    elif placement_profile:
        st.dataframe(placement_profile, use_container_width=True, hide_index=True)
    else:
        st.caption("No Lingxing keyword or placement context is available in the current pull.")

    st.subheader("Action History")
    if action_history:
        st.dataframe(action_history, use_container_width=True)
    else:
        st.caption("No prior action history is available in the current pull.")


def render_key_values(values: Mapping[str, Any]) -> None:
    rows = [{"Metric": key, "Value": safe_text(value)} for key, value in values.items()]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _core_keyword_table(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "Keyword": row.get("keyword"),
                "Tier": row.get("tier"),
                "Rank Status": row.get("rank_status"),
                "Organic Rank": row.get("own_organic_rank"),
                "Ad Rank": row.get("own_ad_rank"),
                "Source": row.get("source"),
                "Confidence": row.get("confidence"),
            }
        )
    return out


def _competitor_table(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        rank = row.get("rank_relationship") if isinstance(row.get("rank_relationship"), Mapping) else {}
        out.append(
            {
                "Tier": row.get("tier"),
                "ASIN": row.get("asin"),
                "Title": row.get("title"),
                "Price": row.get("price"),
                "Rating": row.get("rating"),
                "Reviews": row.get("review_count"),
                "Coupon": row.get("coupon_present"),
                "Deal": row.get("deal_present"),
                "Best Organic Rank": rank.get("best_organic_rank"),
                "Best Ad Rank": rank.get("best_ad_rank"),
                "Matched Keywords": ", ".join(str(item) for item in row.get("keywords", []) or []),
                "Why Selected": ", ".join(str(item) for item in row.get("why_selected", []) or []),
            }
        )
    return out


def render_details(data: Dict[str, Any]) -> None:
    st.subheader("Ad Scope Evidence")
    st.dataframe(data["ad_scope_resolutions"], use_container_width=True, hide_index=True)
    st.subheader("Raw Snapshot")
    st.download_button(
        "Download normalized snapshot JSON",
        data=json.dumps(data, ensure_ascii=False, indent=2, default=str),
        file_name=f"{data['asin']}_dashboard_snapshot.json",
        mime="application/json",
    )
    with st.expander("Show normalized JSON", expanded=False):
        st.json(data)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    inject_css()
    ensure_runtime_compatibility()
    targets = load_targets()
    if "refresh_counter" not in st.session_state:
        st.session_state.refresh_counter = 0

    window = render_header(targets)
    with st.spinner("Pulling latest data..."):
        data = load_dashboard_data(
            st.session_state.refresh_counter,
            window.start_date,
            window.end_date,
            tuple(str(item) for item in targets.get("sp_campaign_ids", []) or []),
            tuple(str(item) for item in targets.get("known_non_sp_campaign_ids", []) or []),
        )

    render_source_status(data, window)
    currency = "$" if data["sales"].get("currency", "USD") == "USD" else ""
    summary = build_summary_with_reload(
        total_sales=data["sales"]["total_sales"],
        total_orders=data["sales"]["total_orders"],
        total_units=data["sales"]["total_units"],
        ad_summary=data["advertising"],
        targets=targets,
        window_days=window.days,
    )

    tabs = st.tabs(["Operating Overview", "SP Ads", "Advertising Diagnostics", "Business Context", "Raw Data"])
    with tabs[0]:
        render_overview(data, summary, currency, window)
    with tabs[1]:
        render_sp_ads(data, summary, currency)
    with tabs[2]:
        render_all_ads(data, summary, currency)
    with tabs[3]:
        render_context(data, summary, currency)
    with tabs[4]:
        render_details(data)


if __name__ == "__main__":
    main()
