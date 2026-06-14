"""Small Pangolinfo Scrape API client for public Amazon context."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List


DEFAULT_BASE_URL = "https://scrapeapi.pangolinfo.com"
TOKEN_ENV = "PANGOLINFO_API_TOKEN"


class PangolinError(RuntimeError):
    """Raised when Pangolinfo returns an unusable response."""


def _json_body(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _coerce_json_entry(entry: Any) -> Any:
    if isinstance(entry, str):
        try:
            return json.loads(entry)
        except json.JSONDecodeError:
            return entry
    return entry


def extract_json_entries(response: Dict[str, Any]) -> List[Any]:
    data = response.get("data")
    if not isinstance(data, dict):
        return []
    raw_entries = data.get("json")
    if raw_entries is None:
        return [data]
    if not isinstance(raw_entries, list):
        raw_entries = [raw_entries]
    return [_coerce_json_entry(entry) for entry in raw_entries]


def extract_results(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in extract_json_entries(response):
        if not isinstance(entry, dict):
            continue
        payload = entry.get("data", entry)
        if not isinstance(payload, dict):
            continue
        results = payload.get("results")
        if isinstance(results, list):
            rows.extend(row for row in results if isinstance(row, dict))
            continue
        items = payload.get("items")
        if isinstance(items, dict):
            data_rows = items.get("data")
            if isinstance(data_rows, list):
                rows.extend(row for row in data_rows if isinstance(row, dict))
        elif isinstance(items, list):
            rows.extend(row for row in items if isinstance(row, dict))
    return rows


class PangolinClient:
    def __init__(
        self,
        *,
        api_token: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 60,
    ) -> None:
        self.api_token = api_token or os.environ.get(TOKEN_ENV, "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        if not self.api_token:
            raise PangolinError(f"{TOKEN_ENV} is required")
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "User-Agent": "amazon-selling-monitor/1.0",
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=_json_body(payload),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise PangolinError(f"Pangolinfo HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise PangolinError(f"Pangolinfo timeout after {self.timeout}s: {reason}") from exc
            raise PangolinError(f"Pangolinfo network error: {reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise PangolinError(f"Pangolinfo timeout after {self.timeout}s: {exc}") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PangolinError("Pangolinfo returned non-JSON response") from exc
        if not isinstance(parsed, dict):
            raise PangolinError("Pangolinfo returned unexpected response shape")
        code = parsed.get("code")
        if code not in (0, "0", None):
            raise PangolinError(f"Pangolinfo API error code={code}: {parsed.get('message', '')}")
        return parsed

    def scrape(self, *, parser_name: str, site: str, content: str, zipcode: str, url: str = "") -> Dict[str, Any]:
        return self._post(
            "/api/v1/scrape",
            {
                "url": url,
                "parserName": parser_name,
                "site": site,
                "content": content,
                "format": "json",
                "bizContext": {"zipcode": zipcode},
            },
        )

    def product_detail(self, *, asin: str, site: str, zipcode: str) -> Dict[str, Any]:
        rows = extract_results(self.scrape(parser_name="amzProductDetail", site=site, content=asin, zipcode=zipcode))
        return rows[0] if rows else {}

    def keyword_search(self, *, keyword: str, site: str, zipcode: str) -> List[Dict[str, Any]]:
        return extract_results(self.scrape(parser_name="amzKeyword", site=site, content=keyword, zipcode=zipcode))

    def product_of_category(self, *, category_id: str, site: str, zipcode: str) -> List[Dict[str, Any]]:
        return extract_results(self.scrape(parser_name="amzProductOfCategory", site=site, content=category_id, zipcode=zipcode))

    def best_sellers(
        self,
        *,
        category_keyword: str,
        site: str,
        zipcode: str,
        category_node_id: str = "",
        category_url: str = "",
    ) -> List[Dict[str, Any]]:
        return extract_results(
            self.scrape(
                parser_name="amzBestSellers",
                site=site,
                content=category_node_id or category_keyword,
                zipcode=zipcode,
                url=category_url,
            )
        )

    def new_releases(
        self,
        *,
        category_keyword: str,
        site: str,
        zipcode: str,
        category_node_id: str = "",
        category_url: str = "",
    ) -> List[Dict[str, Any]]:
        return extract_results(
            self.scrape(
                parser_name="amzNewReleases",
                site=site,
                content=category_node_id or category_keyword,
                zipcode=zipcode,
                url=category_url,
            )
        )
