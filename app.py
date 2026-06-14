"""Streamlit dashboard for Amazon selling monitor."""

from __future__ import annotations

import copy
import html
import importlib
import inspect
import json
import os
import re
from datetime import date
from typing import Any, Dict, Iterable, Mapping

import streamlit as st

from src import lingxing_api_client
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


def offer_value(value: Any) -> str:
    if value in (None, "", [], {}):
        return "None"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def secrets_get(key: str, default: Any = None) -> Any:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def target_int(targets: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(targets.get(key) or default)
    except (TypeError, ValueError):
        return default


def app_version() -> str:
    for key in ("STREAMLIT_GIT_COMMIT", "SOURCE_VERSION", "GIT_COMMIT", "COMMIT_SHA"):
        value = os.environ.get(key)
        if value:
            return str(value)[:8]
    return "local"


def lingxing_api_secret_values(targets: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ASIN": secrets_get("ASIN", targets.get("asin", lingxing_client.DEFAULT_ASIN)),
        "LINGXING_PARENT_ASIN": secrets_get(
            "LINGXING_PARENT_ASIN",
            targets.get("lingxing_parent_asin") or targets.get("parent_asin"),
        ),
        "LINGXING_API_BASE_URL": secrets_get("LINGXING_API_BASE_URL"),
        "LINGXING_ACCOUNT": secrets_get("LINGXING_ACCOUNT"),
        "LINGXING_PROFILE_ID": secrets_get("LINGXING_PROFILE_ID"),
        "LINGXING_USER_TOKEN": secrets_get("LINGXING_USER_TOKEN"),
        "LINGXING_API_TIMEOUT_SECONDS": secrets_get("LINGXING_API_TIMEOUT_SECONDS", 8),
    }


def has_lingxing_api_config(values: Mapping[str, Any]) -> bool:
    keys = (
        "LINGXING_API_BASE_URL",
        "LINGXING_ACCOUNT",
        "LINGXING_PROFILE_ID",
        "LINGXING_USER_TOKEN",
        "LINGXING_PARENT_ASIN",
    )
    return any(values.get(key) not in (None, "") for key in keys)


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
    core_keywords = [str(item) for item in targets.get("core_keywords", []) or [] if str(item).strip()]
    if not core_keywords:
        title = context.get("listing", {}).get("title") if isinstance(context.get("listing"), Mapping) else ""
        core_keywords = _keywords_from_title(str(title), limit=6)
    if not enabled:
        _set_public_context_status(context, "disabled", "Pangolin public context is disabled in targets config.", core_keywords)
        warnings.append("Pangolin public context is disabled in targets config.")
        return data
    if not token:
        _set_public_context_status(context, "missing_token", "PANGOLINFO_API_TOKEN is not configured.", core_keywords)
        warnings.append("Pangolin public context skipped: PANGOLINFO_API_TOKEN is not configured.")
        return data

    asin = str(targets.get("asin") or data.get("asin") or lingxing_client.DEFAULT_ASIN)
    marketplace = str(targets.get("marketplace") or "US")
    try:
        public = build_public_context(
            asin=asin,
            marketplace=marketplace,
            zipcode=str(targets.get("pangolin_zipcode") or "10041"),
            core_keywords=core_keywords,
            pinned_competitor_asins=[str(item) for item in targets.get("pinned_competitor_asins", []) or []],
            excluded_competitor_asins=[str(item) for item in targets.get("excluded_competitor_asins", []) or []],
            max_competitors=target_int(targets, "max_competitors", 10),
            max_keywords=target_int(targets, "pangolin_max_keywords", 3),
            category_rankings_enabled=bool(targets.get("pangolin_category_rankings_enabled", True)),
            category_keyword=safe_text(targets.get("pangolin_category_keyword"), ""),
            include_product_of_category=bool(targets.get("pangolin_include_product_of_category", True)),
            include_best_sellers=bool(targets.get("pangolin_include_best_sellers", True)),
            include_new_releases=bool(targets.get("pangolin_include_new_releases", True)),
            client=PangolinClient(api_token=str(token)),
        )
    except (PangolinError, RuntimeError, ValueError, TimeoutError, OSError) as exc:
        _set_public_context_status(context, "failed", f"{type(exc).__name__}: {exc}", core_keywords)
        warnings.append(f"Pangolin public context failed: {type(exc).__name__}: {exc}")
        return data

    context.update(public)
    status = public.get("public_context_status") if isinstance(public.get("public_context_status"), Mapping) else None
    if status:
        context["public_context_status"] = dict(status)
        if status.get("status") == "partial":
            warnings.append(str(status.get("message") or "Pangolin public context loaded with partial failures."))
    else:
        context["public_context_status"] = {
            "status": "ok",
            "message": "Pangolin public context loaded.",
            "source": "pangolin",
            "freshness": context.get("public_listing", {}).get("freshness"),
        }
    return data


def _set_public_context_status(context: Dict[str, Any], status: str, message: str, core_keywords: Iterable[str]) -> None:
    context["public_context_status"] = {
        "status": status,
        "message": message,
        "source": "pangolin",
        "freshness": None,
    }
    if not context.get("core_keywords"):
        context["core_keywords"] = [
            {
                "keyword": keyword,
                "tier": "configured_core" if idx < 3 else "configured_secondary",
                "rank_status": "not_checked",
                "own_organic_rank": None,
                "own_ad_rank": None,
                "source": "config/targets.yaml",
                "freshness": None,
                "confidence": "configured",
                "missing_fields": ["pangolin_public_context"],
            }
            for idx, keyword in enumerate(core_keywords)
        ]


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
    targets = load_targets()
    api_values = lingxing_api_secret_values(targets)
    server_url = secrets_get("LINGXING_MCP_URL")
    asin = secrets_get("ASIN", targets.get("asin", lingxing_client.DEFAULT_ASIN))
    transport = secrets_get("LINGXING_MCP_TRANSPORT", "auto")
    api_failure = ""

    if has_lingxing_api_config(api_values):
        try:
            config = lingxing_api_client.LingxingAPIConfig.from_mapping(api_values)
            client = lingxing_api_client.LingxingAPIClient(config)
            return client.fetch_dashboard(
                start_date=start_date,
                end_date=end_date,
                sp_campaign_ids=sp_campaign_ids,
                known_non_sp_campaign_ids=known_non_sp_campaign_ids,
            )
        except lingxing_api_client.LingxingAPIConfigError as exc:
            api_failure = f"Lingxing REST API config incomplete: {exc}"
        except Exception as exc:
            api_failure = f"Lingxing REST API pull failed: {type(exc).__name__}: {exc}"

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
            if api_failure:
                dashboard.setdefault("source_status", {}).setdefault("warnings", []).append(
                    api_failure + " Falling back to MCP."
                )
            return dashboard
        except Exception as exc:
            fallback_reason = (
                f"{api_failure} " if api_failure else ""
            ) + (
                "Lingxing live pull failed. The configured LINGXING_MCP_URL did not complete "
                "an MCP session. "
                f"Configured URL: {server_url}. Configured transport: {transport}. "
                f"Error: {type(exc).__name__}: {exc}"
            )
            blocked = lingxing_client.build_blocked_dashboard(
                asin=str(asin),
                mode="live_blocked",
                reason=fallback_reason,
            )
            blocked["date_window"] = {"start_date": start_date, "end_date": end_date}
            return blocked
    if api_failure:
        blocked = lingxing_client.build_blocked_dashboard(
            asin=str(asin),
            mode="api_blocked",
            reason=api_failure,
        )
        blocked["date_window"] = {"start_date": start_date, "end_date": end_date}
        return blocked

    dashboard = lingxing_client.load_fixture_dashboard(
        sp_campaign_ids=sp_campaign_ids,
        known_non_sp_campaign_ids=known_non_sp_campaign_ids,
    )
    dashboard["date_window"] = {"start_date": start_date, "end_date": end_date}
    dashboard["source_status"]["mode"] = "fixture_no_live_url"
    dashboard["source_status"]["warnings"].append("Lingxing REST API secrets and LINGXING_MCP_URL are not configured.")
    return dashboard


@st.cache_data(ttl=1800, show_spinner=False)
def load_market_context(
    force_refresh_key: int,
    data: Dict[str, Any],
    targets: Mapping[str, Any],
) -> Dict[str, Any]:
    del force_refresh_key
    try:
        return enrich_public_context(copy.deepcopy(data), targets)
    except Exception as exc:
        fallback = copy.deepcopy(data)
        context = fallback.setdefault("context", {})
        warnings = fallback.setdefault("source_status", {}).setdefault("warnings", [])
        core_keywords = [str(item) for item in targets.get("core_keywords", []) or [] if str(item).strip()]
        if not core_keywords:
            listing = context.get("listing") if isinstance(context.get("listing"), Mapping) else {}
            core_keywords = _keywords_from_title(str(listing.get("title") or ""), limit=target_int(targets, "pangolin_max_keywords", 3))
        _set_public_context_status(context, "failed", f"{type(exc).__name__}: {exc}", core_keywords)
        warnings.append(f"Market context failed: {type(exc).__name__}: {exc}")
        return fallback


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.35rem; max-width: 1320px; }
        h1 { letter-spacing: 0; font-size: 2.25rem !important; margin-bottom: 0.25rem !important; }
        h2, h3 { letter-spacing: 0; }
        div[data-testid="stMetric"] {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 12px 14px;
            background: #ffffff;
            min-height: 104px;
        }
        div[data-testid="stMetricLabel"] p { color: #4b5563; font-size: 0.88rem; }
        div[data-testid="stMetricValue"] { color: #111827; }
        .status-strip {
            border: 1px solid #d1d5db;
            border-radius: 8px;
            padding: 10px 12px;
            background: #fbfcfd;
            color: #1f2937;
            margin: 0.8rem 0 1rem 0;
            font-size: 0.92rem;
        }
        .health-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin: 0.75rem 0 1rem 0;
        }
        .health-item {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 10px 12px;
            background: #ffffff;
        }
        .health-label {
            color: #6b7280;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0;
            margin-bottom: 2px;
        }
        .health-value {
            color: #111827;
            font-size: 0.94rem;
            font-weight: 650;
            line-height: 1.3;
        }
        .section-note { color: #6b7280; font-size: 0.9rem; }
        .kv-list {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            background: #ffffff;
            overflow: hidden;
        }
        .kv-row {
            display: grid;
            grid-template-columns: minmax(120px, 42%) minmax(0, 58%);
            gap: 12px;
            padding: 8px 10px;
            border-bottom: 1px solid #f3f4f6;
            align-items: start;
        }
        .kv-row:last-child { border-bottom: 0; }
        .kv-key { color: #6b7280; font-size: 0.84rem; line-height: 1.35; }
        .kv-value {
            color: #111827;
            font-size: 0.9rem;
            font-weight: 560;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }
        .badge {
            display: inline-block;
            border-radius: 999px;
            padding: 2px 8px;
            background: #ecfdf5;
            color: #047857;
            font-size: 0.78rem;
            margin-left: 6px;
        }
        @media (max-width: 900px) {
            .health-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 560px) {
            .health-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(targets: Mapping[str, Any]) -> DateWindow:
    timezone_name = str(targets.get("report_timezone") or "Asia/Shanghai")
    anchor = today_for_timezone(timezone_name)
    st.title("Amazon Selling Monitor")
    st.caption(
        f"ASIN: {targets.get('asin', lingxing_client.DEFAULT_ASIN)} | "
        f"Marketplace: {targets.get('marketplace', 'US')} | App: {app_version()}"
    )

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


def dashboard_with_stale_fallback(data: Dict[str, Any]) -> Dict[str, Any]:
    status = data.get("source_status", {})
    if status.get("blocked") and st.session_state.get("last_successful_dashboard"):
        stale = copy.deepcopy(st.session_state.last_successful_dashboard)
        stale_status = stale.setdefault("source_status", {})
        stale_status["stale"] = True
        stale_status["current_refresh_blocked"] = True
        stale_status.setdefault("warnings", []).insert(
            0,
            "Current refresh failed; showing the last successful dashboard snapshot.",
        )
        stale_status.setdefault("warnings", []).extend(status.get("warnings") or [])
        return stale
    if not status.get("blocked") and not str(status.get("mode", "")).startswith("fixture"):
        st.session_state.last_successful_dashboard = copy.deepcopy(data)
    return data


def source_health_label(status: Mapping[str, Any]) -> str:
    mode = str(status.get("mode") or "")
    missing = status.get("missing_fields") or []
    warnings = status.get("warnings") or []
    if status.get("stale"):
        return "Stale fallback"
    if status.get("blocked"):
        return "Blocked"
    if mode.startswith("fixture"):
        return "Sample data"
    if warnings:
        return "Degraded"
    if missing:
        return "Partial"
    if mode == "live_mcp":
        return "MCP fallback"
    return "Healthy"


def render_source_status(data: Dict[str, Any], window: DateWindow) -> None:
    status = data["source_status"]
    mode = status["mode"]
    partial_badge = '<span class="badge">partial day</span>' if window.is_partial else ""
    parent_asin = data.get("parent_asin") or "Not configured"
    selected_child = data.get("selected_child_asin") or data.get("asin")
    if mode == "live_api":
        source = "Lingxing REST API"
    elif mode == "live_mcp":
        source = "Lingxing MCP fallback"
    elif status.get("blocked"):
        source = "Blocked"
    elif mode.startswith("fixture"):
        source = "Sample fixture"
    else:
        source = mode
    health = source_health_label(status)
    st.markdown(
        f"""
        <div class="health-grid">
            <div class="health-item"><div class="health-label">Source Health</div><div class="health-value">{health}</div></div>
            <div class="health-item"><div class="health-label">Date Window</div><div class="health-value">{window.start_date} to {window.end_date}</div></div>
            <div class="health-item"><div class="health-label">Parent ASIN</div><div class="health-value">{parent_asin}</div></div>
            <div class="health-item"><div class="health-label">Selected Child</div><div class="health-value">{selected_child}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if mode in {"live_api", "live_mcp"} and not status.get("stale"):
        body = f"Source: {source}. Pulled at: {data['pulled_at']} {partial_badge}"
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
    family = data.get("sales_family") if isinstance(data.get("sales_family"), Mapping) else {}

    cols = st.columns(3)
    with cols[0]:
        st.subheader("Parent Listing")
        render_key_values(
            {
                "Parent ASIN": safe_text(data.get("parent_asin")),
                "Selected Child": safe_text(data.get("selected_child_asin") or data.get("asin")),
                "Child Count": number(family.get("child_count") or len(data.get("variations") or [])),
                "Active Children": number(family.get("active_child_count")),
                "Window Units": number(data["sales"].get("total_units")),
            }
        )

    with cols[1]:
        st.subheader("SP Goal Pace")
        st.progress(min(float(sp_goal["orders_progress_max"] or 0), 1.0), text=f"Order target pace for {window.label}")
        render_key_values(
            {
                "Order Status": sp_goal["orders_status"],
                "Budget Usage": percent(sp_goal["budget_used_pct"]),
                "ACOS Gap": percent(sp_goal["acos_delta"]),
                "All-Ads TACOS": percent(all_ads["tacos"]),
            }
        )

    with cols[2]:
        st.subheader("Inventory & Listing")
        render_key_values(
            {
                "FBA Fulfillable": number(inventory.get("fba_fulfillable")),
                "Days of Supply": number(inventory.get("days_of_supply")),
                "Stockout Risk": safe_text(inventory.get("stockout_risk")),
                "Price": safe_text(listing.get("price_display") or listing.get("price")),
                "Rating": safe_text(listing.get("rating")),
            }
        )


def render_variations(data: Dict[str, Any], currency: str) -> None:
    rows = []
    for row in data.get("variations") or []:
        rows.append(
            {
                "Image": row.get("image_url"),
                "Child ASIN": row.get("asin"),
                "Title": row.get("title"),
                "SKU": row.get("seller_sku"),
                "Units": row.get("units"),
                "Sales": row.get("sales"),
                "Orders": row.get("orders"),
                "Ad Spend": row.get("ad_spend"),
                "Inventory": row.get("inventory"),
                "Status": row.get("status"),
            }
        )
    if not rows:
        st.info("No child ASIN details were returned for this window.")
        return

    family = data.get("sales_family") if isinstance(data.get("sales_family"), Mapping) else {}
    cols = st.columns(4)
    cols[0].metric("Parent ASIN", safe_text(data.get("parent_asin")))
    cols[1].metric("Children", number(family.get("child_count") or len(rows)))
    cols[2].metric("Active Children", number(family.get("active_child_count")))
    cols[3].metric("Family Sales", money(family.get("sales") or data["sales"].get("total_sales"), currency))

    column_config = {}
    try:
        column_config = {
            "Image": st.column_config.ImageColumn("Image", width="small"),
            "Sales": st.column_config.NumberColumn("Sales", format="$%.2f"),
            "Ad Spend": st.column_config.NumberColumn("Ad Spend", format="$%.2f"),
        }
    except Exception:
        column_config = {}
    st.dataframe(rows, use_container_width=True, hide_index=True, column_config=column_config)


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


def render_market_context_tab(
    data: Dict[str, Any],
    summary: Dict[str, Any],
    currency: str,
    targets: Mapping[str, Any],
) -> None:
    if "market_context_counter" not in st.session_state:
        st.session_state.market_context_counter = 0
    cols = st.columns([1, 3])
    if cols[0].button("Refresh Market Context", use_container_width=True):
        st.session_state.market_context_counter += 1
        load_market_context.clear()
        st.session_state.market_context_loaded = True
    should_load = bool(st.session_state.get("market_context_loaded"))
    if should_load:
        with st.spinner("Pulling market context..."):
            context_data = load_market_context(
                st.session_state.market_context_counter,
                data,
                dict(targets),
            )
        render_context(context_data, summary, currency)
        return

    cols[1].info("Market context is skipped on initial load. Refresh it here when you need Pangolin listing, rank, or competitor context.")
    preview = copy.deepcopy(data)
    preview.setdefault("context", {}).setdefault(
        "public_context_status",
        {
            "status": "skipped",
            "message": "Market context has not been refreshed in this session.",
            "source": "pangolin",
            "freshness": None,
        },
    )
    render_context(preview, summary, currency)


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
    rank = context.get("rank", {})
    core_keywords = context.get("core_keywords", [])
    sales = data.get("sales", {})
    all_ads = summary["advertising"]["all_ads"]
    sp = summary["advertising"]["sp"]

    public_status = context.get("public_context_status") if isinstance(context.get("public_context_status"), Mapping) else {}
    public_status_name = public_status.get("status")
    public_status_message = public_status.get("message")
    if public_status_name == "partial" and public_status_message:
        st.warning(public_status_message)
    elif public_status_name in {"failed", "missing_token"} and public_status_message:
        st.error(public_status_message)

    st.subheader("Context Quality")
    render_key_values(
            {
                "Source": data["source_status"].get("mode"),
                "Pulled At": data.get("pulled_at"),
                "Public Context": context.get("public_context_status", {}).get("status") or "unknown",
                "Public Context Note": context.get("public_context_status", {}).get("message") or "None",
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
        render_key_values(
            {
                "Title": safe_text(listing.get("title")),
                "Price": safe_text(listing.get("price_display") or listing.get("price")),
                "List Price": offer_value(listing.get("list_price_display")),
                "Coupon": offer_value(listing.get("coupon_present")),
                "Discount / Price Reduction": offer_value(listing.get("discount_present")),
                "Amazon Deal": offer_value(listing.get("deal_present")),
                "Rating": safe_text(listing.get("rating")),
                "Reviews": number(listing.get("review_count")),
                "Fulfillment": safe_text(listing.get("fulfillment_method")),
                "Delivery Promise": offer_value(listing.get("delivery_promise")),
                "Source": offer_value(listing.get("source")),
                "Freshness": offer_value(listing.get("freshness")),
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

    st.subheader("Own Ranking")
    render_key_values(own_ranking_values(rank))

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
                "BSR Capture Status": safe_text(rank.get("bsr_capture_status")),
                "BSR Result Count": safe_text(rank.get("bsr_result_count")),
                "Competitor Source": safe_text(market.get("selected_competitors_source") or market.get("source")),
                "Freshness": safe_text(market.get("freshness")),
                "Confidence": safe_text(market.get("confidence")),
            }
        )
    else:
        note = context.get("public_context_status", {}).get("message")
        st.caption(note or "No selected competitor context is available. Connect Pangolin public context or configure core keywords.")


def render_key_values(values: Mapping[str, Any]) -> None:
    rows = []
    for key, value in values.items():
        rows.append(
            '<div class="kv-row">'
            f'<div class="kv-key">{html.escape(str(key))}</div>'
            f'<div class="kv-value">{html.escape(safe_text(value))}</div>'
            "</div>"
        )
    st.markdown('<div class="kv-list">' + "".join(rows) + "</div>", unsafe_allow_html=True)


def own_ranking_values(rank: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "BSR Major Category Rank": safe_text(rank.get("own_bsr_major_rank")),
        "BSR Major Category": safe_text(rank.get("own_bsr_major_category")),
        "BSR Leaf Category Rank": safe_text(rank.get("own_bsr_leaf_rank")),
        "BSR Leaf Category": safe_text(rank.get("own_bsr_leaf_category")),
        "New Release Major Category Rank": safe_text(rank.get("own_new_release_major_rank")),
        "New Release Major Category": safe_text(rank.get("own_new_release_major_category")),
        "New Release Leaf Category Rank": safe_text(rank.get("own_new_release_leaf_rank")),
        "New Release Leaf Category": safe_text(rank.get("own_new_release_leaf_category")),
        "BSR Capture Status": safe_text(rank.get("bsr_capture_status")),
    }


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
                "Best BSR Rank": rank.get("best_bsr_rank"),
                "Best Category/List Rank": rank.get("best_category_list_rank"),
                "Category Source": rank.get("category_rank_source"),
                "Matched Keywords": ", ".join(str(item) for item in row.get("keywords", []) or []),
                "Why Selected": ", ".join(str(item) for item in row.get("why_selected", []) or []),
            }
        )
    return out


def _first_matching_warning(warnings: Iterable[Any], fragments: Iterable[str]) -> str:
    lowered = [fragment.lower() for fragment in fragments]
    for warning in warnings:
        text = str(warning)
        compact = text.lower()
        if any(fragment in compact for fragment in lowered):
            return text
    return ""


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
    with st.spinner("Refreshing sales, ads, listing, and variation data..."):
        data = load_dashboard_data(
            st.session_state.refresh_counter,
            window.start_date,
            window.end_date,
            tuple(str(item) for item in targets.get("sp_campaign_ids", []) or []),
            tuple(str(item) for item in targets.get("known_non_sp_campaign_ids", []) or []),
        )
    data = dashboard_with_stale_fallback(data)

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

    tabs = st.tabs(["Overview", "Variations", "SP Performance", "All Ads", "Market Context", "Diagnostics"])
    with tabs[0]:
        render_overview(data, summary, currency, window)
    with tabs[1]:
        render_variations(data, currency)
    with tabs[2]:
        render_sp_ads(data, summary, currency)
    with tabs[3]:
        render_all_ads(data, summary, currency)
    with tabs[4]:
        render_market_context_tab(data, summary, currency, targets)
    with tabs[5]:
        render_details(data)


if __name__ == "__main__":
    main()
