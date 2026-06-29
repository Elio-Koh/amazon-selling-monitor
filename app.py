"""Streamlit dashboard for Amazon selling monitor."""

from __future__ import annotations

import copy
import concurrent.futures
import html
import importlib
import inspect
import json
import os
import re
import time
import urllib.parse
from datetime import date
from typing import Any, Dict, Iterable, Mapping, Optional

import streamlit as st

from src import lingxing_api_client
from src import lingxing_client
from src import metrics
from src import public_context
from src import supply_inputs
from src.config import load_targets
from src.date_windows import PRESETS, DateWindow, resolve_date_window, today_for_timezone
from src.market_context_snapshot import apply_snapshot_to_dashboard, load_encrypted_snapshot_from_url
from src.pangolin_client import PangolinClient, PangolinError


MARKET_CONTEXT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-context")


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


def market_context_now() -> float:
    return time.monotonic()


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
        "LINGXING_API_TIMEOUT_SECONDS": secrets_get(
            "LINGXING_API_TIMEOUT_SECONDS",
            lingxing_api_client.DEFAULT_TIMEOUT,
        ),
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


def build_public_context_with_reload(**kwargs: Any) -> Dict[str, Any]:
    try:
        return public_context.build_public_context(**kwargs)
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        importlib.invalidate_caches()
        refreshed = importlib.reload(public_context)
        return refreshed.build_public_context(**kwargs)


def enrich_public_context(data: Dict[str, Any], targets: Mapping[str, Any]) -> Dict[str, Any]:
    token = secrets_get("PANGOLINFO_API_TOKEN") or secrets_get("PANGOLIN_API_TOKEN")
    return enrich_public_context_with_token(data, targets, str(token) if token else None)


