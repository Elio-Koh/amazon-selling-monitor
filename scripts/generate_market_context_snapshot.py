#!/usr/bin/env python3
"""Generate a complete Market Context snapshot for scheduled publishing."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_targets
from src.market_context_snapshot import encrypt_snapshot, validate_market_context_snapshot
from src.pangolin_client import PangolinClient
from src.public_context import build_public_context, now_iso


ENV_TARGET_OVERRIDES = {
    "MARKET_CONTEXT_ASIN": "asin",
    "MARKET_CONTEXT_MARKETPLACE": "marketplace",
    "MARKET_CONTEXT_PANGOLIN_ZIPCODE": "pangolin_zipcode",
    "MARKET_CONTEXT_LEAF_CATEGORY_LABEL": "pangolin_leaf_category_label",
    "MARKET_CONTEXT_LEAF_CATEGORY_NODE_ID": "pangolin_leaf_category_node_id",
    "MARKET_CONTEXT_BEST_SELLERS_URL": "pangolin_best_sellers_url",
    "MARKET_CONTEXT_NEW_RELEASES_URL": "pangolin_new_releases_url",
    "MARKET_CONTEXT_PRODUCT_URL": "amazon_product_url",
}


def targets_with_env_overrides(targets: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply private snapshot target settings from GitHub Actions secrets."""
    resolved = dict(targets)
    for env_name, target_key in ENV_TARGET_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value:
            resolved[target_key] = value
    keywords = os.environ.get("MARKET_CONTEXT_CORE_KEYWORDS")
    if keywords:
        resolved["core_keywords"] = [item.strip() for item in keywords.split(",") if item.strip()]
    pinned = os.environ.get("MARKET_CONTEXT_PINNED_COMPETITOR_ASINS")
    if pinned:
        resolved["pinned_competitor_asins"] = [item.strip() for item in pinned.split(",") if item.strip()]
    excluded = os.environ.get("MARKET_CONTEXT_EXCLUDED_COMPETITOR_ASINS")
    if excluded:
        resolved["excluded_competitor_asins"] = [item.strip() for item in excluded.split(",") if item.strip()]
    return resolved


