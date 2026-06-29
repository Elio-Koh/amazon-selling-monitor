from pathlib import Path

from scripts.build_b0gxyyzpbw_daily_ctr_report import (
    ASIN,
    CHART_START_DATE,
    END_DATE,
    START_DATE,
    build_report,
    campaign_rows,
    daily_summary_rows,
    tos_summary_rows,
)


def test_daily_summary_covers_requested_window_and_june_16_sample():
    rows = daily_summary_rows()

    assert len(rows) == 12
    assert START_DATE == "2026-06-10"
    assert END_DATE == "2026-06-21"
    assert rows[0]["date"] == "2026-06-10"
    assert rows[-1]["date"] == "2026-06-21"

    june_16 = next(row for row in rows if row["date"] == "2026-06-16")
    assert june_16["impressions"] == 21415
    assert june_16["clicks"] == 196
    assert round(june_16["ctr_pct"], 2) == 0.92

    june_21 = next(row for row in rows if row["date"] == "2026-06-21")
    assert june_21["impressions"] == 83004
    assert june_21["clicks"] == 406
    assert round(june_21["ctr_pct"], 2) == 0.49


def test_campaign_rows_recompute_ctr_from_clicks_and_impressions():
    rows = campaign_rows()
    june_16_manual = next(
        row
        for row in rows
        if row["date"] == "2026-06-16"
        and row["campaign_id"] == "173844737302109"
    )

    expected_ctr = june_16_manual["clicks"] / june_16_manual["impressions"] * 100
    assert june_16_manual["ctr_pct"] == expected_ctr


def test_tos_summary_uses_top_of_search_impression_share():
    rows = tos_summary_rows()
    june_10 = next(row for row in rows if row["date"] == "2026-06-10")

    assert june_10["tos_impressions"] == 39
    assert june_10["placement_impressions"] == 42188
    assert round(june_10["tos_impression_share_pct"], 2) == 0.09

    june_21 = next(row for row in rows if row["date"] == "2026-06-21")
    assert june_21["tos_impressions"] == 7299
    assert june_21["placement_impressions"] == 81382
    assert round(june_21["tos_impression_share_pct"], 2) == 8.97


def test_build_report_writes_offline_html_and_csv(tmp_path):
    outputs = build_report(tmp_path)

    html_path = Path(outputs["html_path"])
    csv_path = Path(outputs["csv_path"])
    assert html_path.exists()
    assert csv_path.exists()

    html = html_path.read_text(encoding="utf-8")
    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()

    assert ASIN in html
    assert CHART_START_DATE == "2026-06-10"
    assert "2026-06-09 及以前无曝光数据" in html
    assert "图表日期范围：2026-06-10 至 2026-06-21" in html
    assert "TOS 曝光占比" in html
    assert "右轴：TOS 曝光占比" in html
    assert "<svg" in html
    assert html.count("<svg") >= 2
    assert "ASIN 汇总每日 CTR" in html
    assert "Campaign 级每日 CTR" in html
    assert len(csv_lines) == len(campaign_rows()) + 1
    assert "tos_impressions,placement_impressions,tos_impression_share_pct" in csv_lines[0]