def enrich_public_context_with_token(
    data: Dict[str, Any],
    targets: Mapping[str, Any],
    token: Optional[str],
) -> Dict[str, Any]:
    enabled = bool(targets.get("pangolin_enabled", True))
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
        public = build_public_context_with_reload(
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
            leaf_category_label=safe_text(targets.get("pangolin_leaf_category_label"), ""),
            leaf_category_node_id=safe_text(targets.get("pangolin_leaf_category_node_id"), ""),
            best_sellers_url=safe_text(targets.get("pangolin_best_sellers_url"), ""),
            new_releases_url=safe_text(targets.get("pangolin_new_releases_url"), ""),
            direct_url_fallback_enabled=bool(targets.get("amazon_direct_rank_fallback_enabled", True)),
            direct_url_timeout=target_int(targets, "amazon_direct_rank_timeout_seconds", 8),
            direct_url_max_pages=target_int(targets, "amazon_direct_rank_max_pages", 2),
            client=PangolinClient(api_token=str(token), timeout=target_int(targets, "pangolin_request_timeout_seconds", 8)),
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


@st.cache_data(ttl=300, show_spinner=False)
def load_google_sheet_operations_cached(
    force_refresh_key: int,
    sheet_source: str,
    asin: str,
    fba_fulfillable: Optional[float],
    anchor_date_iso: str,
) -> Dict[str, Any]:
    del force_refresh_key
    return supply_inputs.load_google_sheet_operations(
        sheet_source,
        anchor_date=date.fromisoformat(anchor_date_iso),
        asin=asin,
        dashboard_inventory={"fba_fulfillable": fba_fulfillable},
    )


def attach_operations_context(data: Dict[str, Any], operations: Mapping[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    result.setdefault("context", {})["operations"] = copy.deepcopy(dict(operations))
    return result


def render_supply_input_controls(targets: Mapping[str, Any]) -> Dict[str, Any]:
    secret_source = (
        secrets_get("SUPPLY_PLAN_GOOGLE_SHEET_ID")
        or secrets_get("SUPPLY_PLAN_GOOGLE_SHEET_URL")
        or targets.get("supply_plan_google_sheet_id")
        or targets.get("supply_plan_google_sheet_url")
    )
    controls: Dict[str, Any] = {"sheet_source": str(secret_source or "").strip(), "uploads": {}}
    with st.expander("Supply Inputs", expanded=False):
        if secret_source:
            st.caption("Supply Google Sheet is configured at runtime. The sheet ID is not stored in this repository.")
        manual_source = st.text_input(
            "Google Sheet ID or URL override",
            value="",
            placeholder="Paste a Google Sheet ID or URL for sales plan, procurement, FBA shipments, and logistics cycle.",
        )
        if manual_source.strip():
            controls["sheet_source"] = manual_source.strip()
        st.caption("Optional CSV uploads override the matching Google Sheet tab for this browser session.")
        upload_cols = st.columns(5)
        controls["uploads"] = {
            "sales_plan": upload_cols[0].file_uploader("销售计划 CSV", type=["csv"], key="supply_sales_plan_csv"),
            "procurement": upload_cols[1].file_uploader("采购/备货 CSV", type=["csv"], key="supply_procurement_csv"),
            "fba_shipments": upload_cols[2].file_uploader("FBA 发货 CSV", type=["csv"], key="supply_fba_shipments_csv"),
            "logistics_cycle": upload_cols[3].file_uploader("物流周期 CSV", type=["csv"], key="supply_logistics_cycle_csv"),
            "inventory": upload_cols[4].file_uploader("库存 CSV", type=["csv"], key="supply_inventory_csv"),
        }
    return controls


def load_supply_operations(
    controls: Mapping[str, Any],
    data: Mapping[str, Any],
    targets: Mapping[str, Any],
    *,
    anchor_date: date,
) -> Dict[str, Any]:
    context = data.get("context") if isinstance(data.get("context"), Mapping) else {}
    dashboard_inventory = context.get("inventory") if isinstance(context.get("inventory"), Mapping) else {}
    asin = str(data.get("selected_child_asin") or data.get("asin") or targets.get("asin") or lingxing_client.DEFAULT_ASIN)
    sheet_source = str(controls.get("sheet_source") or "").strip()
    uploads = controls.get("uploads") if isinstance(controls.get("uploads"), Mapping) else {}
    warnings = []
    source = "not_configured"

    sales_plan: Mapping[str, Any] = {}
    procurement: Mapping[str, Any] = {}
    fba_shipments: Mapping[str, Any] = {}
    logistics_cycle: Mapping[str, Any] = {}
    inventory_override: Mapping[str, Any] = {}

    if sheet_source:
        try:
            operations = load_google_sheet_operations_cached(
                int(st.session_state.get("refresh_counter", 0)),
                sheet_source,
                asin,
                _safe_float(dashboard_inventory.get("fba_fulfillable")) if dashboard_inventory.get("fba_fulfillable") is not None else None,
                anchor_date.isoformat(),
            )
            sales_plan = operations.get("sales_plan") if isinstance(operations.get("sales_plan"), Mapping) else {}
            procurement = operations.get("procurement") if isinstance(operations.get("procurement"), Mapping) else {}
            fba_shipments = operations.get("fba_shipments") if isinstance(operations.get("fba_shipments"), Mapping) else {}
            logistics_cycle = operations.get("logistics_cycle") if isinstance(operations.get("logistics_cycle"), Mapping) else {}
            source = "google_sheet"
            warnings.extend(operations.get("source_status", {}).get("warnings") or [])
        except Exception as exc:
            source = "supply_input_error"
            warnings.append(f"Supply Google Sheet pull failed: {type(exc).__name__}: {exc}")

    upload_texts = {key: _uploaded_csv_text(value) for key, value in uploads.items()}
    uploaded_any = any(upload_texts.values())
    if upload_texts.get("sales_plan"):
        sales_plan = supply_inputs.parse_sales_plan_csv(upload_texts["sales_plan"], anchor_date=anchor_date)
    if upload_texts.get("procurement"):
        procurement = supply_inputs.parse_procurement_csv(upload_texts["procurement"], reference_year=anchor_date.year)
    if upload_texts.get("fba_shipments"):
        fba_shipments = supply_inputs.parse_fba_shipments_csv(upload_texts["fba_shipments"], asin=asin, reference_year=anchor_date.year)
    if upload_texts.get("logistics_cycle"):
        logistics_cycle = supply_inputs.parse_logistics_cycle_csv(upload_texts["logistics_cycle"])
    if upload_texts.get("inventory"):
        inventory_override = supply_inputs.parse_inventory_csv(upload_texts["inventory"], asin=asin)
    if uploaded_any:
        source = "manual_upload" if source == "not_configured" else f"{source}_with_upload_overrides"
    if source == "not_configured":
        warnings.append("Supply inputs are not configured. Add a runtime Google Sheet source or upload CSV files.")

    return supply_inputs.build_operations_snapshot(
        sales_plan=sales_plan,
        procurement=procurement,
        fba_shipments=fba_shipments,
        logistics_cycle=logistics_cycle,
        inventory=inventory_override,
        dashboard_inventory=dashboard_inventory,
        anchor_date=anchor_date,
        source=source,
        warnings=warnings,
    )


def _uploaded_csv_text(uploaded: Any) -> str:
    if uploaded in (None, ""):
        return ""
    try:
        raw = uploaded.getvalue()
    except AttributeError:
        try:
            raw = uploaded.read()
        except AttributeError:
            raw = uploaded
    if isinstance(raw, bytes):
        return raw.decode("utf-8-sig")
    return str(raw or "")


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


def market_context_request_key(data: Mapping[str, Any], targets: Mapping[str, Any], refresh_counter: int) -> str:
    payload = {
        "refresh_counter": refresh_counter,
        "asin": data.get("asin") or targets.get("asin"),
        "pulled_at": data.get("pulled_at"),
        "date_window": data.get("date_window"),
        "pangolin": {
            "zipcode": targets.get("pangolin_zipcode"),
            "max_keywords": targets.get("pangolin_max_keywords"),
            "leaf_label": targets.get("pangolin_leaf_category_label"),
            "leaf_node_id": targets.get("pangolin_leaf_category_node_id"),
            "best_sellers_url": targets.get("pangolin_best_sellers_url"),
            "new_releases_url": targets.get("pangolin_new_releases_url"),
            "core_keywords": targets.get("core_keywords"),
        },
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _market_context_preview(data: Dict[str, Any], status: str, message: str, targets: Mapping[str, Any]) -> Dict[str, Any]:
    preview = copy.deepcopy(data)
    context = preview.setdefault("context", {})
    core_keywords = [str(item) for item in targets.get("core_keywords", []) or [] if str(item).strip()]
    if not core_keywords:
        listing = context.get("listing") if isinstance(context.get("listing"), Mapping) else {}
        core_keywords = _keywords_from_title(str(listing.get("title") or ""), limit=target_int(targets, "pangolin_max_keywords", 3))
    _set_public_context_status(context, status, message, core_keywords)
    return preview


def _submit_market_context_job(data: Dict[str, Any], targets: Mapping[str, Any], token: str) -> concurrent.futures.Future:
    return MARKET_CONTEXT_EXECUTOR.submit(
        enrich_public_context_with_token,
        copy.deepcopy(data),
        dict(targets),
        token,
    )


@st.cache_data(ttl=120, show_spinner=False)
def load_remote_market_context_snapshot(url: str, encryption_key: str, timeout: int = 5) -> Dict[str, Any]:
    return load_encrypted_snapshot_from_url(url, key=encryption_key, timeout=timeout)


def clear_remote_market_context_snapshot_cache() -> None:
    clear = getattr(load_remote_market_context_snapshot, "clear", None)
    if callable(clear):
        clear()


def market_context_snapshot_effective_url(
    url: str,
    targets: Mapping[str, Any],
    *,
    force_refresh: bool,
) -> str:
    bucket_seconds = max(target_int(targets, "market_context_snapshot_cache_bust_seconds", 60), 1)
    params = {"_snapshot_bucket": str(int(time.time() // bucket_seconds))}
    if force_refresh:
        params["_snapshot_nonce"] = str(int(time.time() * 1000))
    parsed = urllib.parse.urlparse(str(url))
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key not in params]
    query.extend(params.items())
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def market_context_banner_level(status: Optional[str]) -> Optional[str]:
    if status in {"ok", "fresh"}:
        return "success"
    if status in {"partial", "stale"}:
        return "warning"
    if status in {"failed", "missing_token", "expired"}:
        return "error"
    if status == "loading":
        return "info"
    return None


def market_context_from_snapshot(
    data: Dict[str, Any],
    targets: Mapping[str, Any],
    *,
    force_refresh: bool,
) -> Optional[Dict[str, Any]]:
    url = (
        secrets_get("MARKET_CONTEXT_SNAPSHOT_URL")
        or targets.get("market_context_snapshot_url")
    )
    if not url:
        return None
    base_url = str(url)
    if force_refresh:
        clear_remote_market_context_snapshot_cache()
        st.session_state.pop("market_context_snapshot_hot_cache", None)
    encryption_key = str(secrets_get("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY") or "")
    if not encryption_key:
        result = _market_context_preview(
            data,
            "missing_token",
            "MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY is not configured.",
            targets,
        )
        result.setdefault("source_status", {}).setdefault("warnings", []).append(
            "Market context snapshot skipped: MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY is not configured."
        )
        return result
    timeout = target_int(targets, "market_context_snapshot_timeout_seconds", 5)
    stale_minutes = target_int(targets, "market_context_snapshot_stale_minutes", 10)
    expired_minutes = target_int(targets, "market_context_snapshot_expired_minutes", 120)
    effective_url = market_context_snapshot_effective_url(base_url, targets, force_refresh=force_refresh)
    try:
        snapshot = load_remote_market_context_snapshot(effective_url, encryption_key, timeout)
        result = apply_snapshot_to_dashboard(
            data,
            snapshot,
            stale_minutes=stale_minutes,
            expired_minutes=expired_minutes,
        )
        st.session_state["market_context_snapshot_hot_cache"] = {
            "url": base_url,
            "data": copy.deepcopy(result),
        }
        return result
    except Exception as exc:
        hot = st.session_state.get("market_context_snapshot_hot_cache")
        if isinstance(hot, Mapping) and hot.get("url") == base_url:
            result = copy.deepcopy(hot["data"])
            status = result.setdefault("context", {}).setdefault("public_context_status", {})
            status["status"] = "stale"
            status["message"] = f"Using fallback in-memory market context snapshot; remote snapshot read failed: {type(exc).__name__}: {exc}"
            result.setdefault("source_status", {}).setdefault("warnings", []).append(status["message"])
            return result
        result = _market_context_preview(
            data,
            "failed",
            f"Market context snapshot read failed: {type(exc).__name__}: {exc}",
            targets,
        )
        result.setdefault("source_status", {}).setdefault("warnings", []).append(
            f"Market context snapshot read failed: {type(exc).__name__}: {exc}"
        )
        return result


def market_context_render_data(data: Dict[str, Any], targets: Mapping[str, Any], *, force_refresh: bool) -> Dict[str, Any]:
    snapshot_result = market_context_from_snapshot(data, targets, force_refresh=force_refresh)
    if snapshot_result is not None:
        return snapshot_result

    if "market_context_counter" not in st.session_state:
        st.session_state["market_context_counter"] = 0
    if force_refresh:
        st.session_state["market_context_counter"] = int(st.session_state.get("market_context_counter", 0)) + 1
        st.session_state.pop("market_context_future", None)
        st.session_state.pop("market_context_result", None)

    counter = int(st.session_state.get("market_context_counter", 0))
    key = market_context_request_key(data, targets, counter)
    result_record = st.session_state.get("market_context_result")
    result_preview = isinstance(result_record, Mapping) and bool(result_record.get("preview"))
    if isinstance(result_record, Mapping) and result_record.get("key") == key and not result_preview:
        return result_record["data"]

    future_record = st.session_state.get("market_context_future")
    future = future_record.get("future") if isinstance(future_record, Mapping) and future_record.get("key") == key else None
    if future is None and isinstance(result_record, Mapping) and result_record.get("key") == key and result_preview:
        return result_record["data"]
    if future is None:
        token = secrets_get("PANGOLINFO_API_TOKEN") or secrets_get("PANGOLIN_API_TOKEN")
        if not token:
            result = enrich_public_context_with_token(copy.deepcopy(data), targets, None)
            st.session_state["market_context_result"] = {"key": key, "data": result}
            return result
        future = _submit_market_context_job(data, targets, str(token))
        future_record = {"key": key, "future": future, "started_at": market_context_now()}
        st.session_state["market_context_future"] = future_record

    if future.done():
        try:
            result = future.result()
        except Exception as exc:
            result = _market_context_preview(data, "failed", f"{type(exc).__name__}: {exc}", targets)
            result.setdefault("source_status", {}).setdefault("warnings", []).append(
                f"Market context failed: {type(exc).__name__}: {exc}"
            )
        st.session_state["market_context_result"] = {"key": key, "data": result}
        st.session_state.pop("market_context_future", None)
        return result

    timeout_seconds = target_int(targets, "market_context_background_timeout_seconds", 25)
    started_value = future_record.get("started_at") if isinstance(future_record, Mapping) else None
    started_at = float(started_value) if started_value is not None else market_context_now()
    elapsed = max(market_context_now() - started_at, 0.0)
    if elapsed >= timeout_seconds:
        result = _market_context_preview(
            data,
            "partial",
            f"Market context timed out after {timeout_seconds}s; showing available data. Click Refresh Market Context to retry.",
            targets,
        )
        result.setdefault("source_status", {}).setdefault("warnings", []).append(
            f"Market context background fetch exceeded {timeout_seconds}s."
        )
        st.session_state["market_context_result"] = {"key": key, "data": result, "preview": True}
        return result

    return _market_context_preview(
        data,
        "loading",
        f"Market context is loading in background ({int(elapsed)}s). Core sales and ads data are already available.",
        targets,
    )


def _streamlit_fragment(run_every: str):
    fragment = getattr(st, "__dict__", {}).get("fragment") or getattr(st, "__dict__", {}).get("experimental_fragment")
    if callable(fragment):
        return fragment(run_every=run_every)

    def decorator(func):
        return func

    return decorator


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
        supply_clear = getattr(load_google_sheet_operations_cached, "clear", None)
        if callable(supply_clear):
            supply_clear()

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
    if (
        not status.get("blocked")
        and not str(status.get("mode", "")).startswith("fixture")
        and not status.get("warnings")
        and not status.get("missing_fields")
    ):
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


def risk_label(level: Any) -> str:
    return {
        "critical": "Critical",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "unknown": "Unknown",
    }.get(str(level or "unknown"), str(level or "Unknown"))


def render_stockout_risk_summary(operations: Mapping[str, Any]) -> None:
    risk = operations.get("stockout_risk") if isinstance(operations.get("stockout_risk"), Mapping) else {}
    inventory = operations.get("inventory") if isinstance(operations.get("inventory"), Mapping) else {}
    sales_plan = operations.get("sales_plan") if isinstance(operations.get("sales_plan"), Mapping) else {}
    level = str(risk.get("level") or "unknown")
    message = safe_text(risk.get("reason"), "Supply inputs are not configured.")
    if level == "critical":
        st.error(f"Stockout risk: {risk_label(level)}. {message}")
    elif level in {"high", "medium"}:
        st.warning(f"Stockout risk: {risk_label(level)}. {message}")
    elif level == "low":
        st.success(f"Stockout risk: {risk_label(level)}. {message}")
    else:
        st.info(f"Stockout risk: {risk_label(level)}. {message}")

    cols = st.columns(4)
    coverage = risk.get("coverage_days")
    cols[0].metric("Stockout Risk", risk_label(level))
    cols[1].metric("Coverage Days", "-" if coverage is None else f"{float(coverage):.1f}")
    cols[2].metric("Projected Stockout", safe_text(risk.get("projected_stockout_date")))
    cols[3].metric(
        "Planned Daily Units",
        "-" if sales_plan.get("planned_daily_units") is None else f"{float(sales_plan['planned_daily_units']):.1f}",
        f"Inventory {number(inventory.get('fba_fulfillable'))}",
    )


def render_overview(data: Dict[str, Any], summary: Dict[str, Any], currency: str, window: DateWindow) -> None:
    render_metric_row(summary, currency)
    operations = data.get("context", {}).get("operations", {})
    if isinstance(operations, Mapping):
        render_stockout_risk_summary(operations)
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


def render_operations(data: Dict[str, Any]) -> None:
    operations = data.get("context", {}).get("operations", {})
    if not isinstance(operations, Mapping) or not operations:
        st.info("Supply inputs are not available for this dashboard snapshot.")
        return

    status = operations.get("source_status") if isinstance(operations.get("source_status"), Mapping) else {}
    risk = operations.get("stockout_risk") if isinstance(operations.get("stockout_risk"), Mapping) else {}
    inventory = operations.get("inventory") if isinstance(operations.get("inventory"), Mapping) else {}
    sales_plan = operations.get("sales_plan") if isinstance(operations.get("sales_plan"), Mapping) else {}
    procurement = operations.get("procurement") if isinstance(operations.get("procurement"), Mapping) else {}
    shipments = operations.get("fba_shipments") if isinstance(operations.get("fba_shipments"), Mapping) else {}
    logistics_cycle = operations.get("logistics_cycle") if isinstance(operations.get("logistics_cycle"), Mapping) else {}

    st.subheader("Stockout Risk")
    render_key_values(
        {
            "Risk Level": risk_label(risk.get("level")),
            "Coverage Days": risk.get("coverage_days"),
            "Projected Stockout": safe_text(risk.get("projected_stockout_date")),
            "FBA Fulfillable": number(inventory.get("fba_fulfillable")),
            "Inventory Source": safe_text(inventory.get("source")),
            "Reason": safe_text(risk.get("reason")),
            "Data Gaps": ", ".join(str(item) for item in risk.get("data_gaps", []) or []) or "None",
        }
    )

    cols = st.columns(3)
    with cols[0]:
        st.subheader("Sales Plan")
        render_key_values(
            {
                "Updated At": safe_text(sales_plan.get("updated_at")),
                "Current Month Target": number(sales_plan.get("current_month_target_units")),
                "Planned Daily Units": safe_text(sales_plan.get("planned_daily_units")),
            }
        )
        st.dataframe(_sales_plan_table(sales_plan), use_container_width=True, hide_index=True)

    with cols[1]:
        st.subheader("Procurement")
        render_key_values(
            {
                "Lead Time Days": number(procurement.get("lead_time_days")),
                "Unit Cost USD": money(procurement.get("unit_cost_usd"), "$"),
                "Purchase Total Units": number(procurement.get("purchase_total_units")),
                "Shipped Total Units": number(procurement.get("shipped_total_units")),
                "Unshipped Units": number(procurement.get("unshipped_units")),
            }
        )

    with cols[2]:
        st.subheader("FBA Shipments")
        render_key_values(
            {
                "Total Units": number(shipments.get("total_units")),
                "Delivered Units": number(shipments.get("delivered_units")),
                "Open Units": number(shipments.get("open_units")),
                "Rows": number(len(shipments.get("rows", []) or [])),
            }
        )

    st.subheader("Procurement Rows")
    st.dataframe(_procurement_table(procurement.get("rows", []) or []), use_container_width=True, hide_index=True)
    st.subheader("FBA Shipment Rows")
    st.dataframe(_shipment_table(shipments.get("rows", []) or []), use_container_width=True, hide_index=True)
    st.subheader("Logistics Cycle")
    st.dataframe(_logistics_cycle_table(logistics_cycle.get("rows", []) or []), use_container_width=True, hide_index=True)

    warnings = status.get("warnings") or []
    if warnings:
        with st.expander("Supply source notes", expanded=False):
            for warning in warnings:
                st.write(f"- {warning}")


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


@_streamlit_fragment(run_every="2s")
def render_market_context_tab(
    data: Dict[str, Any],
    summary: Dict[str, Any],
    currency: str,
    targets: Mapping[str, Any],
) -> None:
    cols = st.columns([1, 3])
    force_refresh = cols[0].button("Refresh Market Context", use_container_width=True)
    context_data = market_context_render_data(data, dict(targets), force_refresh=force_refresh)
    public_status = context_data.get("context", {}).get("public_context_status", {})
    status = public_status.get("status") if isinstance(public_status, Mapping) else None
    banner_level = market_context_banner_level(status)
    if banner_level == "info":
        cols[1].info(public_status.get("message") or "Market context is loading in background.")
    elif banner_level == "success":
        cols[1].success("Market context is ready.")
    elif banner_level == "warning":
        cols[1].warning(public_status.get("message") or "Market context loaded with partial data.")
    elif banner_level == "error":
        cols[1].error(public_status.get("message") or "Market context is unavailable.")
    render_context(context_data, summary, currency)


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


def _sales_plan_table(sales_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    monthly_units = sales_plan.get("monthly_units") if isinstance(sales_plan.get("monthly_units"), Mapping) else {}
    return [
        {
            "Month": int(month),
            "Target Units": units,
        }
        for month, units in sorted(monthly_units.items(), key=lambda item: int(item[0]))
    ]


def _procurement_table(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "Purchase Date": row.get("purchase_date"),
                "Planned Units": row.get("planned_units"),
                "Delivery Status": row.get("delivery_status"),
                "Delivery Date": row.get("delivery_date"),
                "Delivery Units": row.get("delivery_units"),
                "Shipment Status": row.get("shipment_status"),
            }
        )
    return out


def _shipment_table(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "Arranged Date": row.get("arranged_date"),
                "SKU": row.get("sku"),
                "ASIN": row.get("asin"),
                "Units": row.get("line_units"),
                "Shipment ID": row.get("shipment_id"),
                "Reference ID": row.get("reference_id"),
                "Ship To": row.get("ship_to"),
                "Carrier": row.get("carrier"),
                "Planned Delivery": row.get("planned_delivery_raw"),
                "Actual Delivery": row.get("actual_delivery_raw"),
                "Status": row.get("status"),
            }
        )
    return out


def _logistics_cycle_table(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                "Method": row.get("method"),
                "Min Days": row.get("min_days"),
                "Max Days": row.get("max_days"),
                "Raw Lead Time": row.get("raw_lead_time"),
            }
        )
    return out


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
    if public_status_name in {"partial", "stale"} and public_status_message:
        st.warning(public_status_message)
    elif public_status_name in {"failed", "missing_token", "expired"} and public_status_message:
        st.error(public_status_message)

    st.subheader("Context Quality")
    render_key_values(
            {
                "Source": data["source_status"].get("mode"),
                "Pulled At": data.get("pulled_at"),
                "Public Context": context.get("public_context_status", {}).get("status") or "unknown",
                "Public Context Note": context.get("public_context_status", {}).get("message") or "None",
                "Snapshot Captured At": public_status.get("captured_at") or "None",
                "Snapshot Age Minutes": public_status.get("snapshot_age_minutes") if public_status.get("snapshot_age_minutes") is not None else "None",
                "Snapshot Source": public_status.get("source") or "None",
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
    values = {
        "BSR Major Category Rank": safe_text(rank.get("own_bsr_major_rank")),
        "BSR Major Category": safe_text(rank.get("own_bsr_major_category")),
        "BSR Leaf Category Rank": safe_text(rank.get("own_bsr_leaf_rank")),
        "BSR Leaf Category": safe_text(rank.get("own_bsr_leaf_category")),
        "BSR Leaf Source": safe_text(rank.get("own_bsr_leaf_source")),
        "New Release Leaf Category Rank": safe_text(rank.get("own_new_release_leaf_rank")),
        "New Release Leaf Category": safe_text(rank.get("own_new_release_leaf_category")),
        "New Release Leaf Source": safe_text(rank.get("own_new_release_leaf_source")),
        "BSR Capture Status": safe_text(rank.get("bsr_capture_status")),
    }
    new_release_major_rank = safe_text(rank.get("own_new_release_major_rank"))
    new_release_major_category = safe_text(rank.get("own_new_release_major_category"))
    if new_release_major_rank != "-" or new_release_major_category != "-":
        values = {
            **dict(list(values.items())[:5]),
            "New Release Major Category Rank": new_release_major_rank,
            "New Release Major Category": new_release_major_category,
            **dict(list(values.items())[5:]),
        }
    return values


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
    supply_controls = render_supply_input_controls(targets)
    with st.spinner("Refreshing sales, ads, listing, and variation data..."):
        data = load_dashboard_data(
            st.session_state.refresh_counter,
            window.start_date,
            window.end_date,
            tuple(str(item) for item in targets.get("sp_campaign_ids", []) or []),
            tuple(str(item) for item in targets.get("known_non_sp_campaign_ids", []) or []),
        )
    data = dashboard_with_stale_fallback(data)
    operations = load_supply_operations(
        supply_controls,
        data,
        targets,
        anchor_date=date.fromisoformat(window.end_date),
    )
    data = attach_operations_context(data, operations)

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

    tabs = st.tabs(["Overview", "Variations", "SP Performance", "All Ads", "Operations", "Market Context", "Diagnostics"])
    with tabs[0]:
        render_overview(data, summary, currency, window)
    with tabs[1]:
        render_variations(data, currency)
    with tabs[2]:
        render_sp_ads(data, summary, currency)
    with tabs[3]:
        render_all_ads(data, summary, currency)
    with tabs[4]:
        render_operations(data)
    with tabs[5]:
        render_market_context_tab(data, summary, currency, targets)
    with tabs[6]:
        render_details(data)


if __name__ == "__main__":
    main()
