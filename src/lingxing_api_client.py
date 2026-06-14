"""Lingxing REST API client for parent ASIN dashboard pulls."""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from .lingxing_client import DEFAULT_ASIN, as_float, as_int, first_present, normalize_dashboard_payload


DEFAULT_API_BASE_URL = "http://34.143.132.97:8367"
DEFAULT_TIMEOUT = 8.0


class LingxingAPIError(RuntimeError):
    """Raised when the Lingxing REST API request or response is unusable."""


class LingxingAPIConfigError(ValueError):
    """Raised when Streamlit secrets do not contain the required API settings."""


PostJSON = Callable[[str, Mapping[str, Any], Mapping[str, str], float], Any]


@dataclass(frozen=True)
class LingxingAPIConfig:
    api_base_url: str
    account: str
    profile_id: str
    user_token: str
    parent_asin: str
    focus_asin: str = DEFAULT_ASIN
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "LingxingAPIConfig":
        required = {
            "LINGXING_API_BASE_URL": values.get("LINGXING_API_BASE_URL"),
            "LINGXING_ACCOUNT": values.get("LINGXING_ACCOUNT"),
            "LINGXING_PROFILE_ID": values.get("LINGXING_PROFILE_ID"),
            "LINGXING_USER_TOKEN": values.get("LINGXING_USER_TOKEN"),
            "LINGXING_PARENT_ASIN": values.get("LINGXING_PARENT_ASIN") or values.get("PARENT_ASIN"),
        }
        missing = [key for key, value in required.items() if value in (None, "")]
        if missing:
            raise LingxingAPIConfigError(
                "Missing Lingxing REST API Streamlit secrets: "
                + ", ".join(missing)
                + ". Configure these in Streamlit secrets; do not write live tokens into the repo."
            )
        timeout = values.get("LINGXING_API_TIMEOUT_SECONDS", DEFAULT_TIMEOUT)
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            timeout_value = DEFAULT_TIMEOUT
        return cls(
            api_base_url=str(required["LINGXING_API_BASE_URL"]).rstrip("/"),
            account=str(required["LINGXING_ACCOUNT"]),
            profile_id=str(required["LINGXING_PROFILE_ID"]),
            user_token=str(required["LINGXING_USER_TOKEN"]),
            parent_asin=str(required["LINGXING_PARENT_ASIN"]),
            focus_asin=str(values.get("ASIN") or values.get("LINGXING_CHILD_ASIN") or DEFAULT_ASIN),
            timeout=timeout_value,
        )


