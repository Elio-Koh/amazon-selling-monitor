"""Advertising scope classification for SP and all-ad reporting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Set


NON_SP_RE = re.compile(r"(^|[^A-Z0-9])(SBV?|SD)([^A-Z0-9]|$)", re.IGNORECASE)
SP_TOKEN_RE = re.compile(r"(^|[^A-Z0-9])SP([^A-Z0-9]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class AdScopeResolution:
    campaign_id: str
    campaign_name: str
    targeting_type: str
    status: str
    ad_product: str
    evidence_type: str
    note: str = ""


@dataclass(frozen=True)
class AdScopeSplit:
    sp_campaigns: List[Dict[str, object]]
    all_campaigns: List[Dict[str, object]]
    resolutions: List[AdScopeResolution]


class AdScopeResolver:
    """Resolve campaign rows into SP, non-SP, or unknown buckets.

    This follows the amazon-ad-goal-generator boundary: SP target metrics must
    be proven SP-only; mixed or unknown campaigns can still appear in all-ad
    reporting.
    """

    def __init__(
        self,
        whitelist: Optional[Iterable[str]] = None,
        route_scope: str = "",
    ) -> None:
        self.whitelist: Set[str] = {
            str(item).strip() for item in (whitelist or []) if str(item).strip()
        }
        self.route_scope = route_scope

    def resolve(self, campaign: Mapping[str, object]) -> AdScopeResolution:
        campaign_id = str(campaign.get("campaign_id") or campaign.get("id") or "").strip()
        campaign_name = str(campaign.get("campaign_name") or campaign.get("name") or "").strip()
        targeting_type = str(campaign.get("targeting_type") or "").strip().lower()
        raw_ad_product = str(
            campaign.get("ad_product_type")
            or campaign.get("advertising_product_type")
            or campaign.get("ad_product")
            or ""
        ).strip().upper()

        if raw_ad_product in {"SB", "SBV", "SD"}:
            return AdScopeResolution(
                campaign_id,
                campaign_name,
                targeting_type,
                "excluded",
                raw_ad_product,
                "explicit_non_sp_ad_product_type",
            )
        if NON_SP_RE.search(campaign_name):
            detected = self._detect_non_sp_from_name(campaign_name)
            return AdScopeResolution(
                campaign_id,
                campaign_name,
                targeting_type,
                "excluded",
                detected,
                "negative_sb_sd_token",
            )
        if raw_ad_product == "SP" or any(str(key).startswith("sp_") for key in campaign.keys()):
            return AdScopeResolution(
                campaign_id,
                campaign_name,
                targeting_type,
                "sp_verified",
                "SP",
                "explicit_sp_field",
            )
        if campaign_id and campaign_id in self.whitelist:
            return AdScopeResolution(
                campaign_id,
                campaign_name,
                targeting_type,
                "sp_verified",
                "SP",
                "campaign_id_whitelist",
            )
        if self.route_scope in {"sp_campaign_route", "sp_scope_inferred_from_route"}:
            return AdScopeResolution(
                campaign_id,
                campaign_name,
                targeting_type,
                "sp_verified",
                "SP",
                "sp_scope_inferred_from_route",
            )
        if SP_TOKEN_RE.search(campaign_name):
            return AdScopeResolution(
                campaign_id,
                campaign_name,
                targeting_type,
                "sp_inferred",
                "SP",
                "campaign_name_sp_token",
            )
        return AdScopeResolution(
            campaign_id,
            campaign_name,
            targeting_type,
            "unknown",
            "unknown",
            "missing_ad_product_evidence",
        )

    @staticmethod
    def _detect_non_sp_from_name(campaign_name: str) -> str:
        upper = campaign_name.upper()
        if re.search(r"(^|[^A-Z0-9])SBV([^A-Z0-9]|$)", upper):
            return "SBV"
        if re.search(r"(^|[^A-Z0-9])SB([^A-Z0-9]|$)", upper):
            return "SB"
        if re.search(r"(^|[^A-Z0-9])SD([^A-Z0-9]|$)", upper):
            return "SD"
        return "non_sp"


def split_campaigns_by_scope(
    campaigns: Iterable[Mapping[str, object]],
    resolver: AdScopeResolver,
) -> AdScopeSplit:
    sp_campaigns: List[Dict[str, object]] = []
    all_campaigns: List[Dict[str, object]] = []
    resolutions: List[AdScopeResolution] = []

    for campaign in campaigns:
        resolution = resolver.resolve(campaign)
        resolutions.append(resolution)
        row = dict(campaign)
        row["ad_product"] = resolution.ad_product
        row["ad_scope_status"] = resolution.status
        row["ad_scope_evidence"] = resolution.evidence_type
        all_campaigns.append(row)
        if resolution.status in {"sp_verified", "sp_inferred"}:
            sp_campaigns.append(row)

    return AdScopeSplit(
        sp_campaigns=sp_campaigns,
        all_campaigns=all_campaigns,
        resolutions=resolutions,
    )
