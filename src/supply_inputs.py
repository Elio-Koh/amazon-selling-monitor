"""Manual and spreadsheet-backed supply input normalization."""

from __future__ import annotations

import calendar
import csv
import io
import re
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_GOOGLE_SHEET_GIDS = {
    "sales_plan": "0",
    "procurement": "1649540089",
    "fba_shipments": "1400239777",
    "logistics_cycle": "2114845496",
}


def parse_sales_plan_csv(csv_text: str, *, anchor_date: Optional[date] = None) -> Dict[str, Any]:
    anchor = anchor_date or date.today()
    rows = _nonempty_rows(csv_text)
    updated_at = rows[0][0] if rows and rows[0] else ""
    month_row = _find_row(rows, "月份")
    units_row = _find_row(rows, "销量")
    monthly_units: Dict[int, int] = {}
    if month_row and units_row:
        for idx, month_value in enumerate(month_row[1:], start=1):
            month = _as_int(month_value)
            if month is None or month < 1 or month > 12:
                continue
            units = _as_int(_cell(units_row, idx))
            if units is not None:
                monthly_units[month] = units

    current_month_target = monthly_units.get(anchor.month)
    planned_daily = None
    if current_month_target is not None:
        planned_daily = round(current_month_target / calendar.monthrange(anchor.year, anchor.month)[1], 2)

    return {
        "updated_at": updated_at,
        "monthly_units": monthly_units,
        "current_month_target_units": current_month_target,
        "planned_daily_units": planned_daily,
    }


def parse_procurement_csv(csv_text: str, *, reference_year: Optional[int] = None) -> Dict[str, Any]:
    year = reference_year or date.today().year
    rows = _nonempty_rows(csv_text)
    lead_time_days = None
    unit_cost_usd = None
    purchase_total_units = None
    shipped_total_units = None
    unshipped_units = None

    for row in rows:
        for idx, value in enumerate(row):
            if "产品交期" in value:
                lead_time_days = _as_int(_next_nonempty(row, idx + 1))
            elif "不含税采购成本" in value:
                unit_cost_usd = _as_float(_next_matching(row[idx + 1 :], lambda cell: "$" in cell) or _next_nonempty(row, idx + 1))
            elif "未交数量" in value:
                unshipped_units = _as_int(_next_nonempty(row, idx + 1))
            elif "备货汇总" in value:
                purchase_total_units = _as_int(_next_nonempty(row, idx + 1))
            elif "出货汇总" in value:
                shipped_total_units = _as_int(_next_nonempty(row, idx + 1))

    header_index = _find_row_index(rows, "备货日期")
    detail_rows: List[Dict[str, Any]] = []
    if header_index is not None:
        for row in rows[header_index + 1 :]:
            if not any(row):
                continue
            purchase_date = _parse_date(_cell(row, 0), year)
            planned_units = _as_int(_cell(row, 1))
            delivery_date = _parse_date(_cell(row, 4), year)
            delivery_units = _as_int(_cell(row, 5))
            if purchase_date is None and planned_units is None and delivery_date is None and delivery_units is None:
                continue
            detail_rows.append(
                {
                    "purchase_date": purchase_date,
                    "planned_units": planned_units,
                    "delivery_status": _cell(row, 2),
                    "delivery_date": delivery_date,
                    "delivery_units": delivery_units,
                    "shipment_status": _cell(row, 6),
                }
            )

    return {
        "lead_time_days": lead_time_days,
        "unit_cost_usd": unit_cost_usd,
        "purchase_total_units": purchase_total_units,
        "shipped_total_units": shipped_total_units,
        "unshipped_units": unshipped_units,
        "rows": detail_rows,
    }