class LingxingAPIClient:
    """REST API-first Lingxing client.

    The client intentionally does not use the `/orders` endpoint for dashboard
    totals because parent ASIN order pulls can return no store-order data. The
    source of truth is child-level `/asin-all`, with `/asin-sales` as a units
    fallback for each child ASIN.
    """

    def __init__(self, config: LingxingAPIConfig, post_json: Optional[PostJSON] = None) -> None:
        self.config = config
        self._post_json = post_json or self._post_json

    def headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-USER-TOKEN": self.config.user_token,
            "X-LINGXING-ACCOUNT": self.config.account,
            "X-Profile-Id": self.config.profile_id,
        }

    def discover_child_asins(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "offset": 0,
            "length": 100,
            "asin_type": "parent_asin",
            "fetch_child_images": False,
        }
        body = self._call("/api/lingxing/asin-all-list", payload)
        parents = _extract_rows(body)
        selected_parent = None
        for row in parents:
            parent_asin = first_present(row, ("parent_asin", "parentAsin", "asin"))
            if str(parent_asin or "").strip() == self.config.parent_asin:
                selected_parent = row
                break
        if selected_parent is None:
            return [
                {
                    "asin": self.config.focus_asin,
                    "parent_asin": self.config.parent_asin,
                    "status": "configured_fallback",
                }
            ]

        child_rows = selected_parent.get("child_asins") or selected_parent.get("children") or []
        children: List[Dict[str, Any]] = []
        if isinstance(child_rows, list):
            for item in child_rows:
                if isinstance(item, Mapping):
                    asin = first_present(item, ("asin", "child_asin", "childAsin"))
                    if asin:
                        child = dict(item)
                        child["asin"] = str(asin)
                        child.setdefault("parent_asin", self.config.parent_asin)
                        children.append(child)
                elif item:
                    children.append({"asin": str(item), "parent_asin": self.config.parent_asin})
        if not children:
            children.append(
                {
                    "asin": self.config.focus_asin,
                    "parent_asin": self.config.parent_asin,
                    "status": "configured_fallback",
                }
            )
        return _dedupe_children(children, self.config.focus_asin)

    def fetch_dashboard(
        self,
        start_date: str,
        end_date: str,
        *,
        sp_campaign_ids: Optional[Iterable[str]] = None,
        known_non_sp_campaign_ids: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        try:
            children = self.discover_child_asins(start_date, end_date)
        except Exception as exc:
            warnings.append(
                f"asin-all-list failed for parent {self.config.parent_asin}: {_short_exception(exc)}"
            )
            children = [
                {
                    "asin": self.config.focus_asin,
                    "parent_asin": self.config.parent_asin,
                    "status": "configured_fallback",
                }
            ]

        child_results: Dict[str, Dict[str, Any]] = {}
        max_workers = max(1, min(8, len(children) + 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            child_futures = {
                executor.submit(self._fetch_child_snapshot, child, start_date, end_date): str(child["asin"])
                for child in children
                if child.get("asin")
            }
            campaigns_future = executor.submit(self.fetch_campaigns, start_date, end_date)
            for future in as_completed(child_futures):
                asin = child_futures[future]
                try:
                    variation, child_warnings = future.result()
                    child_results[asin] = variation
                    warnings.extend(child_warnings)
                except Exception as exc:
                    warnings.append(f"child pull failed for {asin}: {_short_exception(exc)}")
                    child_results[asin] = _variation_from_meta(
                        {"asin": asin, "parent_asin": self.config.parent_asin},
                        status="failed",
                    )
            try:
                campaigns = campaigns_future.result()
            except Exception as exc:
                campaigns = []
                warnings.append(
                    f"campaigns failed for parent {self.config.parent_asin}: {_short_exception(exc)}"
                )

        variations = [child_results[str(child["asin"])] for child in children if str(child.get("asin")) in child_results]
        listing = _select_listing_row(variations, self.config.focus_asin)
        inventory = _aggregate_inventory(variations)
        sales_total = round(sum(float(row.get("sales") or 0) for row in variations), 4)
        orders_total = int(sum(float(row.get("orders") or 0) for row in variations))
        units_total = int(sum(float(row.get("units") or 0) for row in variations))

        payload = {
            "asin": self.config.focus_asin,
            "parent_asin": self.config.parent_asin,
            "selected_child_asin": self.config.focus_asin,
            "orders": {
                "total_orders": orders_total,
                "total_sale_total": sales_total,
                "currency_code": "USD",
            },
            "asin_sales": {"total_units": units_total},
            "campaigns": campaigns,
            "listing": listing,
            "inventory": inventory,
            "child_asins": variations,
            "sales_family": {
                "parent_asin": self.config.parent_asin,
                "selected_child_asin": self.config.focus_asin,
                "child_count": len(variations),
                "active_child_count": len([row for row in variations if float(row.get("units") or 0) > 0]),
                "sales": sales_total,
                "orders": orders_total,
                "units": units_total,
            },
            "date_window": {"start_date": start_date, "end_date": end_date},
            "pulled_at": _now_iso(),
            "source_mode": "live_api",
            "warnings": warnings,
            "sp_campaign_ids": list(sp_campaign_ids or []),
            "known_non_sp_campaign_ids": list(known_non_sp_campaign_ids or []),
        }
        return normalize_dashboard_payload(payload)

    def fetch_campaigns(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        payload = {
            "date_range": [start_date, end_date],
            "parent_asin": [self.config.parent_asin],
            "page": 1,
            "length": 100,
            "sort_field": "spends",
            "sort_type": "desc",
        }
        body = self._call("/api/lingxing/campaigns", payload)
        rows = _extract_rows(body)
        return [dict(row) for row in rows if not _is_campaign_summary_row(row)]

    def _fetch_child_snapshot(
        self,
        child: Mapping[str, Any],
        start_date: str,
        end_date: str,
    ) -> Tuple[Dict[str, Any], List[str]]:
        asin = str(child.get("asin") or "").strip()
        warnings: List[str] = []
        try:
            detail = self.fetch_child_detail(asin, start_date, end_date)
            if detail:
                merged = dict(child)
                merged.update(detail)
                return _variation_from_detail(merged, status="ok"), warnings
            warnings.append(f"asin-all returned no detail for {asin}; using asin-sales fallback.")
        except Exception as exc:
            warnings.append(f"asin-all failed for {asin}: {_short_exception(exc)}; using asin-sales fallback.")

        try:
            units = self.fetch_child_units(asin, start_date, end_date)
        except Exception as exc:
            warnings.append(f"asin-sales fallback failed for {asin}: {_short_exception(exc)}")
            units = 0
        variation = _variation_from_meta(child, status="sales_fallback")
        variation["units"] = units
        return variation, warnings

    def fetch_child_detail(self, asin: str, start_date: str, end_date: str) -> Dict[str, Any]:
        payload = {
            "asin": asin,
            "date_start": start_date,
            "date_end": end_date,
        }
        body = self._call("/api/lingxing/asin-all", payload)
        rows = _extract_rows(body)
        return dict(rows[0]) if rows else {}

    def fetch_child_units(self, asin: str, start_date: str, end_date: str) -> int:
        payload = {
            "asin": asin,
            "date_range": [start_date, end_date],
        }
        body = self._call("/api/lingxing/asin-sales", payload)
        if isinstance(body, Mapping):
            units = first_present(body, ("total_units", "units", "volume", "sales"))
            if units is None and isinstance(body.get("data"), Mapping):
                units = first_present(body["data"], ("total_units", "units", "volume", "sales"))
            return as_int(units) or 0
        return 0

    def _call(self, path: str, payload: Mapping[str, Any]) -> Any:
        response = self._post_json(path, payload, self.headers(), self.config.timeout)
        return _unwrap_response(path, response)

    def _post_json(self, path: str, payload: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> Any:
        url = f"{self.config.api_base_url.rstrip('/')}/{path.lstrip('/')}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LingxingAPIError(_summarize_http_error(path, exc.code, body)) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise LingxingAPIError(f"Request failed for {path}: {exc}") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LingxingAPIError(f"Invalid JSON from {path}: {text[:200]}") from exc


def _unwrap_response(path: str, response: Any) -> Any:
    if not isinstance(response, Mapping):
        return response
    success = response.get("success")
    if success is False:
        message = response.get("message") or response.get("msg") or response.get("error") or response
        raise LingxingAPIError(f"{path} returned success=false: {message}")
    code = response.get("code")
    message = str(response.get("message") or response.get("msg") or "").strip().lower()
    if code in (1, "1") and (success is True or message in {"success", "ok"}):
        pass
    elif code not in (None, 0, "0", 200, "200"):
        message = response.get("message") or response.get("msg") or response.get("error") or response
        raise LingxingAPIError(f"{path} returned code={code}: {message}")
    if "data" in response:
        return response["data"]
    return response


def _short_exception(exc: Exception) -> str:
    text = str(exc)
    if "HTTP 422" in text and "Field required" in text:
        fields = _missing_fields_from_text(text)
        if fields:
            return "LingxingAPIError: HTTP 422 validation error; missing request fields: " + ", ".join(fields)
    if len(text) > 220:
        text = text[:217].rstrip() + "..."
    return f"{type(exc).__name__}: {text}"


def _summarize_http_error(path: str, code: int, body: str) -> str:
    if code == 422:
        fields = _missing_fields_from_text(body)
        if fields:
            return f"HTTP 422 from {path}: missing request fields: {', '.join(fields)}"
        return f"HTTP 422 from {path}: validation error"
    compact = " ".join(body.split())
    if len(compact) > 220:
        compact = compact[:217].rstrip() + "..."
    return f"HTTP {code} from {path}: {compact}"


def _missing_fields_from_text(text: str) -> List[str]:
    fields = re.findall(r'"loc"\s*:\s*\[\s*"body"\s*,\s*"([^"]+)"\s*\]', text)
    if not fields:
        fields = re.findall(r"'loc'\s*:\s*\[\s*'body'\s*,\s*'([^']+)'\s*\]", text)
    deduped: List[str] = []
    for field in fields:
        if field not in deduped:
            deduped.append(field)
    return deduped


def _extract_rows(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if not isinstance(value, Mapping):
        return []
    for key in ("list", "rows", "items", "records", "data"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
        if isinstance(rows, Mapping):
            nested = _extract_rows(rows)
            if nested:
                return nested
    return []


def _dedupe_children(children: Iterable[Mapping[str, Any]], focus_asin: str) -> List[Dict[str, Any]]:
    seen = set()
    rows: List[Dict[str, Any]] = []
    for child in children:
        asin = str(child.get("asin") or "").strip()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        rows.append(dict(child))
    return sorted(rows, key=lambda row: 0 if row.get("asin") == focus_asin else 1)


def _variation_from_meta(meta: Mapping[str, Any], *, status: str) -> Dict[str, Any]:
    return {
        "asin": str(first_present(meta, ("asin", "child_asin", "childAsin")) or ""),
        "parent_asin": str(first_present(meta, ("parent_asin", "parentAsin")) or ""),
        "title": first_present(meta, ("title", "product_name", "productName", "item_name")) or "",
        "image_url": first_present(meta, ("image_url", "small_image_url", "main_image", "pic_url")),
        "seller_sku": first_present(meta, ("seller_sku", "sku", "local_sku", "local_sku_name")),
        "units": 0,
        "sales": 0,
        "orders": 0,
        "ad_spend": 0,
        "inventory": 0,
        "status": status,
        "currency": "USD",
    }


def _variation_from_detail(row: Mapping[str, Any], *, status: str) -> Dict[str, Any]:
    variation = _variation_from_meta(row, status=status)
    variation["sales"] = as_float(first_present(row, ("amount", "total_sale_total", "total_sales", "sales"))) or 0
    variation["orders"] = as_int(first_present(row, ("order_items", "total_orders", "orders"))) or 0
    variation["units"] = as_int(first_present(row, ("volume", "quantity", "total_units", "units"))) or 0
    spend = as_float(first_present(row, ("spend", "spends", "ads_spend", "ad_spend")))
    if spend is None:
        spend = (as_float(row.get("ads_sp_cost")) or 0) + (as_float(row.get("shared_ads_sbv_cost")) or 0)
    variation["ad_spend"] = spend or 0
    variation["ad_sales"] = as_float(first_present(row, ("ad_sales_amount", "ads_sales", "ad_sales"))) or 0
    variation["inventory"] = _extract_inventory_units(row)
    variation["currency"] = str(first_present(row, ("currency_code", "currency")) or "USD")
    variation["raw"] = dict(row)
    return variation


def _extract_inventory_units(row: Mapping[str, Any]) -> int:
    available = row.get("available_inventory")
    if isinstance(available, Mapping):
        value = first_present(
            available,
            (
                "afn_fulfillable_quantity",
                "fba_fulfillable",
                "fulfillable_quantity",
                "available_quantity",
                "quantity",
            ),
        )
        if value is not None:
            return as_int(value) or 0
    return as_int(
        first_present(
            row,
            (
                "fba_fulfillable",
                "afn_fulfillable_quantity",
                "fulfillable_quantity",
                "available_quantity",
                "inventory",
            ),
        )
    ) or 0


def _select_listing_row(variations: Iterable[Mapping[str, Any]], focus_asin: str) -> Dict[str, Any]:
    rows = list(variations)
    selected = None
    for row in rows:
        if row.get("asin") == focus_asin:
            selected = row
            break
    if selected is None and rows:
        selected = rows[0]
    if not selected:
        return {}
    raw = selected.get("raw") if isinstance(selected.get("raw"), Mapping) else selected
    listing = dict(raw)
    listing.setdefault("title", selected.get("title"))
    listing.setdefault("image_url", selected.get("image_url"))
    return listing


def _aggregate_inventory(variations: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(variations)
    total = int(sum(float(row.get("inventory") or 0) for row in rows))
    return {
        "fba_fulfillable": total,
        "child_count": len(rows),
        "stockout_risk": "unknown" if rows else None,
    }


def _is_campaign_summary_row(row: Mapping[str, Any]) -> bool:
    campaign_id = first_present(row, ("campaign_id", "campaignId", "id"))
    if campaign_id not in (None, ""):
        return False
    name = str(first_present(row, ("campaign_name", "campaignName", "name")) or "").strip().lower()
    if name in {"summary", "total", "合计", "汇总"}:
        return True
    return bool(row.get("is_summary") or row.get("summary"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
