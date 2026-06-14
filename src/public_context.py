"""Public Amazon context capture and normalization."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .pangolin_client import PangolinClient


SITE_BY_MARKETPLACE = {
    "US": "amz_us",
    "DE": "amz_de",
    "UK": "amz_uk",
    "AU": "amz_au",
    "MX": "amz_mx",
    "IN": "amz_in",
    "CA": "amz_ca",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def first_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        for key in ("text", "value", "name", "title", "deliveryTime", "fastestDelivery"):
            text = first_text(value.get(key))
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = first_text(item)
            if text:
                return text
    return str(value).strip() or None


def listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_float(value: Any) -> Optional[float]:
    text = first_text(value)
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    return float(match.group(1)) if match else None


def parse_int(value: Any) -> Optional[int]:
    text = first_text(value)
    if not text:
        return None
    match = re.search(r"([0-9][0-9,]*)", text)
    return int(match.group(1).replace(",", "")) if match else None


def parse_rank_items(value: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    def add_item(rank: Optional[int], category: Optional[str], source_text: Optional[str] = None) -> None:
        if rank is None or not category:
            return
        normalized_category = category.strip(" .:-")
        if not normalized_category:
            return
        item = {"rank": rank, "category": normalized_category}
        if source_text:
            item["source_text"] = source_text
        if item not in items:
            items.append(item)

    def parse_text(text: Optional[str]) -> None:
        if not text:
            return
        matches = list(re.finditer(r"#?\s*([0-9][0-9,]*)\s+in\s+([^#;\n|]+)", text, flags=re.IGNORECASE))
        for match in matches:
            add_item(int(match.group(1).replace(",", "")), match.group(2), text)

    def parse_value(raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, list):
            for child in raw:
                parse_value(child)
            return
        if isinstance(raw, Mapping):
            rank = parse_int(raw.get("rank") or raw.get("bsr_rank") or raw.get("position") or raw.get("value"))
            category = first_text(
                raw.get("category")
                or raw.get("categoryName")
                or raw.get("category_name")
                or raw.get("name")
                or raw.get("title")
                or raw.get("label")
            )
            add_item(rank, category, first_text(raw.get("text")))
            parse_text(first_text(raw.get("text") or raw.get("display") or raw.get("bestSellersRank")))
            return
        parse_text(first_text(raw))

    parse_value(value)
    return items


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = first_text(value)
    return text.lower() in {"true", "yes", "y", "1", "sponsored"} if text else False


def parse_coupon_pct(coupon_text: Any, price_display: Any = None) -> Optional[float]:
    text = first_text(coupon_text)
    if not text:
        return 0.0
    percent = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if percent:
        return round(float(percent.group(1)) / 100.0, 4)
    amount = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", text)
    price = parse_float(price_display)
    if amount and price and price > 0:
        return round(float(amount.group(1)) / price, 4)
    return None


def has_price_discount(price_display: Any, list_price_display: Any) -> bool:
    price = parse_float(price_display)
    list_price = parse_float(list_price_display)
    return bool(price and list_price and list_price > price)


def normalize_delivery(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        delivery = first_text(value.get("deliveryTime"))
        fastest = first_text(value.get("fastestDelivery"))
        if delivery and fastest:
            return f"{delivery}; fastest {fastest}"
        return delivery or fastest
    return first_text(value)


def normalize_public_listing(product: Mapping[str, Any], *, source: str, zipcode: str) -> Dict[str, Any]:
    captured_at = now_iso()
    price_display = first_text(product.get("price") or product.get("price_display"))
    list_price_display = first_text(product.get("strikethroughPrice") or product.get("list_price_display"))
    rank_payload = product.get("bestSellersRankItems") or product.get("bestSellersRank") or product.get("best_sellers_rank")
    coupon = first_text(product.get("coupon"))
    badge = first_text(product.get("badge")) or ""
    images = [
        text
        for text in (
            first_text(item)
            for item in [product.get("image")] + listify(product.get("images")) + listify(product.get("highResolutionImages"))
        )
        if text
    ]
    features = [text for text in (first_text(item) for item in listify(product.get("features"))) if text]
    deal_present = parse_bool(product.get("deal_present")) or "deal" in badge.lower()
    discount_present = has_price_discount(price_display, list_price_display)
    out = {
        "schema_version": "1.0",
        "asin": first_text(product.get("asin")),
        "title": first_text(product.get("title")),
        "price_display": price_display,
        "list_price_display": list_price_display,
        "coupon_present": bool(coupon),
        "coupon_pct": parse_coupon_pct(coupon, price_display),
        "discount_present": discount_present,
        "deal_present": deal_present,
        "rating": parse_float(product.get("star") or product.get("rating_value") or product.get("rating")),
        "review_count": parse_int(product.get("rating") or product.get("customerReviews") or product.get("review_count")),
        "main_image_url": images[0] if images else None,
        "image_count": len(images),
        "bullets_count": len(features),
        "category_id": first_text(product.get("category_id")),
        "category_name": first_text(product.get("category_name")),
        "best_sellers_rank": first_text(product.get("bestSellersRank") or product.get("best_sellers_rank")),
        "best_sellers_rank_items": parse_rank_items(rank_payload),
        "delivery_promise": normalize_delivery(
            product.get("deliveryTime")
            or product.get("delivery")
            or product.get("deliveryPromise")
            or product.get("delivery_promise")
            or product.get("availability")
            or product.get("inStock")
        ),
        "source": source,
        "freshness": captured_at,
        "captured_at": captured_at,
        "confidence": "measured",
        "zipcode": zipcode,
    }
    required = ("price_display", "coupon_present", "deal_present", "rating", "review_count", "title")
    out["missing_fields"] = [field for field in required if out.get(field) is None]
    return out


def _asin(row: Mapping[str, Any]) -> str:
    return str(row.get("asin") or row.get("competitor_asin") or "").upper().strip()


def _row_price(row: Mapping[str, Any]) -> Optional[float]:
    return parse_float(row.get("price"))


def _min_rank(current: Optional[float], candidate: Optional[float]) -> Optional[float]:
    if candidate is None:
        return current
    return min(current if current is not None else candidate, candidate)


def _category_keyword(listing: Mapping[str, Any], keywords: List[str], configured: Optional[str] = None) -> Optional[str]:
    configured_text = first_text(configured)
    if configured_text:
        return configured_text
    category_name = first_text(listing.get("category_name"))
    if category_name:
        return category_name
    bsr = first_text(listing.get("best_sellers_rank"))
    if bsr:
        match = re.search(r"in\s+(.+)$", bsr, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return keywords[0] if keywords else None


def _category_rank_labels(listing: Mapping[str, Any], keywords: List[str], configured: Optional[str] = None) -> List[Dict[str, str]]:
    labels: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def add(label: Optional[str], level: str) -> None:
        text = first_text(label)
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        labels.append({"label": text, "rank_level": level})

    rank_items = listing.get("best_sellers_rank_items") if isinstance(listing.get("best_sellers_rank_items"), list) else []
    if len(rank_items) > 1:
        add(rank_items[0].get("category"), "major")
        add(rank_items[-1].get("category"), "leaf")
    elif len(rank_items) == 1:
        add(rank_items[0].get("category"), "leaf")
    else:
        add(listing.get("category_name"), "leaf")

    configured_text = first_text(configured)
    if configured_text:
        add(configured_text, "configured")
    if not labels and keywords:
        add(keywords[0], "configured")
    return labels


def _with_configured_leaf_category(
    labels: List[Dict[str, Any]],
    *,
    leaf_category_label: Optional[str],
    leaf_category_node_id: Optional[str],
    best_sellers_url: Optional[str],
    new_releases_url: Optional[str],
) -> List[Dict[str, Any]]:
    label = first_text(leaf_category_label)
    node_id = first_text(leaf_category_node_id)
    if not label and not node_id:
        return [dict(row) for row in labels]
    leaf = {
        "label": label or str(node_id),
        "rank_level": "leaf",
        "category_node_id": node_id,
        "best_sellers_url": first_text(best_sellers_url),
        "new_releases_url": first_text(new_releases_url),
    }
    out = [dict(row) for row in labels if row.get("rank_level") != "leaf" and first_text(row.get("label")) != leaf["label"]]
    out.append(leaf)
    return out


def _row_rank(row: Mapping[str, Any], fallback: int) -> int:
    return parse_int(row.get("rank") or row.get("bsr_rank") or row.get("position") or row.get("index")) or fallback


def _url_with_page(url: str, page: int) -> str:
    if page <= 1:
        return url
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key.lower() != "pg"]
    query.append(("pg", str(page)))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def fetch_amazon_rank_rows_from_url(
    url: str,
    *,
    asin: str,
    category_label: str,
    source: str,
    timeout: int = 8,
    max_pages: int = 2,
) -> List[Dict[str, Any]]:
    """Best-effort fallback for configured Amazon ranking URLs.

    Pangolin remains the primary source. This only extracts ASIN order from the
    public Best Sellers/New Releases HTML when Pangolin cannot locate the leaf
    node rank.
    """
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    base_timeout = max(int(timeout or 1), 1)
    page_limit = max(int(max_pages or 1), 1)
    target_asin = asin.upper().strip()
    for page in range(1, page_limit + 1):
        page_url = _url_with_page(url, page)
        request = urllib.request.Request(
            page_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(request, timeout=base_timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
        asin_matches = re.findall(r'data-asin=["\']([A-Z0-9]{10})["\']', html)
        if not asin_matches:
            asin_matches = re.findall(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?\"'&]|$)", html)
        for found_asin in asin_matches:
            normalized_asin = found_asin.upper()
            if normalized_asin in seen:
                continue
            seen.add(normalized_asin)
            rows.append(
                {
                    "asin": normalized_asin,
                    "rank": len(rows) + 1,
                    "title": None,
                    "category": category_label,
                    "source": source,
                }
            )
            if normalized_asin == target_asin:
                return rows
    return rows


def _set_own_category_rank(
    own_rank: Dict[str, Any],
    *,
    metric: str,
    rank_level: str,
    rank: int,
    category_label: str,
    source: str,
) -> None:
    display_level = rank_level if rank_level in {"major", "leaf"} else "leaf"
    prefix = f"own_{metric}_{display_level}"
    if rank_level == "configured" and own_rank.get(f"{prefix}_rank") is not None:
        return
    own_rank.update(
        {
            f"{prefix}_rank": rank,
            f"{prefix}_category": category_label,
            f"{prefix}_source": source,
        }
    )


def _own_bsr_ranks_from_listing(listing: Mapping[str, Any]) -> Dict[str, Any]:
    own_rank: Dict[str, Any] = {}
    rank_items = listing.get("best_sellers_rank_items") if isinstance(listing.get("best_sellers_rank_items"), list) else []
    if len(rank_items) > 1:
        major = rank_items[0]
        leaf = rank_items[-1]
        if major.get("category") != leaf.get("category"):
            _set_own_category_rank(
                own_rank,
                metric="bsr",
                rank_level="major",
                rank=int(major["rank"]),
                category_label=str(major["category"]),
                source="pangolin:amzProductDetail",
            )
        _set_own_category_rank(
            own_rank,
            metric="bsr",
            rank_level="leaf",
            rank=int(leaf["rank"]),
            category_label=str(leaf["category"]),
            source="pangolin:amzProductDetail",
        )
    elif len(rank_items) == 1:
        leaf = rank_items[0]
        _set_own_category_rank(
            own_rank,
            metric="bsr",
            rank_level="leaf",
            rank=int(leaf["rank"]),
            category_label=str(leaf["category"]),
            source="pangolin:amzProductDetail",
        )
    return own_rank


def _normalize_category_rows(
    *,
    rows: List[Mapping[str, Any]],
    source: str,
    category_label: str,
    rank_level: str,
    own_asin: str,
    category_node_id: Optional[str] = None,
    category_url: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    normalized_rows: List[Dict[str, Any]] = []
    competitor_rows: List[Dict[str, Any]] = []
    own_rank: Dict[str, Any] = {}
    own_found = False
    for idx, row in enumerate(rows, start=1):
        asin = _asin(row)
        if not asin:
            continue
        rank = _row_rank(row, idx)
        normalized = {
            "keyword": f"category:{category_label}",
            "competitor_asin": asin,
            "title": first_text(row.get("title")),
            "price": first_text(row.get("price")),
            "rating": parse_float(row.get("star") or row.get("rating")),
            "review_count": parse_int(row.get("rating") or row.get("customerReviews") or row.get("review_count")),
            "coupon_present": parse_bool(row.get("coupon_present") or row.get("coupon")),
            "deal_present": parse_bool(row.get("deal_present")) or "deal" in (first_text(row.get("badge")) or "").lower(),
            "delivery_promise": normalize_delivery(
                row.get("deliveryTime")
                or row.get("delivery")
                or row.get("deliveryPromise")
                or row.get("delivery_promise")
                or row.get("availability")
                or row.get("inStock")
            ),
            "bsr_rank": rank if source in {"pangolin:amzBestSellers", "amazon:directBestSellersUrl"} else None,
            "category_list_rank": rank,
            "category_label": category_label,
            "category_node_id": category_node_id,
            "category_url": category_url,
            "rank_level": rank_level,
            "category_candidate_source": source,
            "ad_visibility": "category_list",
            "source": source,
        }
        normalized_rows.append(normalized)
        if asin == own_asin:
            own_found = True
            if source in {"pangolin:amzBestSellers", "amazon:directBestSellersUrl"}:
                _set_own_category_rank(
                    own_rank,
                    metric="bsr",
                    rank_level=rank_level,
                    rank=rank,
                    category_label=category_label,
                    source=source,
                )
            elif source in {"pangolin:amzNewReleases", "amazon:directNewReleasesUrl"}:
                _set_own_category_rank(
                    own_rank,
                    metric="new_release",
                    rank_level=rank_level,
                    rank=rank,
                    category_label=category_label,
                    source=source,
                )
            else:
                own_rank.update(
                    {
                        "own_category_list_rank": rank,
                        "own_category_list_category": category_label,
                        "own_category_list_source": source,
                    }
                )
        else:
            competitor_rows.append(normalized)
    if own_found:
        capture_status = "measured"
    elif source in {"pangolin:amzNewReleases", "amazon:directNewReleasesUrl"} and rank_level == "leaf":
        capture_status = "not_in_leaf_new_release_window"
    elif source in {"pangolin:amzBestSellers", "amazon:directBestSellersUrl"} and rank_level == "leaf":
        capture_status = "not_in_leaf_bsr_window"
    else:
        capture_status = "not_in_bsr_window"
    attempt = {
        "source": source,
        "category": category_label,
        "category_node_id": category_node_id,
        "category_url": category_url,
        "rank_level": rank_level,
        "bsr_capture_status": capture_status,
        "bsr_result_count": len(normalized_rows),
        "bsr_window_size": len(rows),
    }
    return normalized_rows, own_rank, [attempt]


def _bsr_capture_failed(
    *,
    source: str,
    category_label: Optional[str],
    error: Exception,
    category_node_id: Optional[str] = None,
    category_url: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "source": source,
        "category": category_label,
        "category_node_id": category_node_id,
        "category_url": category_url,
        "bsr_capture_status": "bsr_capture_failed",
        "bsr_result_count": 0,
        "bsr_window_size": 0,
        "error": f"{type(error).__name__}: {error}",
    }


def _rank_rows_for_keyword(keyword: str, rows: List[Mapping[str, Any]], own_asin: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    own_organic = None
    own_ad = None
    competitors: List[Dict[str, Any]] = []
    organic_position = 0
    ad_position = 0
    for idx, row in enumerate(rows, start=1):
        asin = _asin(row)
        if not asin:
            continue
        sponsored = parse_bool(row.get("sponsored") or row.get("isSponsored") or row.get("ad"))
        if sponsored:
            ad_position += 1
        else:
            organic_position += 1
        organic_rank = None if sponsored else organic_position
        ad_rank = ad_position if sponsored else None
        normalized = {
            "keyword": keyword,
            "competitor_asin": asin,
            "title": first_text(row.get("title")),
            "price": first_text(row.get("price")),
            "rating": parse_float(row.get("star") or row.get("rating")),
            "review_count": parse_int(row.get("rating") or row.get("customerReviews") or row.get("review_count")),
            "coupon_present": parse_bool(row.get("coupon_present") or row.get("coupon")),
            "deal_present": parse_bool(row.get("deal_present")) or "deal" in (first_text(row.get("badge")) or "").lower(),
            "organic_rank": organic_rank,
            "ad_rank": ad_rank,
            "serp_position": idx,
            "ad_visibility": "sponsored" if sponsored else "organic",
            "source": "pangolin:amzKeyword",
        }
        if asin == own_asin:
            own_organic = organic_rank
            own_ad = ad_rank
        else:
            competitors.append(normalized)
    rank_status = "measured" if own_organic is not None or own_ad is not None else "not_in_serp_window"
    rank = {
        "keyword": keyword,
        "rank_status": rank_status,
        "own_organic_rank": own_organic,
        "own_ad_rank": own_ad,
        "result_count": len(rows),
        "source": "pangolin:amzKeyword",
        "freshness": now_iso(),
        "confidence": "measured" if rank_status == "measured" else "estimated",
        "missing_fields": [] if rank_status == "measured" else ["own_keyword_rank"],
    }
    return rank, competitors


def _failed_keyword_rank(keyword: str, error: Exception) -> Dict[str, Any]:
    return {
        "keyword": keyword,
        "rank_status": "failed",
        "own_organic_rank": None,
        "own_ad_rank": None,
        "result_count": 0,
        "source": "pangolin:amzKeyword",
        "freshness": now_iso(),
        "confidence": "missing",
        "missing_fields": ["pangolin_keyword_search"],
        "error": _short_error(error),
    }


def _short_error(error: Exception, *, limit: int = 180) -> str:
    text = f"{type(error).__name__}: {error}".strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _context_status_from_failures(failures: List[str], *, freshness: Optional[str]) -> Dict[str, Any]:
    if not failures:
        return {
            "status": "ok",
            "message": "Pangolin public context loaded.",
            "source": "pangolin",
            "freshness": freshness,
            "warnings": [],
        }
    shown = "; ".join(failures[:3])
    if len(failures) > 3:
        shown = f"{shown}; {len(failures) - 3} more failures"
    return {
        "status": "partial",
        "message": f"Pangolin public context loaded with partial failures: {shown}",
        "source": "pangolin",
        "freshness": freshness,
        "warnings": failures,
    }


def _score_competitors(
    competitors: Iterable[Mapping[str, Any]],
    *,
    pinned: Set[str],
    excluded: Set[str],
    top_n: int,
) -> List[Dict[str, Any]]:
    aggregated: Dict[str, Dict[str, Any]] = {}
    for row in competitors:
        asin = _asin(row)
        if not asin or asin in excluded:
            continue
        current = aggregated.setdefault(
            asin,
            {
                "asin": asin,
                "score": 0.0,
                "why_selected": [],
                "keywords": set(),
                "best_organic_rank": None,
                "best_ad_rank": None,
                "best_bsr_rank": None,
                "best_category_list_rank": None,
                "category_rank_source": None,
                "category_candidate_sources": set(),
                "price": _row_price(row),
                "coupon_present": False,
                "deal_present": False,
                "rating": None,
                "review_count": None,
                "title": None,
                "data_sources": set(),
            },
        )
        current["keywords"].add(row.get("keyword"))
        current["data_sources"].add(row.get("source") or "pangolin")
        current["title"] = current["title"] or first_text(row.get("title"))
        current["rating"] = current["rating"] or parse_float(row.get("rating"))
        current["review_count"] = current["review_count"] or parse_float(row.get("review_count"))
        price = _row_price(row)
        if price is not None and (current["price"] is None or price < current["price"]):
            current["price"] = price
        if row.get("coupon_present"):
            current["coupon_present"] = True
        if row.get("deal_present"):
            current["deal_present"] = True
        organic_rank = parse_float(row.get("organic_rank"))
        ad_rank = parse_float(row.get("ad_rank"))
        bsr_rank = parse_float(row.get("bsr_rank"))
        category_list_rank = parse_float(row.get("category_list_rank"))
        if organic_rank is not None:
            current["best_organic_rank"] = min(current["best_organic_rank"] or organic_rank, organic_rank)
        if ad_rank is not None:
            current["best_ad_rank"] = min(current["best_ad_rank"] or ad_rank, ad_rank)
        previous_category_rank = current["best_category_list_rank"]
        current["best_bsr_rank"] = _min_rank(current["best_bsr_rank"], bsr_rank)
        current["best_category_list_rank"] = _min_rank(current["best_category_list_rank"], category_list_rank)
        category_source = first_text(row.get("category_candidate_source") or row.get("source"))
        if category_source and category_list_rank is not None:
            current["category_candidate_sources"].add(category_source)
            if previous_category_rank is None or category_list_rank <= previous_category_rank:
                current["category_rank_source"] = category_source

    selected: List[Dict[str, Any]] = []
    for asin, row in aggregated.items():
        score = len(row["keywords"]) * 10.0
        why = ["keyword_serp_overlap"] if row["keywords"] else []
        if asin in pinned:
            score += 1000.0
            why.append("operator_pinned")
        if row["best_ad_rank"] is not None:
            score += 12.0
            why.append("sponsored_visibility")
        if row["best_organic_rank"] is not None and row["best_organic_rank"] <= 10:
            score += 10.0
            why.append("top_organic_rank")
        if row["coupon_present"] or row["deal_present"]:
            score += 6.0
            why.append("commercial_pressure")
        if row["best_bsr_rank"] is not None or row["best_category_list_rank"] is not None:
            score += 8.0
            why.append("category_or_bestseller_presence")
        if "pangolin:amzNewReleases" in row["category_candidate_sources"]:
            score += 5.0
            why.append("new_release_presence")
        out = {
            "asin": asin,
            "score": round(score, 4),
            "tier": "candidate",
            "why_selected": why,
            "rank_relationship": {
                "best_organic_rank": row["best_organic_rank"],
                "best_ad_rank": row["best_ad_rank"],
                "best_bsr_rank": row["best_bsr_rank"],
                "best_category_list_rank": row["best_category_list_rank"],
                "category_rank_source": row["category_rank_source"],
            },
            "keywords": sorted(keyword for keyword in row["keywords"] if keyword),
            "price": row["price"],
            "coupon_present": row["coupon_present"],
            "deal_present": row["deal_present"],
            "rating": row["rating"],
            "review_count": row["review_count"],
            "title": row["title"],
            "data_sources": sorted(row["data_sources"]),
        }
        selected.append(out)
    selected.sort(key=lambda item: (-item["score"], item["asin"]))
    for idx, row in enumerate(selected[:top_n]):
        row["tier"] = "primary_monitor" if idx < 3 else ("secondary_monitor" if idx < 6 else "watchlist")
    return selected[:top_n]


def build_public_context(
    *,
    asin: str,
    marketplace: str,
    zipcode: str,
    core_keywords: Iterable[str],
    pinned_competitor_asins: Iterable[str],
    excluded_competitor_asins: Iterable[str],
    client: Any = None,
    max_competitors: int = 10,
    category_rankings_enabled: bool = True,
    category_keyword: Optional[str] = None,
    include_product_of_category: bool = True,
    include_best_sellers: bool = True,
    include_new_releases: bool = True,
    max_keywords: int = 3,
    leaf_category_label: Optional[str] = None,
    leaf_category_node_id: Optional[str] = None,
    best_sellers_url: Optional[str] = None,
    new_releases_url: Optional[str] = None,
    direct_url_fallback_enabled: bool = True,
    direct_url_timeout: int = 8,
    direct_url_fetcher: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    site = SITE_BY_MARKETPLACE.get(marketplace, f"amz_{marketplace.lower()}")
    own_asin = asin.upper()
    pangolin = client or PangolinClient()
    listing_raw = pangolin.product_detail(asin=own_asin, site=site, zipcode=zipcode)
    listing = normalize_public_listing({**listing_raw, "asin": listing_raw.get("asin") or own_asin}, source="pangolin:amzProductDetail", zipcode=zipcode)
    keyword_limit = max(int(max_keywords or 0), 0)
    keywords = [keyword.strip() for keyword in core_keywords if str(keyword).strip()][:keyword_limit]
    rank_rows: List[Dict[str, Any]] = []
    competitor_rows: List[Dict[str, Any]] = []
    category_candidates: List[Dict[str, Any]] = []
    bsr_capture_attempts: List[Dict[str, Any]] = []
    context_failures: List[str] = []
    own_category_rank: Dict[str, Any] = _own_bsr_ranks_from_listing(listing)
    for keyword in keywords:
        try:
            rows = pangolin.keyword_search(keyword=keyword, site=site, zipcode=zipcode)
        except Exception as exc:
            rank_rows.append(_failed_keyword_rank(keyword, exc))
            context_failures.append(f"keyword_search failed for {keyword}: {_short_error(exc)}")
            continue
        rank, competitors = _rank_rows_for_keyword(keyword, rows, own_asin)
        rank_rows.append(rank)
        competitor_rows.extend(competitors)

    category_labels = _with_configured_leaf_category(
        _category_rank_labels(listing, keywords, category_keyword),
        leaf_category_label=leaf_category_label,
        leaf_category_node_id=leaf_category_node_id,
        best_sellers_url=best_sellers_url,
        new_releases_url=new_releases_url,
    )
    category_label = category_labels[-1]["label"] if category_labels else _category_keyword(listing, keywords, category_keyword)
    product_detail_bsr_recorded = False
    if own_category_rank.get("own_bsr_leaf_rank") is not None:
        bsr_capture_attempts.append(
            {
                "source": "pangolin:amzProductDetail",
                "category": own_category_rank.get("own_bsr_leaf_category") or category_label,
                "category_node_id": first_text(leaf_category_node_id),
                "category_url": first_text(best_sellers_url),
                "rank_level": "leaf",
                "bsr_capture_status": "measured",
                "bsr_result_count": 1,
                "bsr_window_size": 1,
            }
        )
        product_detail_bsr_recorded = True
    category_sources: List[Dict[str, Any]] = []
    if category_rankings_enabled:
        product_category_id = first_text(leaf_category_node_id) or first_text(listing.get("category_id"))
        if include_product_of_category and product_category_id:
            product_category = category_labels[-1] if category_labels else {"label": str(category_label or listing.get("category_id") or "category"), "rank_level": "configured"}
            category_sources.append(
                {
                    "source": "pangolin:amzProductOfCategory",
                    "category_label": str(product_category["label"]),
                    "rank_level": str(product_category["rank_level"]),
                    "category_node_id": product_category_id,
                    "category_url": None,
                    "fetch": lambda category_id=product_category_id: pangolin.product_of_category(category_id=str(category_id), site=site, zipcode=zipcode),
                }
            )
        if include_best_sellers:
            for category in category_labels:
                label = str(category["label"])
                category_sources.append(
                    {
                        "source": "pangolin:amzBestSellers",
                        "category_label": label,
                        "rank_level": str(category["rank_level"]),
                        "category_node_id": first_text(category.get("category_node_id")),
                        "category_url": first_text(category.get("best_sellers_url")),
                        "fetch": lambda category=category, label=label: pangolin.best_sellers(
                            category_keyword=label,
                            site=site,
                            zipcode=zipcode,
                            category_node_id=first_text(category.get("category_node_id")) or "",
                            category_url=first_text(category.get("best_sellers_url")) or "",
                        ),
                    }
                )
        if include_new_releases:
            for category in category_labels:
                label = str(category["label"])
                category_sources.append(
                    {
                        "source": "pangolin:amzNewReleases",
                        "category_label": label,
                        "rank_level": str(category["rank_level"]),
                        "category_node_id": first_text(category.get("category_node_id")),
                        "category_url": first_text(category.get("new_releases_url")),
                        "fetch": lambda category=category, label=label: pangolin.new_releases(
                            category_keyword=label,
                            site=site,
                            zipcode=zipcode,
                            category_node_id=first_text(category.get("category_node_id")) or "",
                            category_url=first_text(category.get("new_releases_url")) or "",
                        ),
                    }
                )
    for category_source in category_sources:
        source = str(category_source["source"])
        source_category_label = str(category_source["category_label"])
        rank_level = str(category_source["rank_level"])
        category_node_id = first_text(category_source.get("category_node_id"))
        category_url = first_text(category_source.get("category_url"))
        fetch_rows = category_source["fetch"]
        try:
            rows = fetch_rows()
        except Exception as exc:
            bsr_capture_attempts.append(
                _bsr_capture_failed(
                    source=source,
                    category_label=source_category_label,
                    error=exc,
                    category_node_id=category_node_id,
                    category_url=category_url,
                )
            )
            context_failures.append(f"{source} failed for {source_category_label}: {_short_error(exc)}")
            continue
        normalized, own_rank, attempts = _normalize_category_rows(
            rows=rows,
            source=source,
            category_label=source_category_label,
            rank_level=rank_level,
            own_asin=own_asin,
            category_node_id=category_node_id,
            category_url=category_url,
        )
        category_candidates.extend(normalized)
        competitor_rows.extend([row for row in normalized if row.get("competitor_asin") != own_asin])
        bsr_capture_attempts.extend(attempts)
        own_category_rank.update({key: value for key, value in own_rank.items() if value is not None})

    if direct_url_fallback_enabled and own_category_rank.get("own_bsr_leaf_rank") is None and first_text(best_sellers_url):
        leaf_label = first_text(leaf_category_label) or str(category_label or "category")
        source = "amazon:directBestSellersUrl"
        category_url = first_text(best_sellers_url)
        category_node_id = first_text(leaf_category_node_id)
        fetcher = direct_url_fetcher or fetch_amazon_rank_rows_from_url
        try:
            rows = fetcher(
                category_url,
                asin=own_asin,
                category_label=leaf_label,
                source=source,
                timeout=direct_url_timeout,
            )
        except Exception as exc:
            bsr_capture_attempts.append(
                _bsr_capture_failed(
                    source=source,
                    category_label=leaf_label,
                    error=exc,
                    category_node_id=category_node_id,
                    category_url=category_url,
                )
            )
            context_failures.append(f"{source} failed for {leaf_label}: {_short_error(exc)}")
        else:
            normalized, own_rank, attempts = _normalize_category_rows(
                rows=rows,
                source=source,
                category_label=leaf_label,
                rank_level="leaf",
                own_asin=own_asin,
                category_node_id=category_node_id,
                category_url=category_url,
            )
            category_candidates.extend(normalized)
            competitor_rows.extend([row for row in normalized if row.get("competitor_asin") != own_asin])
            bsr_capture_attempts.extend(attempts)
            own_category_rank.update({key: value for key, value in own_rank.items() if value is not None})

    if direct_url_fallback_enabled and own_category_rank.get("own_new_release_leaf_rank") is None and first_text(new_releases_url):
        leaf_label = first_text(leaf_category_label) or str(category_label or "category")
        source = "amazon:directNewReleasesUrl"
        category_url = first_text(new_releases_url)
        category_node_id = first_text(leaf_category_node_id)
        fetcher = direct_url_fetcher or fetch_amazon_rank_rows_from_url
        try:
            rows = fetcher(
                category_url,
                asin=own_asin,
                category_label=leaf_label,
                source=source,
                timeout=direct_url_timeout,
            )
        except Exception as exc:
            bsr_capture_attempts.append(
                _bsr_capture_failed(
                    source=source,
                    category_label=leaf_label,
                    error=exc,
                    category_node_id=category_node_id,
                    category_url=category_url,
                )
            )
            context_failures.append(f"{source} failed for {leaf_label}: {_short_error(exc)}")
        else:
            normalized, own_rank, attempts = _normalize_category_rows(
                rows=rows,
                source=source,
                category_label=leaf_label,
                rank_level="leaf",
                own_asin=own_asin,
                category_node_id=category_node_id,
                category_url=category_url,
            )
            category_candidates.extend(normalized)
            competitor_rows.extend([row for row in normalized if row.get("competitor_asin") != own_asin])
            bsr_capture_attempts.extend(attempts)
            own_category_rank.update({key: value for key, value in own_rank.items() if value is not None})

    selected_keywords = [
        {
            "keyword": row["keyword"],
            "tier": "primary_core" if idx < 3 else "secondary_core",
            "rank_status": row["rank_status"],
            "own_organic_rank": row["own_organic_rank"],
            "own_ad_rank": row["own_ad_rank"],
            "source": row["source"],
            "freshness": row["freshness"],
            "confidence": row["confidence"],
            "missing_fields": row["missing_fields"],
        }
        for idx, row in enumerate(rank_rows)
    ]
    selected_competitors = _score_competitors(
        competitor_rows,
        pinned={str(item).upper() for item in pinned_competitor_asins},
        excluded={own_asin, *{str(item).upper() for item in excluded_competitor_asins}},
        top_n=max_competitors,
    )
    listing_bsr_rank = parse_int(listing.get("best_sellers_rank"))
    if own_category_rank.get("own_bsr_leaf_rank") is None and listing_bsr_rank is not None:
        _set_own_category_rank(
            own_category_rank,
            metric="bsr",
            rank_level="leaf",
            rank=listing_bsr_rank,
            category_label=str(listing.get("category_name") or category_label or "category"),
            source="pangolin:amzProductDetail",
        )
    if not product_detail_bsr_recorded and own_category_rank.get("own_bsr_leaf_source") == "pangolin:amzProductDetail":
        bsr_capture_attempts.append(
            {
                "source": "pangolin:amzProductDetail",
                "category": own_category_rank.get("own_bsr_leaf_category") or category_label,
                "category_node_id": first_text(leaf_category_node_id),
                "category_url": first_text(best_sellers_url),
                "rank_level": "leaf",
                "bsr_capture_status": "measured",
                "bsr_result_count": 1,
                "bsr_window_size": 1,
            }
        )
    if own_category_rank.get("own_bsr_rank") is None:
        own_category_rank["own_bsr_rank"] = own_category_rank.get("own_bsr_leaf_rank") or own_category_rank.get("own_bsr_major_rank")
        own_category_rank["own_bsr_category"] = own_category_rank.get("own_bsr_leaf_category") or own_category_rank.get("own_bsr_major_category")
        own_category_rank["own_bsr_source"] = own_category_rank.get("own_bsr_leaf_source") or own_category_rank.get("own_bsr_major_source")
    if own_category_rank.get("own_new_release_rank") is None:
        own_category_rank["own_new_release_rank"] = own_category_rank.get("own_new_release_leaf_rank") or own_category_rank.get("own_new_release_major_rank")
        own_category_rank["own_new_release_category"] = own_category_rank.get("own_new_release_leaf_category") or own_category_rank.get("own_new_release_major_category")
        own_category_rank["own_new_release_source"] = own_category_rank.get("own_new_release_leaf_source") or own_category_rank.get("own_new_release_major_source")
    successful_bsr = [row for row in bsr_capture_attempts if row.get("bsr_capture_status") != "bsr_capture_failed"]
    failed_bsr = [row for row in bsr_capture_attempts if row.get("bsr_capture_status") == "bsr_capture_failed"]
    if successful_bsr:
        bsr_capture_status = "measured" if any(row.get("bsr_capture_status") == "measured" for row in successful_bsr) else "not_in_bsr_window"
    elif failed_bsr:
        bsr_capture_status = "bsr_capture_failed"
    else:
        bsr_capture_status = "not_configured"
    bsr_result_count = sum(int(row.get("bsr_result_count") or 0) for row in successful_bsr)
    bsr_window_source = ", ".join(sorted({str(row.get("source")) for row in bsr_capture_attempts if row.get("source")}))
    return {
        "public_listing": listing,
        "public_context_status": _context_status_from_failures(
            context_failures,
            freshness=listing.get("freshness") if isinstance(listing, Mapping) else now_iso(),
        ),
        "core_keywords": selected_keywords,
        "rank": {
            "core_keyword_ranks": rank_rows,
            "bsr_capture_attempts": bsr_capture_attempts,
            "bsr_capture_status": bsr_capture_status,
            "bsr_result_count": bsr_result_count,
            "bsr_window_source": bsr_window_source or None,
            **own_category_rank,
            "source": "pangolin:amzKeyword",
            "freshness": now_iso(),
            "confidence": "measured" if any(row["rank_status"] == "measured" for row in rank_rows) else "estimated",
            "missing_fields": [field for row in rank_rows for field in row["missing_fields"]],
        },
        "market": {
            "category_average_cvr": None,
            "category_average_cvr_source": None,
            "category_candidates": category_candidates,
            "selected_competitors": selected_competitors,
            "selected_competitors_source": "src.public_context",
            "source": "src.public_context",
            "freshness": now_iso(),
            "confidence": "measured" if selected_competitors else "missing",
            "missing_fields": [] if selected_competitors else ["selected_competitors"],
        },
    }