def parse_fba_shipments_csv(csv_text: str, *, asin: Optional[str] = None, reference_year: Optional[int] = None) -> Dict[str, Any]:
    year = reference_year or date.today().year
    rows = _dict_rows(csv_text)
    inherited: Dict[str, Any] = {}
    normalized_rows: List[Dict[str, Any]] = []
    for raw in rows:
        current = {
            "arranged_date_raw": _get(raw, "安排时间"),
            "ship_date_raw": _get(raw, "出货时间"),
            "approval_id": _get(raw, "飞书审批单号"),
            "origin": _get(raw, "发货地"),
            "destination": _get(raw, "收货地"),
            "sku": _get(raw, "（M）SKU", "(M)SKU", "M SKU", "SKU"),
            "asin": _get(raw, "ASIN"),
            "product_label": _get(raw, "产品标"),
            "group_total_units": _as_int(_get(raw, "发货总数")),
        }
        for key, value in current.items():
            if value not in (None, ""):
                inherited[key] = value

        row_asin = str(inherited.get("asin") or "").strip()
        if asin and row_asin and row_asin != asin:
            continue

        line_units = _as_int(_get(raw, "件数")) or _as_int(_get(raw, "发货总数")) or 0
        shipment_id = _get(raw, "Shipment ID")
        ship_to = _get(raw, "Ship to")
        if line_units <= 0 and not shipment_id and not ship_to:
            continue

        actual_delivery = _get(raw, "实际送达")
        planned_delivery = _get(raw, "填写送达日期")
        status = _shipment_status(actual_delivery, planned_delivery)
        normalized_rows.append(
            {
                "arranged_date": _parse_date(str(inherited.get("arranged_date_raw") or ""), year),
                "ship_date_raw": inherited.get("ship_date_raw") or "",
                "approval_id": inherited.get("approval_id") or "",
                "origin": inherited.get("origin") or "",
                "destination": inherited.get("destination") or "",
                "sku": inherited.get("sku") or "",
                "asin": row_asin,
                "product_label": inherited.get("product_label") or "",
                "group_total_units": inherited.get("group_total_units"),
                "line_units": line_units,
                "cartons": _as_int(_get(raw, "Box")),
                "units_per_carton": _as_int(_get(raw, "装箱数")),
                "shipment_id": shipment_id,
                "reference_id": _get(raw, "Refernce ID", "Reference ID"),
                "ship_to": ship_to,
                "carrier": _get(raw, "运输方式"),
                "planned_delivery_raw": planned_delivery,
                "actual_delivery_raw": actual_delivery,
                "tracking_number": _get(raw, "后台跟踪号"),
                "status": status,
            }
        )

    total_units = sum(int(row.get("line_units") or 0) for row in normalized_rows)
    delivered_units = sum(int(row.get("line_units") or 0) for row in normalized_rows if row.get("status") == "delivered")
    return {
        "total_units": total_units,
        "delivered_units": delivered_units,
        "open_units": total_units - delivered_units,
        "rows": normalized_rows,
    }


def parse_logistics_cycle_csv(csv_text: str) -> Dict[str, Any]:
    rows = _dict_rows(csv_text)
    out = []
    for row in rows:
        method = _get(row, "物流方式", "method")
        raw_lead_time = _get(row, "投递时效", "lead_time")
        if not method and not raw_lead_time:
            continue
        min_days, max_days = _parse_day_range(raw_lead_time)
        out.append(
            {
                "method": method,
                "min_days": min_days,
                "max_days": max_days,
                "raw_lead_time": raw_lead_time,
            }
        )
    return {"rows": out}


def parse_inventory_csv(csv_text: str, *, asin: Optional[str] = None) -> Dict[str, Any]:
    rows = []
    total = 0
    for raw in _dict_rows(csv_text):
        row_asin = _get(raw, "ASIN", "asin")
        if asin and row_asin and row_asin != asin:
            continue
        quantity = _as_int(
            _get(
                raw,
                "FBA Fulfillable",
                "FBA可售",
                "FBA可售库存",
                "可售库存",
                "库存",
                "quantity",
                "inventory",
            )
        )
        if quantity is None:
            continue
        total += quantity
        rows.append(
            {
                "asin": row_asin,
                "sku": _get(raw, "SKU", "sku", "（M）SKU"),
                "fba_fulfillable": quantity,
                "source_row": dict(raw),
            }
        )
    return {"fba_fulfillable": total if rows else None, "rows": rows}


