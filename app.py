"""Streamlit dashboard for Amazon selling monitor."""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict

import streamlit as st

from src import lingxing_client
from src.config import load_targets
from src.metrics import build_dashboard_summary


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
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    return f"{float(value):,.0f}"


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


@st.cache_data(ttl=60, show_spinner=False)
def load_dashboard_data(force_refresh_key: int) -> Dict[str, Any]:
    del force_refresh_key
    server_url = secrets_get("LINGXING_MCP_URL")
    asin = secrets_get("ASIN", lingxing_client.DEFAULT_ASIN)
    transport = secrets_get("LINGXING_MCP_TRANSPORT", "auto")
    if server_url:
        try:
            return create_lingxing_client(
                server_url=str(server_url),
                asin=str(asin),
                transport=str(transport),
            ).fetch_dashboard()
        except Exception as exc:
            return lingxing_client.build_blocked_dashboard(
                asin=str(asin),
                mode="live_blocked",
                reason=(
                    "Lingxing live pull failed. The configured LINGXING_MCP_URL is reachable "
                    "from settings but did not complete an MCP session. "
                    f"Configured URL: {server_url}. Configured transport: {transport}. "
                    f"Error: {type(exc).__name__}: {exc}"
                ),
            )
    dashboard = lingxing_client.load_fixture_dashboard()
    dashboard["source_status"]["mode"] = "fixture_no_live_url"
    dashboard["source_status"]["warnings"].append("LINGXING_MCP_URL is not configured.")
    return dashboard


def render_source_status(data: Dict[str, Any]) -> None:
    status = data["source_status"]
    mode = status["mode"]
    if mode == "live_mcp":
        st.success(f"数据源：Lingxing 实时拉取。更新时间：{data['pulled_at']}")
    elif status.get("blocked"):
        st.error(f"实时数据源不可用。模式：{mode}。检查时间：{data['pulled_at']}")
    elif mode.startswith("fixture"):
        st.warning(f"当前使用样例数据。模式：{mode}。更新时间：{data['pulled_at']}")
    else:
        st.info(f"数据源模式：{mode}。更新时间：{data['pulled_at']}")

    missing = status.get("missing_fields") or []
    warnings = status.get("warnings") or []
    if missing:
        st.caption("缺失字段：" + "、".join(missing))
    if warnings:
        with st.expander("数据源提示", expanded=False):
            for warning in warnings:
                st.write(f"- {warning}")
            if status.get("blocked"):
                st.write("- 这个页面当前不会展示样例业务数据，避免把 fixture 误认为真实数据。")
                st.write("- 请确认 Streamlit secrets 中的 `LINGXING_MCP_URL` 是可由 Streamlit 直接访问的 MCP/SSE 或 Streamable HTTP 端点，并且 `LINGXING_MCP_TRANSPORT` 与远端协议匹配。")


def render_metric_row(summary: Dict[str, Any], currency: str) -> None:
    sales = summary["sales"]
    sp_goal = summary["sp_goal"]
    advertising = summary["advertising"]
    sp = advertising["sp"]
    all_ads = advertising["all_ads"]

    cols = st.columns(6)
    cols[0].metric("总销售额", money(sales["total_sales"], currency))
    cols[1].metric("总订单", number(sales["total_orders"]))
    cols[2].metric("SP 订单", number(sp_goal["orders"]), f"目标 {number(sp_goal['orders_min'])}-{number(sp_goal['orders_max'])}")
    cols[3].metric("SP ACOS", percent(sp["acos"]), f"目标 {percent(sp_goal['target_acos'])}")
    cols[4].metric("SP 花费", money(sp["spend"], currency), f"预算 {money(sp_goal['daily_budget'], currency)}")
    cols[5].metric("全量广告 TACOS", percent(all_ads["tacos"]))


