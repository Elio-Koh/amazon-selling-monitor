"""Public Amazon context capture and normalization."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

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
        "delivery_promise": normalize_delivery(product.get("deliveryTime") or product.get("delivery")),
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
        if organic_rank is not None:
            current["best_organic_rank"] = min(current["best_organic_rank"] or organic_rank, organic_rank)
        if ad_rank is not None:
            current["best_ad_rank"] = min(current["best_ad_rank"] or ad_rank, ad_rank)

    selected: List[Dict[str, Any]] = []
    for asin, row in aggregated.items():
        score = len(row["keywords"]) * 10.0
        why = ["keyword_serp_overlap"]
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
        out = {
            "asin": asin,
            "score": round(score, 4),
            "tier": "candidate",
            "why_selected": why,
            "rank_relationship": {
                "best_organic_rank": row["best_organic_rank"],
                "best_ad_rank": row["best_ad_rank"],
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
) -> Dict[str, Any]:
    site = SITE_BY_MARKETPLACE.get(marketplace, f"amz_{marketplace.lower()}")
    own_asin = asin.upper()
    pangolin = client or PangolinClient()
    listing_raw = pangolin.product_detail(asin=own_asin, site=site, zipcode=zipcode)
    listing = normalize_public_listing({**listing_raw, "asin": listing_raw.get("asin") or own_asin}, source="pangolin:amzProductDetail", zipcode=zipcode)
    keywords = [keyword.strip() for keyword in core_keywords if str(keyword).strip()]
    rank_rows: List[Dict[str, Any]] = []
    competitor_rows: List[Dict[str, Any]] = []
    for keyword in keywords:
        rows = pangolin.keyword_search(keyword=keyword, site=site, zipcode=zipcode)
        rank, competitors = _rank_rows_for_keyword(keyword, rows, own_asin)
        rank_rows.append(rank)
        competitor_rows.extend(competitors)

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
        excluded={str(item).upper() for item in excluded_competitor_asins},
        top_n=max_competitors,
    )
    return {
        "public_listing": listing,
        "core_keywords": selected_keywords,
        "rank": {
            "core_keyword_ranks": rank_rows,
            "source": "pangolin:amzKeyword",
            "freshness": now_iso(),
            "confidence": "measured" if any(row["rank_status"] == "measured" for row in rank_rows) else "estimated",
            "missing_fields": [field for row in rank_rows for field in row["missing_fields"]],
        },
        "market": {
            "category_average_cvr": None,
            "category_average_cvr_source": None,
            "selected_competitors": selected_competitors,
            "selected_competitors_source": "src.public_context",
            "source": "pangolin:amzKeyword",
            "freshness": now_iso(),
            "confidence": "measured" if selected_competitors else "missing",
            "missing_fields": [] if selected_competitors else ["selected_competitors"],
        },
    }