def compute_stockout_risk(
    fba_fulfillable_units: Optional[Any],
    sales_plan: Mapping[str, Any],
    *,
    anchor_date: Optional[date] = None,
) -> Dict[str, Any]:
    anchor = anchor_date or date.today()
    data_gaps: List[str] = []
    inventory_units = _as_float(fba_fulfillable_units)
    if inventory_units is None:
        data_gaps.append("inventory.fba_fulfillable")
    planned_daily_units = _as_float(sales_plan.get("planned_daily_units"))
    if planned_daily_units in (None, 0):
        data_gaps.append("operations.sales_plan.planned_daily_units")
    if data_gaps:
        return {
            "level": "unknown",
            "coverage_days": None,
            "projected_stockout_date": None,
            "reason": "缺少库存或销售计划，无法计算缺货风险。",
            "data_gaps": data_gaps,
        }

    coverage_days = round(float(inventory_units) / float(planned_daily_units), 1)
    if coverage_days < 14:
        level = "critical"
    elif coverage_days < 30:
        level = "high"
    elif coverage_days < 45:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "coverage_days": coverage_days,
        "projected_stockout_date": (anchor + timedelta(days=int(coverage_days))).isoformat(),
        "reason": f"FBA 可售库存按销售计划可覆盖约 {coverage_days:g} 天。",
        "data_gaps": [],
    }


def build_operations_snapshot(
    *,
    sales_plan: Optional[Mapping[str, Any]] = None,
    procurement: Optional[Mapping[str, Any]] = None,
    fba_shipments: Optional[Mapping[str, Any]] = None,
    logistics_cycle: Optional[Mapping[str, Any]] = None,
    inventory: Optional[Mapping[str, Any]] = None,
    dashboard_inventory: Optional[Mapping[str, Any]] = None,
    anchor_date: Optional[date] = None,
    source: str = "manual",
    warnings: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    inventory = dict(inventory or {})
    dashboard_inventory = dict(dashboard_inventory or {})
    inventory_units = inventory.get("fba_fulfillable")
    inventory_source = "manual_upload"
    if inventory_units in (None, ""):
        inventory_units = dashboard_inventory.get("fba_fulfillable")
        inventory_source = "lingxing_dashboard"
    plan = dict(sales_plan or {})
    return {
        "source_status": {
            "mode": source,
            "warnings": list(warnings or []),
        },
        "sales_plan": plan,
        "procurement": dict(procurement or _empty_procurement()),
        "fba_shipments": dict(fba_shipments or _empty_shipments()),
        "logistics_cycle": dict(logistics_cycle or {"rows": []}),
        "inventory": {
            **inventory,
            "fba_fulfillable": inventory_units,
            "source": inventory_source if inventory_units not in (None, "") else "missing",
        },
        "stockout_risk": compute_stockout_risk(inventory_units, plan, anchor_date=anchor_date),
    }


def build_google_sheet_export_url(sheet_id_or_url: str, gid: str) -> str:
    sheet_id = extract_google_sheet_id(sheet_id_or_url)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def extract_google_sheet_id(sheet_id_or_url: str) -> str:
    value = str(sheet_id_or_url or "").strip()
    match = re.search(r"/spreadsheets/d/([^/?#]+)", value)
    if match:
        return match.group(1)
    if not value or "/" in value:
        raise ValueError("Google Sheet ID or URL is invalid.")
    return value


def fetch_google_sheet_csv(sheet_id_or_url: str, gid: str, *, timeout: float = 8.0) -> str:
    url = build_google_sheet_export_url(sheet_id_or_url, gid)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8-sig")


def load_google_sheet_operations(
    sheet_id_or_url: str,
    *,
    anchor_date: Optional[date] = None,
    asin: Optional[str] = None,
    timeout: float = 8.0,
    gids: Optional[Mapping[str, str]] = None,
    dashboard_inventory: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    selected_gids = dict(DEFAULT_GOOGLE_SHEET_GIDS)
    selected_gids.update(dict(gids or {}))
    sales_plan = parse_sales_plan_csv(
        fetch_google_sheet_csv(sheet_id_or_url, selected_gids["sales_plan"], timeout=timeout),
        anchor_date=anchor_date,
    )
    procurement = parse_procurement_csv(
        fetch_google_sheet_csv(sheet_id_or_url, selected_gids["procurement"], timeout=timeout),
        reference_year=(anchor_date or date.today()).year,
    )
    fba_shipments = parse_fba_shipments_csv(
        fetch_google_sheet_csv(sheet_id_or_url, selected_gids["fba_shipments"], timeout=timeout),
        asin=asin,
        reference_year=(anchor_date or date.today()).year,
    )
    logistics_cycle = parse_logistics_cycle_csv(
        fetch_google_sheet_csv(sheet_id_or_url, selected_gids["logistics_cycle"], timeout=timeout)
    )
    return build_operations_snapshot(
        sales_plan=sales_plan,
        procurement=procurement,
        fba_shipments=fba_shipments,
        logistics_cycle=logistics_cycle,
        dashboard_inventory=dashboard_inventory,
        anchor_date=anchor_date,
        source="google_sheet",
    )


def _empty_procurement() -> Dict[str, Any]:
    return {
        "lead_time_days": None,
        "unit_cost_usd": None,
        "purchase_total_units": None,
        "shipped_total_units": None,
        "unshipped_units": None,
        "rows": [],
    }


def _empty_shipments() -> Dict[str, Any]:
    return {
        "total_units": 0,
        "delivered_units": 0,
        "open_units": 0,
        "rows": [],
    }


def _dict_rows(csv_text: str) -> List[Dict[str, str]]:
    cleaned = csv_text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(cleaned))
    rows: List[Dict[str, str]] = []
    for raw in reader:
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw.items()}
        if any(row.values()):
            rows.append(row)
    return rows


