"""Metric calculations for Amazon selling monitor."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Mapping, Optional


NUMERIC_FIELDS = ("spend", "sales", "orders", "clicks", "impressions")


def safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) / float(denominator), 4)


def sum_field(rows: Iterable[Mapping[str, object]], field: str) -> float:
    total = 0.0
    for row in rows:
        value = row.get(field)
        if value in (None, ""):
            continue
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue
    return round(total, 4)


def summarize_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    total_sales: Optional[float] = None,
    total_orders: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    materialized = list(rows)
    spend = sum_field(materialized, "spend")
    sales = sum_field(materialized, "sales")
    orders = sum_field(materialized, "orders")
    clicks = sum_field(materialized, "clicks")
    impressions = sum_field(materialized, "impressions")
    return {
        "spend": spend,
        "sales": sales,
        "orders": orders,
        "clicks": clicks,
        "impressions": impressions,
        "acos": safe_div(spend, sales),
        "roas": safe_div(sales, spend),
        "cpc": safe_div(spend, clicks),
        "ctr": safe_div(clicks, impressions),
        "cvr": safe_div(orders, clicks),
        "cpa": safe_div(spend, orders),
        "tacos": safe_div(spend, total_sales),
        "order_share": safe_div(orders, total_orders),
    }


def summarize_by_product(rows: Iterable[Mapping[str, object]]) -> Dict[str, Dict[str, Optional[float]]]:
    grouped = defaultdict(list)
    for row in rows:
        ad_product = str(row.get("ad_product") or "unknown")
        grouped[ad_product].append(row)
    return {key: summarize_rows(value) for key, value in grouped.items()}


def summarize_advertising(
    *,
    sp_campaigns: Iterable[Mapping[str, object]],
    all_campaigns: Iterable[Mapping[str, object]],
    total_sales: Optional[float],
    total_orders: Optional[float],
) -> Dict[str, Dict[str, Optional[float]]]:
    all_rows = list(all_campaigns)
    sp_rows = list(sp_campaigns)
    return {
        "sp": summarize_rows(sp_rows, total_sales=total_sales, total_orders=total_orders),
        "all_ads": summarize_rows(all_rows, total_sales=total_sales, total_orders=total_orders),
        "by_product": summarize_by_product(all_rows),
    }


def build_dashboard_summary(
    *,
    total_sales: float,
    total_orders: float,
    total_units: float,
    ad_summary: Mapping[str, Mapping[str, Optional[float]]],
    targets: Mapping[str, float],
    window_days: int = 1,
) -> Dict[str, object]:
    sp = ad_summary.get("sp", {})
    target_acos = float(targets["sp_target_acos"])
    daily_budget = float(targets["sp_daily_budget_current"])
    days = max(int(window_days or 1), 1)
    window_budget = daily_budget * days
    min_orders = float(targets["sp_orders_daily_min"]) * days
    max_orders = float(targets["sp_orders_daily_max"]) * days
    sp_orders = float(sp.get("orders") or 0)
    sp_spend = float(sp.get("spend") or 0)
    sp_acos = sp.get("acos")

    return {
        "sales": {
            "total_sales": total_sales,
            "total_orders": total_orders,
            "total_units": total_units,
        },
        "sp_goal": {
            "target_acos": target_acos,
            "current_acos": sp_acos,
            "acos_delta": round(float(sp_acos or 0) - target_acos, 4),
            "daily_budget": daily_budget,
            "window_budget": window_budget,
            "window_days": days,
            "budget_used_pct": safe_div(sp_spend, window_budget),
            "orders": sp_orders,
            "orders_min": min_orders,
            "orders_max": max_orders,
            "orders_status": classify_order_target(sp_orders, min_orders, max_orders),
            "orders_progress_min": safe_div(sp_orders, min_orders),
            "orders_progress_max": safe_div(sp_orders, max_orders),
        },
        "advertising": dict(ad_summary),
    }


def classify_order_target(orders: float, min_orders: float, max_orders: float) -> str:
    if orders < min_orders:
        return "below_min"
    if orders > max_orders:
        return "above_max"
    return "in_range"
