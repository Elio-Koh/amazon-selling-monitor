from src.metrics import build_dashboard_summary, summarize_advertising


def test_summarize_advertising_computes_sp_and_all_ads_separately():
    sp_campaigns = [
        {"spend": 100, "sales": 250, "orders": 10, "clicks": 200, "impressions": 10000},
    ]
    all_campaigns = [
        {"spend": 100, "sales": 250, "orders": 10, "clicks": 200, "impressions": 10000, "ad_product": "SP"},
        {"spend": 40, "sales": 80, "orders": 4, "clicks": 100, "impressions": 5000, "ad_product": "SB"},
        {"spend": 10, "sales": 0, "orders": 0, "clicks": 20, "impressions": 1500, "ad_product": "unknown"},
    ]

    summary = summarize_advertising(
        sp_campaigns=sp_campaigns,
        all_campaigns=all_campaigns,
        total_sales=1000,
        total_orders=50,
    )

    assert summary["sp"]["spend"] == 100
    assert summary["sp"]["acos"] == 0.4
    assert summary["sp"]["tacos"] == 0.1
    assert summary["sp"]["order_share"] == 0.2
    assert summary["all_ads"]["spend"] == 150
    assert summary["all_ads"]["acos"] == round(150 / 330, 4)
    assert summary["all_ads"]["tacos"] == 0.15
    assert summary["by_product"]["SB"]["spend"] == 40
    assert summary["by_product"]["unknown"]["spend"] == 10


def test_build_dashboard_summary_applies_user_targets():
    ad_summary = {
        "sp": {
            "spend": 180,
            "orders": 30,
            "sales": 420,
            "acos": 0.4286,
            "tacos": 0.18,
        },
        "all_ads": {
            "spend": 240,
            "orders": 38,
            "sales": 520,
            "acos": 0.4615,
            "tacos": 0.24,
        },
    }
    targets = {
        "sp_target_acos": 0.4993,
        "sp_daily_budget_current": 300,
        "sp_orders_daily_min": 22,
        "sp_orders_daily_max": 60,
    }

    summary = build_dashboard_summary(
        total_sales=1000,
        total_orders=80,
        total_units=90,
        ad_summary=ad_summary,
        targets=targets,
    )

    assert summary["sales"]["total_sales"] == 1000
    assert summary["sp_goal"]["acos_delta"] == round(0.4286 - 0.4993, 4)
    assert summary["sp_goal"]["budget_used_pct"] == 0.6
    assert summary["sp_goal"]["orders_status"] == "in_range"
    assert summary["sp_goal"]["orders_progress_min"] == round(30 / 22, 4)
    assert summary["sp_goal"]["orders_progress_max"] == 0.5