def _nonempty_rows(csv_text: str) -> List[List[str]]:
    reader = csv.reader(io.StringIO(csv_text.lstrip("\ufeff")))
    rows: List[List[str]] = []
    for row in reader:
        cleaned = [cell.strip() for cell in row]
        if any(cleaned):
            rows.append(cleaned)
    return rows


def _find_row(rows: Iterable[List[str]], first_cell: str) -> Optional[List[str]]:
    for row in rows:
        if row and row[0] == first_cell:
            return row
    return None


def _find_row_index(rows: List[List[str]], first_cell: str) -> Optional[int]:
    for idx, row in enumerate(rows):
        if row and row[0] == first_cell:
            return idx
    return None


def _cell(row: List[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index].strip()


def _get(row: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return ""


def _next_nonempty(row: List[str], start: int) -> str:
    for value in row[start:]:
        if value:
            return value
    return ""


def _next_matching(values: Iterable[str], predicate: Any) -> str:
    for value in values:
        if value and predicate(value):
            return value
    return ""


def _as_int(value: Any) -> Optional[int]:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _parse_date(value: Any, reference_year: int) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        return _safe_date(reference_year, int(match.group(1)), int(match.group(2)))
    match = re.fullmatch(r"(\d{2})(\d{2})", text)
    if match:
        return _safe_date(reference_year, int(match.group(1)), int(match.group(2)))
    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2})", text)
    if match:
        month = month_names.get(match.group(1).lower())
        if month:
            return _safe_date(reference_year, month, int(match.group(2)))
    return None


def _safe_date(year: int, month: int, day: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _shipment_status(actual_delivery: str, planned_delivery: str) -> str:
    actual = str(actual_delivery or "").strip()
    if actual and "预计" not in actual:
        return "delivered"
    if actual or planned_delivery:
        return "expected"
    return "open"


def _parse_day_range(value: str) -> tuple[Optional[int], Optional[int]]:
    numbers = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return numbers[0], numbers[1]