def render_overview(data: Dict[str, Any], summary: Dict[str, Any], currency: str) -> None:
    render_metric_row(summary, currency)
    st.divider()

    sp_goal = summary["sp_goal"]
    all_ads = summary["advertising"]["all_ads"]
    inventory = data["context"]["inventory"]

    cols = st.columns(3)
    cols[0].subheader("SP 目标进度")
    cols[0].progress(min(float(sp_goal["orders_progress_max"] or 0), 1.0), text="SP 订单目标上限进度")
    cols[0].write(f"订单状态：`{sp_goal['orders_status']}`")
    cols[0].write(f"预算使用率：{percent(sp_goal['budget_used_pct'])}")
    cols[0].write(f"ACOS 差距：{percent(sp_goal['acos_delta'])}")

    cols[1].subheader("全量广告")
    cols[1].write(f"花费：{money(all_ads['spend'], currency)}")
    cols[1].write(f"销售额：{money(all_ads['sales'], currency)}")
    cols[1].write(f"ACOS：{percent(all_ads['acos'])}")
    cols[1].write(f"ROAS：{number(all_ads['roas'])}")

    cols[2].subheader("库存/Listing")
    cols[2].write(f"FBA 可售：{number(inventory.get('fba_fulfillable'))}")
    cols[2].write(f"可售天数：{number(inventory.get('days_of_supply'))}")
    cols[2].write(f"断货风险：`{inventory.get('stockout_risk', '-')}`")
    cols[2].write(f"Listing：{data['context']['listing'].get('title', '-')}")


def render_sp_ads(data: Dict[str, Any], summary: Dict[str, Any], currency: str) -> None:
    sp = summary["advertising"]["sp"]
    cols = st.columns(6)
    cols[0].metric("SP 花费", money(sp["spend"], currency))
    cols[1].metric("SP 销售额", money(sp["sales"], currency))
    cols[2].metric("SP 订单", number(sp["orders"]))
    cols[3].metric("SP ACOS", percent(sp["acos"]))
    cols[4].metric("SP CVR", percent(sp["cvr"]))
    cols[5].metric("SP CPA", money(sp["cpa"], currency))
    st.dataframe(data["sp_campaigns"], use_container_width=True)


def render_all_ads(data: Dict[str, Any], summary: Dict[str, Any], currency: str) -> None:
    by_product = summary["advertising"]["by_product"]
    rows = []
    for ad_product, metrics in sorted(by_product.items()):
        rows.append(
            {
                "广告类型": ad_product,
                "花费": metrics["spend"],
                "销售额": metrics["sales"],
                "订单": metrics["orders"],
                "ACOS": metrics["acos"],
                "ROAS": metrics["roas"],
                "CPC": metrics["cpc"],
                "CTR": metrics["ctr"],
                "CVR": metrics["cvr"],
            }
        )
    st.dataframe(rows, use_container_width=True)
    st.subheader("Campaign 明细")
    st.dataframe(data["campaigns"], use_container_width=True)


def render_context(data: Dict[str, Any]) -> None:
    st.subheader("Listing / 库存")
    cols = st.columns(2)
    cols[0].json(data["context"]["listing"])
    cols[1].json(data["context"]["inventory"])
    st.subheader("市场 / 关键词 / 行动历史")
    st.json(
        {
            "market": data["context"]["market"],
            "keyword_market": data["context"]["keyword_market"],
            "action_history": data["context"]["action_history"],
        }
    )


def render_details(data: Dict[str, Any]) -> None:
    st.subheader("广告口径判定")
    st.dataframe(data["ad_scope_resolutions"], use_container_width=True)
    st.download_button(
        "下载当前规范化数据 JSON",
        data=str(data),
        file_name=f"{data['asin']}_dashboard_snapshot.txt",
    )


def main() -> None:
    targets = load_targets()
    st.title("Amazon Selling Monitor")
    st.caption(f"ASIN: {targets.get('asin', lingxing_client.DEFAULT_ASIN)} | 中文实时经营看板")

    if "refresh_counter" not in st.session_state:
        st.session_state.refresh_counter = 0
    if st.button("刷新最新数据"):
        st.session_state.refresh_counter += 1
        load_dashboard_data.clear()

    with st.spinner("正在拉取最新数据..."):
        data = load_dashboard_data(st.session_state.refresh_counter)

    render_source_status(data)
    currency = "$" if data["sales"].get("currency", "USD") == "USD" else ""
    summary = build_dashboard_summary(
        total_sales=data["sales"]["total_sales"],
        total_orders=data["sales"]["total_orders"],
        total_units=data["sales"]["total_units"],
        ad_summary=data["advertising"],
        targets=targets,
    )

    tabs = st.tabs(["总览", "SP 广告", "全量广告", "经营上下文", "明细数据"])
    with tabs[0]:
        render_overview(data, summary, currency)
    with tabs[1]:
        render_sp_ads(data, summary, currency)
    with tabs[2]:
        render_all_ads(data, summary, currency)
    with tabs[3]:
        render_context(data)
    with tabs[4]:
        render_details(data)


if __name__ == "__main__":
    main()