def _int_value(targets: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(targets.get(key) or default)
    except (TypeError, ValueError):
        return default


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def build_snapshot(*, targets: Mapping[str, Any], api_token: str) -> Dict[str, Any]:
    asin = str(targets.get("asin") or "B0TEST0001")
    marketplace = str(targets.get("marketplace") or "US")
    context = build_public_context(
        asin=asin,
        marketplace=marketplace,
        zipcode=str(targets.get("pangolin_zipcode") or "10041"),
        core_keywords=_list_value(targets.get("core_keywords"))[: _int_value(targets, "pangolin_max_keywords", 3)],
        pinned_competitor_asins=_list_value(targets.get("pinned_competitor_asins")),
        excluded_competitor_asins=_list_value(targets.get("excluded_competitor_asins")),
        max_competitors=_int_value(targets, "max_competitors", 10),
        max_keywords=_int_value(targets, "pangolin_max_keywords", 3),
        category_rankings_enabled=bool(targets.get("pangolin_category_rankings_enabled", True)),
        category_keyword=str(targets.get("pangolin_category_keyword") or ""),
        include_product_of_category=bool(targets.get("pangolin_include_product_of_category", True)),
        include_best_sellers=bool(targets.get("pangolin_include_best_sellers", True)),
        include_new_releases=bool(targets.get("pangolin_include_new_releases", True)),
        leaf_category_label=str(targets.get("pangolin_leaf_category_label") or ""),
        leaf_category_node_id=str(targets.get("pangolin_leaf_category_node_id") or ""),
        best_sellers_url=str(targets.get("pangolin_best_sellers_url") or ""),
        new_releases_url=str(targets.get("pangolin_new_releases_url") or ""),
        product_url=str(targets.get("amazon_product_url") or ""),
        direct_url_fallback_enabled=bool(targets.get("amazon_direct_rank_fallback_enabled", True)),
        direct_url_timeout=_int_value(targets, "amazon_direct_rank_timeout_seconds", 4),
        direct_url_max_pages=_int_value(targets, "amazon_direct_rank_max_pages", 2),
        client=PangolinClient(
            api_token=api_token,
            timeout=_int_value(targets, "pangolin_request_timeout_seconds", 8),
        ),
    )
    snapshot = {
        "schema_version": "1.0",
        "snapshot_status": "complete",
        "captured_at": now_iso(),
        "source_versions": {
            "generator": "scripts/generate_market_context_snapshot.py",
            "context_source": context.get("market", {}).get("source"),
        },
        "market_context": context,
        "warnings": context.get("public_context_status", {}).get("warnings") or [],
    }
    return snapshot


def snapshot_diagnostics(snapshot: Mapping[str, Any]) -> str:
    context = snapshot.get("market_context") if isinstance(snapshot.get("market_context"), Mapping) else {}
    listing = context.get("public_listing") if isinstance(context.get("public_listing"), Mapping) else {}
    status = context.get("public_context_status") if isinstance(context.get("public_context_status"), Mapping) else {}
    rank = context.get("rank") if isinstance(context.get("rank"), Mapping) else {}

    def safe(value: Any) -> str:
        text = str(value or "")
        text = re.sub(r"https?://\S+", "[url-redacted]", text)
        text = re.sub(r"\bB0[A-Z0-9]{8}\b", "[asin-redacted]", text)
        return text

    attempts = []
    for attempt in rank.get("bsr_capture_attempts") or []:
        if not isinstance(attempt, Mapping):
            continue
        attempts.append(
            ":".join(
                [
                    safe(attempt.get("source") or "unknown"),
                    safe(attempt.get("rank_level") or "unknown"),
                    safe(attempt.get("bsr_capture_status") or "unknown"),
                    safe(attempt.get("bsr_result_count") if attempt.get("bsr_result_count") is not None else ""),
                ]
            )
        )

    pieces = [
        f"listing_source={safe(listing.get('source') or 'unknown')}",
        "listing_missing_fields=" + safe(", ".join(str(item) for item in listing.get("missing_fields") or [])),
        f"public_context_status={safe(status.get('status') or 'unknown')}",
        f"public_context_message={safe(status.get('message') or '')}",
        f"bsr_capture_status={safe(rank.get('bsr_capture_status') or 'unknown')}",
        f"bsr_capture_attempts={safe(', '.join(attempts) or 'none')}",
    ]
    return "; ".join(pieces)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=Path("config/targets.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encrypt", action="store_true", help="write encrypted snapshot envelope")
    return parser.parse_args(list(argv))


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    api_token = os.environ.get("PANGOLINFO_API_TOKEN") or os.environ.get("PANGOLIN_API_TOKEN")
    if not api_token:
        print("PANGOLINFO_API_TOKEN is required", file=sys.stderr)
        return 2
    encryption_key = os.environ.get("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY")
    if args.encrypt and not encryption_key:
        print("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY is required for encrypted output", file=sys.stderr)
        return 2
    if args.encrypt and not os.environ.get("MARKET_CONTEXT_ASIN"):
        print("MARKET_CONTEXT_ASIN is required for encrypted output", file=sys.stderr)
        return 2
    targets = targets_with_env_overrides(load_targets(args.targets))
    try:
        snapshot = build_snapshot(targets=targets, api_token=api_token)
        snapshot = validate_market_context_snapshot(snapshot)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.encrypt:
            payload = encrypt_snapshot(snapshot, key=str(encryption_key))
        else:
            payload = snapshot
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:
        snapshot = locals().get("snapshot")
        if isinstance(snapshot, Mapping):
            print(f"Market context snapshot diagnostics: {snapshot_diagnostics(snapshot)}", file=sys.stderr)
        print(f"Market context snapshot generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output), "captured_at": snapshot["captured_at"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
