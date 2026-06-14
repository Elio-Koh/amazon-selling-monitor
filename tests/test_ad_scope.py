from src.ad_scope import AdScopeResolver, split_campaigns_by_scope


def test_resolver_keeps_auto_and_manual_as_sp_when_route_scope_is_sp():
    resolver = AdScopeResolver(route_scope="sp_campaign_route")
    campaigns = [
        {
            "campaign_id": "auto-1",
            "campaign_name": "VC_B0TEST0001_Auto_Close",
            "targeting_type": "auto",
        },
        {
            "campaign_id": "manual-1",
            "campaign_name": "VC_B0TEST0001_manual_keyword",
            "targeting_type": "manual",
        },
    ]

    resolved = [resolver.resolve(campaign) for campaign in campaigns]

    assert [item.status for item in resolved] == ["sp_verified", "sp_verified"]
    assert {item.ad_product for item in resolved} == {"SP"}


def test_resolver_excludes_sb_sd_from_sp_but_keeps_them_in_all_ads():
    resolver = AdScopeResolver()
    campaigns = [
        {
            "campaign_id": "sp-1",
            "campaign_name": "LH-B0TEST0001-SP-exact",
            "spend": 30,
            "sales": 90,
        },
        {
            "campaign_id": "sb-1",
            "campaign_name": "LH_B0TEST0001_SB_brand",
            "spend": 20,
            "sales": 40,
        },
        {
            "campaign_id": "sd-1",
            "campaign_name": "LH_B0TEST0001_SD_retarget",
            "spend": 10,
            "sales": 15,
        },
    ]

    split = split_campaigns_by_scope(campaigns, resolver)

    assert [row["campaign_id"] for row in split.sp_campaigns] == ["sp-1"]
    assert {row["campaign_id"] for row in split.all_campaigns} == {"sp-1", "sb-1", "sd-1"}
    assert {row["ad_scope_status"] for row in split.all_campaigns} == {
        "sp_inferred",
        "excluded",
    }


def test_unknown_campaign_stays_in_all_ads_with_unknown_status():
    resolver = AdScopeResolver()
    campaign = {
        "campaign_id": "unknown-1",
        "campaign_name": "LH_B0TEST0001_launch",
        "spend": 12,
    }

    resolved = resolver.resolve(campaign)

    assert resolved.status == "unknown"
    assert resolved.ad_product == "unknown"
    assert resolved.evidence_type == "missing_ad_product_evidence"


def test_resolver_treats_auto_manual_campaign_type_as_sp_evidence():
    resolver = AdScopeResolver()
    campaigns = [
        {
            "campaign_id": "230170919088708",
            "campaign_name": "SC_B0TEST0001_MF04_Auto_260606",
            "campaign_type": "auto",
        },
        {
            "campaign_id": "173844737302109",
            "campaign_name": "SC_B0TEST0001_MF04_Frother_P_260610",
            "campaign_type": "manual",
        },
    ]

    resolved = [resolver.resolve(campaign) for campaign in campaigns]

    assert [item.status for item in resolved] == ["sp_verified", "sp_verified"]
    assert [item.evidence_type for item in resolved] == ["campaign_type_auto_manual", "campaign_type_auto_manual"]


def test_explicit_non_sp_ad_product_overrides_manual_campaign_type():
    resolver = AdScopeResolver()
    campaign = {
        "campaign_id": "sb-manual",
        "campaign_name": "Brand launch",
        "campaign_type": "manual",
        "ad_product_type": "SB",
    }

    resolved = resolver.resolve(campaign)

    assert resolved.status == "excluded"
    assert resolved.ad_product == "SB"
    assert resolved.evidence_type == "explicit_non_sp_ad_product_type"
